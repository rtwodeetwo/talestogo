"""
Tests for the LLMProviderManager and ProviderConfig — focused on the Azure
OpenAI api_type plumbing added when the codebase went provider-agnostic.
"""
import os
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models
from app.services.llm_provider_manager import (
    API_TYPE_TO_ENV_VAR,
    LLMProviderManager,
    ProviderConfig,
)
from app.services.generic_llm_client import LLMConfigurationError


@pytest.fixture()
def test_db():
    test_db_uri = "sqlite:///file:llmpmtest?mode=memory&cache=shared"
    engine = create_engine(test_db_uri, connect_args={"check_same_thread": False, "uri": True})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield TestingSessionLocal
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_api_type_to_env_var_includes_azure():
    """Azure must have a default env var so admin-UI defaults work."""
    assert API_TYPE_TO_ENV_VAR["azure"] == "AZURE_OPENAI_API_KEY"


def test_provider_config_api_version_default_is_none():
    """api_version is optional on ProviderConfig — only Azure needs it."""
    cfg = ProviderConfig(
        provider_key="gpt",
        display_name="GPT-4o",
        api_type="openai",
        model_name="gpt-4o",
    )
    assert cfg.api_version is None


def test_provider_config_azure_get_api_key_uses_env_var(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "secret-from-env")
    cfg = ProviderConfig(
        provider_key="azure_openai",
        display_name="Azure OpenAI",
        api_type="azure",
        model_name="gpt-4o-deployment",
        api_endpoint="https://my-resource.openai.azure.com/",
        api_version="2024-10-21",
    )
    assert cfg.has_api_key() is True


def test_provider_config_azure_threads_api_version_into_call(monkeypatch):
    """ProviderConfig.call() must forward api_version into GenericLLMClient.call."""
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "secret-from-env")
    cfg = ProviderConfig(
        provider_key="azure_openai",
        display_name="Azure OpenAI",
        api_type="azure",
        model_name="gpt-4o-deployment",
        api_endpoint="https://my-resource.openai.azure.com/",
        api_version="2024-10-21",
    )

    with patch("app.services.llm_provider_manager.GenericLLMClient.call") as mock_call:
        mock_call.return_value = "ok"
        cfg.call("hello", max_tokens=10, temperature=0.5)

    mock_call.assert_called_once()
    kwargs = mock_call.call_args.kwargs
    assert kwargs["api_type"] == "azure"
    assert kwargs["api_version"] == "2024-10-21"
    assert kwargs["api_endpoint"] == "https://my-resource.openai.azure.com/"
    assert kwargs["model_name"] == "gpt-4o-deployment"


def test_azure_db_provider_loads_api_version(test_db, monkeypatch):
    """A DB-stored Azure provider's api_version threads into ProviderConfig."""
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "key")
    db = test_db()
    db.add(models.LLMProvider(
        tenant_id=None,
        provider_key="azure_openai",
        display_name="Azure OpenAI",
        api_type="azure",
        api_endpoint="https://my-resource.openai.azure.com/",
        api_version="2024-10-21",
        model_name="gpt-4o-prod",
        is_enabled=True,
        use_for_analysis=True,
        supports_web_search=False,
    ))
    db.commit()

    mgr = LLMProviderManager(db)
    analysis = mgr.get_analysis_provider()

    assert analysis is not None
    assert analysis.api_type == "azure"
    assert analysis.api_version == "2024-10-21"
    assert analysis.api_endpoint == "https://my-resource.openai.azure.com/"


def test_get_analysis_provider_returns_none_when_nothing_configured(test_db, monkeypatch):
    """With no providers and no env vars, the analysis provider is None."""
    for var in API_TYPE_TO_ENV_VAR.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    db = test_db()
    mgr = LLMProviderManager(db)
    assert mgr.get_analysis_provider() is None


# ==================== Bing web-search providers ====================

def test_api_type_to_env_var_includes_bing():
    """Both Bing api_types must have default env var bindings."""
    assert API_TYPE_TO_ENV_VAR["bing_v7"] == "BING_SEARCH_V7_API_KEY"
    assert API_TYPE_TO_ENV_VAR["azure_foundry_agents"] == "AZURE_AI_PROJECT_ENDPOINT"
    assert API_TYPE_TO_ENV_VAR["bing_grounded"] == "AZURE_AI_PROJECT_ENDPOINT"  # backward compat


