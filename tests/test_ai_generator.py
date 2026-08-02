"""
Tests for the AIGenerator — it must (a) not crash when no analysis provider is
configured (clean ValueError → HTTP 400 in the route), and (b) route through
whatever provider is flagged use_for_analysis=True, not Gemini specifically.
"""
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models
from app.ai_generator import AIGenerator


@pytest.fixture()
def test_db():
    test_db_uri = "sqlite:///file:aigentest?mode=memory&cache=shared&uri=true"
    engine = create_engine(test_db_uri, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield TestingSessionLocal
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_no_provider_raises_clean_value_error(test_db, monkeypatch):
    """Without any analysis provider configured, instantiation must raise
    ValueError (which the brands router converts to HTTP 400) — NOT a generic
    Exception or KeyError that would surface as a 500."""
    # Strip every provider env var so the default-provider fallback yields nothing.
    for var in (
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
        "GOOGLE_API_KEY", "PERPLEXITY_API_KEY", "AZURE_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    db = test_db()
    user = models.User(
        id=1, email="t@example.com", full_name="T", is_active=True,
        is_admin=False, is_invited=True,
    )

    with pytest.raises(ValueError, match="No analysis LLM configured"):
        AIGenerator(db, user=user)


def test_uses_configured_analysis_provider(test_db, monkeypatch):
    """With an Azure provider flagged use_for_analysis=True, AIGenerator
    should route _generate() through it (no hardcoded Gemini)."""
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "key")
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                "GOOGLE_API_KEY", "PERPLEXITY_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    db = test_db()
    user = models.User(
        id=1, email="t@example.com", full_name="T", is_active=True,
        is_admin=False, is_invited=True,
    )
    db.add(user)
    db.add(models.LLMProvider(
        tenant_id=None,
        provider_key="azure_openai",
        display_name="Azure OpenAI",
        api_type="azure",
        api_endpoint="https://my.openai.azure.com/",
        api_version="2024-10-21",
        model_name="gpt-4o-prod",
        is_enabled=True,
        use_for_analysis=True,
        supports_web_search=False,
    ))
    db.commit()

    gen = AIGenerator(db, user=user)
    assert gen.provider is not None
    assert gen.provider.api_type == "azure"

    with patch.object(gen.provider, "call", return_value='[{"x": 1}]') as mock_call:
        result = gen._generate("a prompt")

    mock_call.assert_called_once()
    assert result == '[{"x": 1}]'
