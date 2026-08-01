"""
Router-level regression tests for GET /responses/.

Covers the three bugs that caused the Tales descriptor-analytics page to
display 0% for shared brands and large brands:
- Bug #1 — shared-brand support: shared users couldn't see the owner's responses
  because the endpoint filtered by `current_user.id` instead of the brand owner.
- Bug #2 — `batch_id` query param was silently dropped (no FastAPI param).
- Bug #3 — default limit=100 was too small for real-world brands.
"""
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.auth import get_current_user
from app.utils.brand_access import get_active_brand_id
from app import models


OWNER_USER_ID = 100
SHARED_USER_ID = 200
BRAND_ID = 50


@pytest.fixture()
def test_db():
    """Fresh in-memory SQLite DB with two users, one brand owned by the
    OWNER user and shared with the SHARED user, plus seeded responses
    across two batches.
    """
    test_db_uri = "sqlite:///file:responsesroutertest?mode=memory&cache=shared&uri=true"
    engine = create_engine(test_db_uri, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = TestingSessionLocal()
    try:
        # Owner and a separate user who has the brand shared with them.
        db.add(models.User(
            id=OWNER_USER_ID, email="owner@example.com", full_name="Owner",
            is_active=True, is_admin=False, is_invited=True,
        ))
        db.add(models.User(
            id=SHARED_USER_ID, email="shared@example.com", full_name="Shared",
            is_active=True, is_admin=False, is_invited=True,
        ))
        db.add(models.BrandInfo(
            id=BRAND_ID, user_id=OWNER_USER_ID, brand_name="Princeton Engineering",
            is_active=True,
        ))
        db.add(models.BrandShare(
            brand_id=BRAND_ID, user_id=SHARED_USER_ID,
            shared_by_user_id=OWNER_USER_ID, permission_level="edit",
        ))
        # 3 responses in batch 1, 2 responses in batch 2 — all owned by the OWNER.
        for i in range(3):
            db.add(models.Response(
                user_id=OWNER_USER_ID, brand_id=BRAND_ID, batch_id=1,
                query_id=f"QB1{i}", query_text="Test", platform="Claude",
                response_text=f"Owner batch 1 response {i}",
            ))
        for i in range(2):
            db.add(models.Response(
                user_id=OWNER_USER_ID, brand_id=BRAND_ID, batch_id=2,
                query_id=f"QB2{i}", query_text="Test", platform="Claude",
                response_text=f"Owner batch 2 response {i}",
            ))
        db.commit()
    finally:
        db.close()

    yield TestingSessionLocal

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _make_client(SessionLocal, as_user_id: int, active_brand_id: int):
    """Build a TestClient with get_db / get_current_user / get_active_brand_id
    overridden to the requested user and active brand.

    `override_get_current_user` takes the request's DB session via Depends so
    the returned User stays attached for the lifetime of the request. The
    earlier version opened a fresh session and closed it before returning the
    User, which would raise DetachedInstanceError if any handler ever touched
    a lazy-loaded attribute (relationships, deferred columns). The current
    route only reads `current_user.id` so it never triggered, but the pattern
    is fragile — Depends fixes it for good.
    """
    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_user(db: Session = Depends(get_db)):
        return db.query(models.User).filter(models.User.id == as_user_id).first()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_active_brand_id] = lambda: active_brand_id
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    yield
    app.dependency_overrides.clear()


def test_shared_brand_responses_visible_to_shared_user(test_db):
    """Bug #1 regression: a user with a shared brand must see the owner's responses.

    Pre-fix, the endpoint filtered by `current_user.id == SHARED_USER_ID`
    and matched zero rows because every response was owned by OWNER_USER_ID.
    Post-fix, `get_data_owner_user_id` resolves the brand owner and returns
    their data.
    """
    client = _make_client(test_db, as_user_id=SHARED_USER_ID, active_brand_id=BRAND_ID)
    resp = client.get(f"/responses/?brand_id={BRAND_ID}")
    assert resp.status_code == 200
    body = resp.json()
    # All 5 responses in the brand should be returned (owner + shared user identical view).
    # Pre-fix: 0 rows. Post-fix: 5 rows.
    assert len(body) == 5
    assert all("Owner batch" in r["response_text"] for r in body)


def test_batch_id_query_param_filters_results(test_db):
    """Bug #2 regression: the batch_id query param must actually filter."""
    client = _make_client(test_db, as_user_id=OWNER_USER_ID, active_brand_id=BRAND_ID)

    in_batch_1 = client.get(f"/responses/?brand_id={BRAND_ID}&batch_id=1").json()
    in_batch_2 = client.get(f"/responses/?brand_id={BRAND_ID}&batch_id=2").json()
    no_filter = client.get(f"/responses/?brand_id={BRAND_ID}").json()

    assert len(in_batch_1) == 3
    assert all("batch 1" in r["response_text"] for r in in_batch_1)
    assert len(in_batch_2) == 2
    assert all("batch 2" in r["response_text"] for r in in_batch_2)
    assert len(no_filter) == 5


def test_limit_clamp_rejects_negative_and_oversize(test_db):
    """Defensive clamp: limit is bounded to [1, 10000].

    A negative limit would otherwise return an empty result silently; a
    pathologically large limit could exhaust memory. The clamp protects
    both ends.
    """
    client = _make_client(test_db, as_user_id=OWNER_USER_ID, active_brand_id=BRAND_ID)

    # Negative limit gets clamped up to 1 — should return at least one row.
    negative = client.get(f"/responses/?brand_id={BRAND_ID}&limit=-5").json()
    assert len(negative) == 1, "Negative limit should clamp to 1, not return zero rows"

    # Oversized limit (1,000,000) clamps down to 10000 — fixture has only 5,
    # so we just confirm the request succeeds and returns all 5.
    huge = client.get(f"/responses/?brand_id={BRAND_ID}&limit=1000000").json()
    assert len(huge) == 5