def test_bing_v7_db_provider_threads_analysis_provider_into_call(test_db, monkeypatch):
    """A bing_v7 ProviderConfig.call_with_web_search must pass analysis_provider
    through to GenericLLMClient. Mocking GenericLLMClient.call_with_web_search to
    verify the parameter is threaded correctly."""
    monkeypatch.setenv("BING_SEARCH_V7_API_KEY", "bing-key")
    db = test_db()
    db.add(models.LLMProvider(
        tenant_id=None,
        provider_key="bing_v7",
        display_name="Bing v7",
        api_type="bing_v7",
        api_endpoint="https://api.bing.microsoft.com/",
        model_name="bing",
        is_enabled=True,
        supports_web_search=True,
    ))
    db.commit()

    mgr = LLMProviderManager(db)
    web_providers = mgr.get_web_search_providers()
    assert any(p.api_type == "bing_v7" for p in web_providers)

    bing = next(p for p in web_providers if p.api_type == "bing_v7")
    fake_analysis = object()  # opaque sentinel — just needs to thread through

    with patch("app.services.llm_provider_manager.GenericLLMClient.call_with_web_search") as mock_ws:
        mock_ws.return_value = "ok"
        bing.call_with_web_search(prompt="Q?", analysis_provider=fake_analysis)

    mock_ws.assert_called_once()
    kwargs = mock_ws.call_args.kwargs
    assert kwargs["api_type"] == "bing_v7"
    assert kwargs["analysis_provider"] is fake_analysis
    assert kwargs["api_endpoint"] == "https://api.bing.microsoft.com/"


def test_azure_foundry_agents_call_with_web_search_without_api_key(monkeypatch):
    """azure_foundry_agents uses DefaultAzureCredential, not an API key — must not
    raise LLMConfigurationError when no API key env var is set."""
    monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)
    cfg = ProviderConfig(
        provider_key="azure_foundry",
        display_name="Foundry Bing",
        api_type="azure_foundry_agents",
        model_name="gpt-4o",
        api_endpoint="https://x.example/",
        bing_connection_name="bing-grounding",
        supports_web_search=True,
    )

    with patch("app.services.llm_provider_manager.GenericLLMClient.call_with_web_search") as mock_ws:
        mock_ws.return_value = "grounded response"
        result = cfg.call_with_web_search(prompt="Q?")

    assert result == "grounded response"
    mock_ws.assert_called_once()
    assert mock_ws.call_args.kwargs["api_key"] == ""
    assert mock_ws.call_args.kwargs["bing_connection_name"] == "bing-grounding"


def test_bing_grounded_backward_compat_also_skips_key_check(monkeypatch):
    """Legacy bing_grounded api_type also bypasses the API key check."""
    monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)
    cfg = ProviderConfig(
        provider_key="bing_grounded",
        display_name="Foundry Bing",
        api_type="bing_grounded",
        model_name="gpt-4o",
        api_endpoint="https://x.example/",
        bing_connection_name="bing-grounding",
        supports_web_search=True,
    )

    with patch("app.services.llm_provider_manager.GenericLLMClient.call_with_web_search") as mock_ws:
        mock_ws.return_value = "grounded response"
        result = cfg.call_with_web_search(prompt="Q?")

    assert result == "grounded response"


def test_get_web_search_providers_includes_bing(test_db, monkeypatch):
    """Both Bing types must be discoverable via get_web_search_providers."""
    monkeypatch.setenv("BING_SEARCH_V7_API_KEY", "x")
    db = test_db()
    db.add(models.LLMProvider(
        tenant_id=None, provider_key="bing_v7", display_name="Bing v7",
        api_type="bing_v7", api_endpoint="https://api.bing.microsoft.com/",
        model_name="bing", is_enabled=True, supports_web_search=True,
    ))
    db.add(models.LLMProvider(
        tenant_id=None, provider_key="azure_foundry", display_name="Foundry Bing",
        api_type="azure_foundry_agents", api_endpoint="https://x.example/",
        model_name="gpt-4o", bing_connection_name="bing-grounding",
        is_enabled=True, supports_web_search=True,
    ))
    db.commit()

    types = {p.api_type for p in LLMProviderManager(db).get_web_search_providers()}
    assert {"bing_v7", "azure_foundry_agents"}.issubset(types)


def test_azure_foundry_agents_has_api_key_checks_endpoint():
    """azure_foundry_agents uses endpoint presence (not env var) for has_api_key."""
    cfg = ProviderConfig(
        provider_key="foundry",
        display_name="Foundry",
        api_type="azure_foundry_agents",
        model_name="gpt-4o",
        api_endpoint="https://x.example/",
    )
    assert cfg.has_api_key() is True

    cfg_no_endpoint = ProviderConfig(
        provider_key="foundry2",
        display_name="Foundry2",
        api_type="azure_foundry_agents",
        model_name="gpt-4o",
    )
    assert cfg_no_endpoint.has_api_key() is False
