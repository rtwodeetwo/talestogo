"""
Tests for GenericLLMClient — focused on the Azure code path and on the
validation guards that protect against missing Azure config.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.generic_llm_client import (
    GenericLLMClient,
    LLMAPIError,
    LLMConfigurationError,
)


class TestAzureValidation:
    def test_azure_missing_endpoint_raises(self):
        with pytest.raises(LLMConfigurationError, match="api_endpoint"):
            GenericLLMClient.call(
                api_type="azure",
                api_key="k",
                model_name="my-deployment",
                prompt="hi",
                api_version="2024-10-21",
            )

    def test_azure_missing_api_version_raises(self):
        with pytest.raises(LLMConfigurationError, match="api_version"):
            GenericLLMClient.call(
                api_type="azure",
                api_key="k",
                model_name="my-deployment",
                prompt="hi",
                api_endpoint="https://my.openai.azure.com/",
            )

    def test_unknown_api_type_raises(self):
        with pytest.raises(LLMConfigurationError, match="Unknown API type"):
            GenericLLMClient.call(
                api_type="bogus",
                api_key="k",
                model_name="m",
                prompt="hi",
            )


class TestAzureCall:
    @patch("app.services.generic_llm_client.AzureOpenAI")
    def test_azure_call_constructs_client_with_correct_args(self, mock_azure_cls):
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "azure response text"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        mock_azure_cls.return_value = mock_client

        result = GenericLLMClient.call(
            api_type="azure",
            api_key="secret",
            model_name="gpt-4o-prod",
            prompt="hello",
            api_endpoint="https://my-resource.openai.azure.com/",
            api_version="2024-10-21",
            max_tokens=200,
            temperature=0.4,
        )

        assert result == "azure response text"

        # AzureOpenAI client must be constructed with the resource URL,
        # api_version, and api_key.
        mock_azure_cls.assert_called_once()
        kwargs = mock_azure_cls.call_args.kwargs
        assert kwargs["azure_endpoint"] == "https://my-resource.openai.azure.com/"
        assert kwargs["api_version"] == "2024-10-21"
        assert kwargs["api_key"] == "secret"

        # The chat.completions call should use the deployment name as the model.
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-prod"
        assert call_kwargs["max_tokens"] == 200
        assert call_kwargs["temperature"] == 0.4

    @patch("app.services.generic_llm_client.AzureOpenAI")
    def test_azure_call_wraps_sdk_errors(self, mock_azure_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("boom")
        mock_azure_cls.return_value = mock_client

        with pytest.raises(LLMAPIError, match="Azure OpenAI API error"):
            GenericLLMClient.call(
                api_type="azure",
                api_key="k",
                model_name="m",
                prompt="hi",
                api_endpoint="https://x.openai.azure.com/",
                api_version="2024-10-21",
            )

    @patch("app.services.generic_llm_client.AzureOpenAI")
    def test_azure_call_raises_on_empty_choices(self, mock_azure_cls):
        """If Azure returns no choices (content filter / misconfig), raise cleanly
        instead of letting IndexError leak out."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(choices=[])
        mock_azure_cls.return_value = mock_client

        with pytest.raises(LLMAPIError, match="no choices"):
            GenericLLMClient.call(
                api_type="azure",
                api_key="k",
                model_name="m",
                prompt="hi",
                api_endpoint="https://x.openai.azure.com/",
                api_version="2024-10-21",
            )

    @patch("app.services.generic_llm_client.AzureOpenAI")
    def test_azure_call_handles_none_content(self, mock_azure_cls):
        """If Azure returns choices but content is None (refusal / tool_calls),
        return an empty string rather than letting None propagate."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        mock_azure_cls.return_value = mock_client

        result = GenericLLMClient.call(
            api_type="azure",
            api_key="k",
            model_name="m",
            prompt="hi",
            api_endpoint="https://x.openai.azure.com/",
            api_version="2024-10-21",
        )
        assert result == ""


class TestWebSearchUnsupportedForAzure:
    def test_call_with_web_search_rejects_azure(self):
        with pytest.raises(LLMConfigurationError, match="does not support web search"):
            GenericLLMClient.call_with_web_search(
                api_type="azure",
                api_key="k",
                model_name="m",
                prompt="hi",
                api_endpoint="https://x.openai.azure.com/",
            )


# ==================== Bing Search v7 ====================

def _mock_bing_response(snippets):
    """Build a mock httpx.Response.json() return shape matching Bing v7."""
    return {
        "webPages": {
            "value": [
                {"name": title, "url": url, "snippet": text}
                for (title, url, text) in snippets
            ]
        }
    }


class TestBingV7Search:
    @patch("app.services.generic_llm_client.httpx.Client")
    def test_bing_v7_search_parses_results(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _mock_bing_response([
            ("Result A", "https://a.example", "snippet A"),
            ("Result B", "https://b.example", "snippet B"),
        ])
        mock_resp.raise_for_status.return_value = None
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

        results = GenericLLMClient._call_bing_v7_search(
            api_key="key", query="LLM news", api_endpoint="https://api.bing.microsoft.com/",
            timeout=10.0,
        )
        assert len(results) == 2
        assert results[0] == {"title": "Result A", "url": "https://a.example", "snippet": "snippet A"}

        # Confirm the correct URL was assembled and the API-key header was set.
        get_kwargs = mock_client_cls.return_value.__enter__.return_value.get.call_args.kwargs
        get_args = mock_client_cls.return_value.__enter__.return_value.get.call_args.args
        assert get_args[0] == "https://api.bing.microsoft.com/v7.0/search"
        assert get_kwargs["headers"]["Ocp-Apim-Subscription-Key"] == "key"
        assert get_kwargs["params"]["q"] == "LLM news"

    def test_format_bing_results_handles_empty(self):
        out = GenericLLMClient._format_bing_results_as_context([])
        assert "no search results" in out.lower()

    def test_format_bing_results_numbers_and_includes_urls(self):
        out = GenericLLMClient._format_bing_results_as_context([
            {"title": "T1", "url": "https://u1", "snippet": "S1"},
            {"title": "T2", "url": "https://u2", "snippet": "S2"},
        ])
        assert "[1]" in out and "[2]" in out
        assert "https://u1" in out and "https://u2" in out


class TestBingV7GroundedSynthesis:
    @patch("app.services.generic_llm_client.GenericLLMClient._call_bing_v7_search")
    def test_synthesis_distills_query_then_calls_analysis_provider(self, mock_search):
        """The full v7 path now does: distill → search → synthesize. The analysis
        provider gets called twice: once for distillation (short prompt), once
        for synthesis (the augmented prompt with Bing results)."""
        mock_search.return_value = [
            {"title": "T1", "url": "https://u1", "snippet": "S1"},
        ]
        analysis_provider = MagicMock()
        # Distillation returns a focused query; synthesis returns the final prose.
        analysis_provider.call.side_effect = ["LLM platform changes 2026", "synthesized prose"]

        result = GenericLLMClient._call_bing_v7_grounded_synthesis(
            bing_api_key="k",
            prompt="Long instruction about LLM platform changes ..." * 20,
            bing_endpoint="https://api.bing.microsoft.com/",
            analysis_provider=analysis_provider,
            timeout=10.0,
        )
        assert result == "synthesized prose"

        # Two calls: distill + synthesize.
        assert analysis_provider.call.call_count == 2

        # The distilled query (first call's return) is what got passed to Bing.
        mock_search.assert_called_once()
        assert mock_search.call_args.args[1] == "LLM platform changes 2026"

        # The synthesis prompt (second call) embeds the Bing results.
        synthesis_kwargs = analysis_provider.call.call_args_list[1].kwargs
        assert "T1" in synthesis_kwargs["prompt"]
        assert "[1]" in synthesis_kwargs["prompt"]

    @patch("app.services.generic_llm_client.GenericLLMClient._call_bing_v7_search")
    def test_synthesis_falls_back_to_truncated_prompt_if_distillation_fails(self, mock_search):
        """If the analysis provider errors during distillation, fall back to a
        truncated word-list of the original prompt rather than hard-failing."""
        mock_search.return_value = []
        analysis_provider = MagicMock()
        analysis_provider.call.side_effect = [
            RuntimeError("LLM transient error"),  # distillation fails
            "fallback synthesis",                  # synthesis still works
        ]

        result = GenericLLMClient._call_bing_v7_grounded_synthesis(
            bing_api_key="k",
            prompt="alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",
            bing_endpoint="https://api.bing.microsoft.com/",
            analysis_provider=analysis_provider,
            timeout=10.0,
        )
        assert result == "fallback synthesis"

        # Fallback query = first 10 words of the prompt.
        mock_search.assert_called_once()
        assert mock_search.call_args.args[1] == "alpha beta gamma delta epsilon zeta eta theta iota kappa"


class TestBingV7EndpointNormalization:
    """Operators may paste the endpoint with or without /v7.0/search appended.
    The code must canonicalize without ever doubling up the path."""

    @pytest.mark.parametrize("endpoint", [
        "https://api.bing.microsoft.com",
        "https://api.bing.microsoft.com/",
        "https://api.bing.microsoft.com/v7.0",
        "https://api.bing.microsoft.com/v7.0/",
        "https://api.bing.microsoft.com/v7.0/search",
        "https://api.bing.microsoft.com/v7.0/search/",
    ])
    @patch("app.services.generic_llm_client.httpx.Client")
    def test_endpoint_normalizes_to_canonical_url(self, mock_client_cls, endpoint):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _mock_bing_response([])
        mock_resp.raise_for_status.return_value = None
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

        GenericLLMClient._call_bing_v7_search(
            api_key="k", query="q", api_endpoint=endpoint, timeout=10.0,
        )
        url = mock_client_cls.return_value.__enter__.return_value.get.call_args.args[0]
        assert url == "https://api.bing.microsoft.com/v7.0/search", (
            f"Endpoint {endpoint!r} normalized to {url!r}, expected canonical form"
        )


class TestBingV7Required:
    def test_bing_v7_requires_analysis_provider(self):
        with pytest.raises(LLMConfigurationError, match="analysis"):
            GenericLLMClient.call_with_web_search(
                api_type="bing_v7",
                api_key="k",
                model_name="bing",
                prompt="Q?",
                api_endpoint="https://api.bing.microsoft.com/",
                analysis_provider=None,
            )

    def test_bing_v7_requires_endpoint(self):
        with pytest.raises(LLMConfigurationError, match="api_endpoint"):
            GenericLLMClient.call_with_web_search(
                api_type="bing_v7",
                api_key="k",
                model_name="bing",
                prompt="Q?",
                analysis_provider=MagicMock(),
            )


# ==================== Azure AI Foundry Agents ====================

class TestAzureFoundryAgentsSDKGuard:
    def test_raises_clear_error_when_sdk_missing(self, monkeypatch):
        """If the azure-foundry extra isn't installed, the user gets a clear
        message instead of an ImportError."""
        import app.services.generic_llm_client as glc
        monkeypatch.setattr(glc, "AZURE_AI_FOUNDRY_AVAILABLE", False)
        with pytest.raises(LLMConfigurationError, match="azure-foundry"):
            GenericLLMClient.call_with_web_search(
                api_type="azure_foundry_agents",
                api_key="k",
                model_name="gpt-4o",
                prompt="Q?",
                api_endpoint="https://my-foundry.example/",
                bing_connection_name="bing-grounding",
            )

    def test_backward_compat_bing_grounded_also_raises(self, monkeypatch):
        """The legacy 'bing_grounded' alias routes to the same implementation."""
        import app.services.generic_llm_client as glc
        monkeypatch.setattr(glc, "AZURE_AI_FOUNDRY_AVAILABLE", False)
        with pytest.raises(LLMConfigurationError, match="azure-foundry"):
            GenericLLMClient.call_with_web_search(
                api_type="bing_grounded",
                api_key="k",
                model_name="gpt-4o",
                prompt="Q?",
                api_endpoint="https://my-foundry.example/",
                bing_connection_name="bing-grounding",
            )

    def test_requires_endpoint(self, monkeypatch):
        import app.services.generic_llm_client as glc
        monkeypatch.setattr(glc, "AZURE_AI_FOUNDRY_AVAILABLE", True)
        with pytest.raises(LLMConfigurationError, match="api_endpoint"):
            GenericLLMClient.call_with_web_search(
                api_type="azure_foundry_agents",
                api_key="k",
                model_name="gpt-4o",
                prompt="Q?",
                bing_connection_name="bing-grounding",
            )

    def test_requires_bing_connection_name(self, monkeypatch):
        import app.services.generic_llm_client as glc
        monkeypatch.setattr(glc, "AZURE_AI_FOUNDRY_AVAILABLE", True)
        monkeypatch.delenv("AZURE_AI_BING_CONNECTION_NAME", raising=False)
        with pytest.raises(LLMConfigurationError, match="bing_connection_name"):
            GenericLLMClient.call_with_web_search(
                api_type="azure_foundry_agents",
                api_key="k",
                model_name="gpt-4o",
                prompt="Q?",
                api_endpoint="https://my-foundry.example/",
            )

    def test_requires_deployment_name(self, monkeypatch):
        import app.services.generic_llm_client as glc
        monkeypatch.setattr(glc, "AZURE_AI_FOUNDRY_AVAILABLE", True)
        with pytest.raises(LLMConfigurationError, match="model_name"):
            GenericLLMClient.call_with_web_search(
                api_type="azure_foundry_agents",
                api_key="k",
                model_name="",
                prompt="Q?",
                api_endpoint="https://my-foundry.example/",
                bing_connection_name="bing-grounding",
            )


class TestAzureFoundryAgentsAuth:
    """Azure AI Foundry Agents uses DefaultAzureCredential + AIProjectClient."""

    def test_uses_default_azure_credential_and_project_client(self, monkeypatch):
        import app.services.generic_llm_client as glc
        monkeypatch.setattr(glc, "AZURE_AI_FOUNDRY_AVAILABLE", True)

        mock_project_cls = MagicMock()
        mock_default_cred_cls = MagicMock()
        mock_rnf = type("ResourceNotFoundError", (Exception,), {})

        monkeypatch.setattr(glc, "AIProjectClient", mock_project_cls, raising=False)
        monkeypatch.setattr(glc, "DefaultAzureCredential", mock_default_cred_cls, raising=False)
        monkeypatch.setattr(glc, "ResourceNotFoundError", mock_rnf, raising=False)
        monkeypatch.setattr(glc, "PromptAgentDefinition", MagicMock(), raising=False)
        monkeypatch.setattr(glc, "BingGroundingTool", MagicMock(), raising=False)
        monkeypatch.setattr(glc, "BingGroundingSearchToolParameters", MagicMock(), raising=False)
        monkeypatch.setattr(glc, "BingGroundingSearchConfiguration", MagicMock(), raising=False)

        project = MagicMock()
        mock_project_cls.return_value = project

        # Connection lookup
        conn = MagicMock()
        conn.id = "/subscriptions/x/connections/bing-grounding"
        project.connections.get.return_value = conn

        # Agent already exists with matching metadata
        project.agents.get.return_value = MagicMock()
        version = MagicMock()
        version.status = "active"
        version.metadata = {
            "schema_version": "1",
            "model": "gpt-4o",
            "bing_conn_hash": "anything",  # Will be overwritten below
        }
        # Compute what the code expects
        import hashlib
        bing_hash = hashlib.sha256(conn.id.encode()).hexdigest()[:16]
        version.metadata["bing_conn_hash"] = bing_hash
        project.agents.list_versions.return_value = [version]

        # OpenAI client
        openai_client = MagicMock()
        project.get_openai_client.return_value = openai_client
        response = MagicMock()
        response.status = None
        response.output_text = "grounded response"
        openai_client.responses.create.return_value = response

        result = GenericLLMClient.call_with_web_search(
            api_type="azure_foundry_agents",
            api_key="ignored",
            model_name="gpt-4o",
            prompt="Q?",
            api_endpoint="https://my-foundry.example/",
            bing_connection_name="bing-grounding",
        )

        assert result == "grounded response"
        mock_default_cred_cls.assert_called_once()
        mock_project_cls.assert_called_once_with(
            endpoint="https://my-foundry.example/",
            credential=mock_default_cred_cls.return_value,
        )
        project.connections.get.assert_called_once_with("bing-grounding")
        openai_client.responses.create.assert_called_once()
        call_kwargs = openai_client.responses.create.call_args.kwargs
        assert call_kwargs["tool_choice"] == "required"
        assert "agent_reference" in call_kwargs["extra_body"]


class TestAzureFoundryAgentsCreation:
    """When the agent doesn't exist yet, it's created via create_version."""

    def test_creates_agent_on_not_found(self, monkeypatch):
        import app.services.generic_llm_client as glc
        monkeypatch.setattr(glc, "AZURE_AI_FOUNDRY_AVAILABLE", True)

        mock_project_cls = MagicMock()
        mock_default_cred_cls = MagicMock()
        mock_rnf = type("ResourceNotFoundError", (Exception,), {})

        monkeypatch.setattr(glc, "AIProjectClient", mock_project_cls, raising=False)
        monkeypatch.setattr(glc, "DefaultAzureCredential", mock_default_cred_cls, raising=False)
        monkeypatch.setattr(glc, "ResourceNotFoundError", mock_rnf, raising=False)
        monkeypatch.setattr(glc, "PromptAgentDefinition", MagicMock(), raising=False)
        monkeypatch.setattr(glc, "BingGroundingTool", MagicMock(), raising=False)
        monkeypatch.setattr(glc, "BingGroundingSearchToolParameters", MagicMock(), raising=False)
        monkeypatch.setattr(glc, "BingGroundingSearchConfiguration", MagicMock(), raising=False)

        project = MagicMock()
        mock_project_cls.return_value = project

        conn = MagicMock()
        conn.id = "/subscriptions/x/connections/bing-grounding"
        project.connections.get.return_value = conn

        # Agent NOT found — triggers creation
        project.agents.get.side_effect = mock_rnf()

        openai_client = MagicMock()
        project.get_openai_client.return_value = openai_client
        response = MagicMock()
        response.status = None
        response.output_text = "created agent response"
        openai_client.responses.create.return_value = response

        result = GenericLLMClient.call_with_web_search(
            api_type="azure_foundry_agents",
            api_key="",
            model_name="gpt-4o",
            prompt="Q?",
            api_endpoint="https://my-foundry.example/",
            bing_connection_name="bing-grounding",
        )

        assert result == "created agent response"
        project.agents.create_version.assert_called_once()
        create_kwargs = project.agents.create_version.call_args.kwargs
        assert create_kwargs["agent_name"].startswith("tales-bing-")
        assert create_kwargs["metadata"]["provider"] == "tales"


class TestAzureFoundryAgentsOutputExtraction:
    """If output_text is empty, falls back to iterating output items."""

    def test_fallback_to_output_items(self, monkeypatch):
        import app.services.generic_llm_client as glc
        monkeypatch.setattr(glc, "AZURE_AI_FOUNDRY_AVAILABLE", True)

        mock_project_cls = MagicMock()
        mock_rnf = type("ResourceNotFoundError", (Exception,), {})

        monkeypatch.setattr(glc, "AIProjectClient", mock_project_cls, raising=False)
        monkeypatch.setattr(glc, "DefaultAzureCredential", MagicMock(), raising=False)
        monkeypatch.setattr(glc, "ResourceNotFoundError", mock_rnf, raising=False)
        monkeypatch.setattr(glc, "PromptAgentDefinition", MagicMock(), raising=False)
        monkeypatch.setattr(glc, "BingGroundingTool", MagicMock(), raising=False)
        monkeypatch.setattr(glc, "BingGroundingSearchToolParameters", MagicMock(), raising=False)
        monkeypatch.setattr(glc, "BingGroundingSearchConfiguration", MagicMock(), raising=False)

        project = MagicMock()
        mock_project_cls.return_value = project

        conn = MagicMock()
        conn.id = "/subscriptions/x/connections/bing-grounding"
        project.connections.get.return_value = conn
        project.agents.get.side_effect = mock_rnf()

        openai_client = MagicMock()
        project.get_openai_client.return_value = openai_client

        # response.output_text is empty; must fallback to output items
        response = MagicMock()
        response.status = None
        response.output_text = ""
        block1 = MagicMock()
        block1.text = "Part one."
        block2 = MagicMock()
        block2.text = "Part two."
        item = MagicMock()
        item.content = [block1, block2]
        response.output = [item]
        openai_client.responses.create.return_value = response

        result = GenericLLMClient.call_with_web_search(
            api_type="azure_foundry_agents",
            api_key="",
            model_name="gpt-4o",
            prompt="Q?",
            api_endpoint="https://my-foundry.example/",
            bing_connection_name="bing-grounding",
        )
        assert "Part one." in result
        assert "Part two." in result


# ==================== test_connection() ====================


class TestTestConnection:
    @patch("app.services.generic_llm_client.GenericLLMClient._call_bing_v7_search")
    def test_bing_v7_test_connection_calls_search(self, mock_search):
        mock_search.return_value = [
            {"title": "Result", "url": "https://example.com", "snippet": "A test snippet"},
        ]
        success, message, preview = GenericLLMClient.test_connection(
            api_type="bing_v7",
            api_key="test-key",
            model_name="bing-v7-label",
            api_endpoint="https://api.bing.microsoft.com/",
        )
        assert success is True
        assert "Bing Search v7" in message
        assert "A test snippet" in preview
        mock_search.assert_called_once_with(
            api_key="test-key",
            query="test",
            api_endpoint="https://api.bing.microsoft.com/",
            timeout=30.0,
            count=1,
        )

    @patch("app.services.generic_llm_client.GenericLLMClient._call_bing_v7_search")
    def test_bing_v7_test_connection_api_error(self, mock_search):
        mock_search.side_effect = LLMAPIError("Bing returned 403")
        success, message, preview = GenericLLMClient.test_connection(
            api_type="bing_v7",
            api_key="bad-key",
            model_name="bing",
            api_endpoint="https://api.bing.microsoft.com/",
        )
        assert success is False
        assert "API error" in message
        assert "403" in message
        assert preview is None

    def test_bing_v7_test_connection_missing_endpoint(self):
        success, message, preview = GenericLLMClient.test_connection(
            api_type="bing_v7",
            api_key="key",
            model_name="bing",
        )
        assert success is False
        assert "Configuration error" in message
        assert "api_endpoint" in message

    @patch("app.services.generic_llm_client.GenericLLMClient._call_azure_foundry_agents")
    def test_azure_foundry_agents_test_connection_success(self, mock_foundry):
        mock_foundry.return_value = "Hello! I'm an Azure AI agent."
        success, message, preview = GenericLLMClient.test_connection(
            api_type="azure_foundry_agents",
            api_key="",
            model_name="gpt-4o",
            api_endpoint="https://my-foundry.example/",
            bing_connection_name="bing-grounding",
        )
        assert success is True
        assert "Azure AI Foundry" in message
        assert "Hello!" in preview
        mock_foundry.assert_called_once_with(
            api_key="",
            deployment_name="gpt-4o",
            prompt="Hello, please respond with a brief greeting.",
            api_endpoint="https://my-foundry.example/",
            api_version=None,
            timeout=60.0,
            bing_connection_name="bing-grounding",
        )

    @patch("app.services.generic_llm_client.GenericLLMClient._call_azure_foundry_agents")
    def test_bing_grounded_alias_routes_to_foundry_agents(self, mock_foundry):
        """Legacy 'bing_grounded' api_type routes through test_connection too."""
        mock_foundry.return_value = "Hello!"
        success, message, _ = GenericLLMClient.test_connection(
            api_type="bing_grounded",
            api_key="",
            model_name="gpt-4o",
            api_endpoint="https://my-foundry.example/",
            bing_connection_name="bing-grounding",
        )
        assert success is True
        assert "Azure AI Foundry" in message

    def test_azure_foundry_agents_test_connection_sdk_missing(self, monkeypatch):
        import app.services.generic_llm_client as glc
        monkeypatch.setattr(glc, "AZURE_AI_FOUNDRY_AVAILABLE", False)
        success, message, preview = GenericLLMClient.test_connection(
            api_type="azure_foundry_agents",
            api_key="",
            model_name="gpt-4o",
            api_endpoint="https://my-foundry.example/",
            bing_connection_name="bing-grounding",
        )
        assert success is False
        assert "Configuration error" in message
        assert "azure-foundry" in message

    @patch("app.services.generic_llm_client.GenericLLMClient.call")
    def test_standard_type_still_routes_through_call(self, mock_call):
        mock_call.return_value = "Hi there!"
        success, message, preview = GenericLLMClient.test_connection(
            api_type="openai",
            api_key="sk-test",
            model_name="gpt-4",
        )
        assert success is True
        assert message == "Connection successful"
        assert "Hi there!" in preview
        mock_call.assert_called_once()
