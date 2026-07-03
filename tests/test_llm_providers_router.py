"""
Router-level regression tests for the LLM Providers admin endpoint.

Covers:
- Web-search-only types (bing_v7, azure_foundry_agents) must be rejected if a
  user tries to mark one as `use_for_analysis=True` — either at create or update.
- The update endpoint must enforce the same per-type field requirements that
  the create endpoint already enforces (api_endpoint for bing_v7;
  api_endpoint for azure_foundry_agents).
"""
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.auth import get_current_user
from app import models


ADMIN_USER_ID = 1


@pytest.fixture()
def test_db():
    """Fresh in-memory SQLite DB with a single admin user seeded."""
    test_db_uri = "sqlite:///file:llmprovrouter?mode=memory&cache=shared"
    engine = create_engine(
        test_db_uri, connect_args={"check_same_thread": False, "uri": True}
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = TestingSessionLocal()
    try:
        db.add(models.User(
            id=ADMIN_USER_ID,
            email="admin@example.com",
            full_name="Admin",
            is_active=True,
            is_admin=True,
            is_invited=True,
        ))
        db.commit()
    finally:
        db.close()

    yield TestingSessionLocal

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _make_admin_client(SessionLocal):
    """TestClient with get_db / get_current_user overridden as a logged-in admin."""
    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_user(db: Session = Depends(get_db)):
        return db.query(models.User).filter(models.User.id == ADMIN_USER_ID).first()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    yield
    app.dependency_overrides.clear()


# ============================================================
# Finding #1: search-only providers cannot be analysis providers
# ============================================================

@pytest.mark.parametrize("bing_type,extra_fields", [
    ("bing_v7", {"api_endpoint": "https://api.bing.microsoft.com/"}),
    ("azure_foundry_agents", {
        "api_endpoint": "https://my-foundry.example/",
        "bing_connection_name": "bing-grounding",
    }),
])
def test_create_rejects_bing_with_use_for_analysis_true(test_db, bing_type, extra_fields):
    """A web-search-only provider with use_for_analysis=True would crash report generation
    because GenericLLMClient.call() has no branch for these api_types."""
    client = _make_admin_client(test_db)
    payload = {
        "provider_key": f"{bing_type}_test",
        "display_name": "Bing test",
        "api_type": bing_type,
        "model_name": "bing",
        "use_for_analysis": True,  # ← the disallowed combination
        "supports_web_search": True,
        **extra_fields,
    }
    resp = client.post("/admin/llm-providers", json=payload)
    assert resp.status_code == 400, resp.text
    assert "web-search-only" in resp.json()["detail"].lower() or "cannot be the analysis" in resp.json()["detail"].lower()


def test_create_allows_bing_when_use_for_analysis_false(test_db):
    """Same Bing config without use_for_analysis must succeed."""
    client = _make_admin_client(test_db)
    resp = client.post("/admin/llm-providers", json={
        "provider_key": "bing_v7_ok",
        "display_name": "Bing v7 OK",
        "api_type": "bing_v7",
        "model_name": "bing",
        "api_endpoint": "https://api.bing.microsoft.com/",
        "use_for_analysis": False,
        "supports_web_search": True,
    })
    assert resp.status_code in (200, 201), resp.text


# ============================================================
# Finding #2: update endpoint mirrors create-time validation
# ============================================================

def _seed_bing_provider(SessionLocal, api_type, **fields):
    """Insert a Bing provider directly into the DB so we can target it for updates."""
    db = SessionLocal()
    try:
        provider = models.LLMProvider(
            tenant_id=None,
            provider_key=f"{api_type}_seed",
            display_name=f"{api_type} seed",
            api_type=api_type,
            model_name="bing",
            is_enabled=True,
            supports_web_search=True,
            **fields,
        )
        db.add(provider)
        db.commit()
        db.refresh(provider)
        return provider.id
    finally:
        db.close()


def test_update_rejects_clearing_bing_v7_endpoint(test_db):
    """Trying to PUT api_endpoint=None on a bing_v7 provider must fail."""
    provider_id = _seed_bing_provider(
        test_db, "bing_v7", api_endpoint="https://api.bing.microsoft.com/"
    )
    client = _make_admin_client(test_db)
    resp = client.put(f"/admin/llm-providers/{provider_id}", json={"api_endpoint": None})
    assert resp.status_code == 400, resp.text
    assert "api_endpoint" in resp.json()["detail"]


def test_update_rejects_clearing_azure_foundry_agents_endpoint(test_db):
    """Trying to PUT api_endpoint=None on an azure_foundry_agents provider must fail."""
    provider_id = _seed_bing_provider(
        test_db, "azure_foundry_agents",
        api_endpoint="https://my-foundry.example/",
        bing_connection_name="bing-grounding",
    )
    client = _make_admin_client(test_db)
    resp = client.put(f"/admin/llm-providers/{provider_id}", json={"api_endpoint": None})
    assert resp.status_code == 400, resp.text
    assert "api_endpoint" in resp.json()["detail"]


def test_update_rejects_flipping_bing_to_analysis_provider(test_db):
    """Trying to PUT use_for_analysis=True on a Bing provider must fail."""
    provider_id = _seed_bing_provider(
        test_db, "bing_v7", api_endpoint="https://api.bing.microsoft.com/"
    )
    client = _make_admin_client(test_db)
    resp = client.put(
        f"/admin/llm-providers/{provider_id}", json={"use_for_analysis": True}
    )
    assert resp.status_code == 400, resp.text
    assert "web-search-only" in resp.json()["detail"].lower() or "cannot be the analysis" in resp.json()["detail"].lower()


# ============================================================
# Round-2 finding: use_for_analysis=True + is_enabled=False is a footgun.
# get_analysis_provider() silently falls back to the first enabled provider,
# so the user's intent ("use THIS provider for analysis") is ignored without
# any indication. Block it at config time so they get a clear error instead.
# ============================================================

def test_create_rejects_use_for_analysis_with_disabled(test_db):
    """A non-Bing provider that's use_for_analysis=True but is_enabled=False
    must be rejected at create — analysis would silently fall back to another
    provider, defeating the user's intent."""
    client = _make_admin_client(test_db)
    resp = client.post("/admin/llm-providers", json={
        "provider_key": "openai_disabled",
        "display_name": "OpenAI (disabled)",
        "api_type": "openai",
        "model_name": "gpt-4o",
        "use_for_analysis": True,
        "is_enabled": False,  # ← the bad combination
        "supports_web_search": False,
    })
    assert resp.status_code == 400, resp.text
    assert "enabled" in resp.json()["detail"].lower()


def test_update_rejects_disabling_a_provider_that_is_use_for_analysis(test_db):
    """PUT is_enabled=False on a provider whose use_for_analysis=True must fail."""
    # Seed an OpenAI provider with use_for_analysis=True and is_enabled=True.
    db = test_db()
    try:
        p = models.LLMProvider(
            tenant_id=None,
            provider_key="openai_seed",
            display_name="OpenAI seed",
            api_type="openai",
            model_name="gpt-4o",
            is_enabled=True,
            use_for_analysis=True,
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        provider_id = p.id
    finally:
        db.close()

    client = _make_admin_client(test_db)
    resp = client.put(
        f"/admin/llm-providers/{provider_id}", json={"is_enabled": False}
    )
    assert resp.status_code == 400, resp.text
    assert "enabled" in resp.json()["detail"].lower()


def test_update_rejects_setting_use_for_analysis_on_disabled_provider(test_db):
    """PUT use_for_analysis=True on a provider whose is_enabled=False must fail
    (caller forgot to also flip is_enabled)."""
    db = test_db()
    try:
        p = models.LLMProvider(
            tenant_id=None,
            provider_key="openai_dormant",
            display_name="OpenAI dormant",
            api_type="openai",
            model_name="gpt-4o",
            is_enabled=False,  # already disabled
            use_for_analysis=False,
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        provider_id = p.id
    finally:
        db.close()

    client = _make_admin_client(test_db)
    resp = client.put(
        f"/admin/llm-providers/{provider_id}", json={"use_for_analysis": True}
    )
    assert resp.status_code == 400, resp.text
    assert "enabled" in resp.json()["detail"].lower()
