"""
The three tool-use dialects, checked without a network.

These adapters are the one part of investigations that cannot be exercised
against the real thing in CI, so what they translate is pinned here instead: the
tool definitions, the shape of an assistant turn going back into the history,
how a tool result is attached, and how each provider's stop signal maps onto the
loop's three outcomes.

The temperature assertions are not decoration. Opus 4.7/4.8 and Sonnet 5 reject
temperature with a 400, and GPT-5 rejects it and wants max_completion_tokens; an
adapter that sends it does not degrade, it fails outright.
"""
import json
import types as pytypes

import pytest

from app.services.investigation import agent_client as ac


class FakeProvider:
    def __init__(self, api_type, model_name, api_endpoint=None, api_version=None):
        self.api_type = api_type
        self.model_name = model_name
        self.provider_key = api_type
        self.api_endpoint = api_endpoint
        self.api_version = api_version
        self.sort_order = 0

    def _get_api_key(self):
        return "test-key-not-used"


TOOLS = [
    ac.ToolSpec("compare_scopes", "Every metric for both windows.",
                {"type": "object", "properties": {}}),
    ac.ToolSpec("response_details", "What the platforms said.",
                {"type": "object",
                 "properties": {
                     "side": {"type": "string", "enum": ["current", "previous"]},
                     "query_id": {"type": "string"},
                 },
                 "required": ["side", "query_id"]}),
]


def _call(name="response_details"):
    return ac.ToolCall(id="call-1", name=name,
                       arguments={"side": "current", "query_id": "Q1"})


# ------------------------------------------------------------- selection

class TestProviderSelection:
    def test_prefers_anthropic_then_openai_then_google(self):
        providers = [FakeProvider("google", "gemini-3.5-flash"),
                     FakeProvider("openai", "gpt-5.5"),
                     FakeProvider("anthropic", "claude-opus-4-8")]
        assert ac.select_agent_provider(providers).api_type == "anthropic"
        assert ac.select_agent_provider(providers[:2]).api_type == "openai"
        assert ac.select_agent_provider(providers[:1]).api_type == "google"

    def test_search_models_are_rejected(self):
        """Perplexity's sonar models speak OpenAI but cannot call tools."""
        assert ac.select_agent_provider(
            [FakeProvider("openai_compatible", "sonar-pro")]) is None

    def test_an_openai_compatible_proxy_is_usable(self):
        """An internal LiteLLM-style gateway is openai_compatible and does
        support tools, so it must not be excluded with Perplexity."""
        provider = FakeProvider("openai_compatible", "claude-opus-4-8",
                                api_endpoint="https://proxy.internal/v1")
        assert ac.select_agent_provider([provider]) is provider

    def test_nothing_configured_returns_none(self):
        assert ac.select_agent_provider([]) is None


# ------------------------------------------------------------- Anthropic

class FakeAnthropicMessage:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = pytypes.SimpleNamespace(input_tokens=11, output_tokens=7)


def _block(**kwargs):
    return pytypes.SimpleNamespace(**kwargs)


@pytest.fixture
def anthropic_conversation(monkeypatch):
    conversation = ac.build_conversation(
        FakeProvider("anthropic", "claude-opus-4-8"), "SYSTEM", TOOLS, 12288)
    sent = []

    def create(**kwargs):
        sent.append(kwargs)
        return conversation._next

    conversation._client = pytypes.SimpleNamespace(
        messages=pytypes.SimpleNamespace(create=create))
    conversation.sent = sent
    return conversation


class TestAnthropicAdapter:
    def test_tool_definitions_keep_the_json_schema(self, anthropic_conversation):
        definitions = anthropic_conversation._tool_defs
        assert definitions[1]["name"] == "response_details"
        assert definitions[1]["input_schema"]["required"] == ["side", "query_id"]

    def test_no_temperature_is_ever_sent(self, anthropic_conversation):
        anthropic_conversation._next = FakeAnthropicMessage(
            [_block(type="text", text="done")], "end_turn")
        anthropic_conversation.start("go")
        anthropic_conversation.run()
        assert "temperature" not in anthropic_conversation.sent[0]
        assert anthropic_conversation.sent[0]["max_tokens"] == 12288
        assert anthropic_conversation.sent[0]["system"] == "SYSTEM"

    def test_tool_use_turn_is_normalised(self, anthropic_conversation):
        anthropic_conversation._next = FakeAnthropicMessage(
            [_block(type="text", text="looking"),
             _block(type="tool_use", id="call-1", name="compare_scopes", input={})],
            "tool_use")
        anthropic_conversation.start("go")
        turn = anthropic_conversation.run()

        assert turn.stop_reason == "tool_use"
        assert turn.text == "looking"
        assert [c.name for c in turn.tool_calls] == ["compare_scopes"]
        assert turn.input_tokens == 11 and turn.output_tokens == 7

    def test_a_failed_tool_result_carries_is_error(self, anthropic_conversation):
        anthropic_conversation.start("go")
        anthropic_conversation.submit_tool_results(
            [ac.ToolResult(_call(), "it broke", is_error=True)])
        block = anthropic_conversation._messages[-1]["content"][0]
        assert block["type"] == "tool_result"
        assert block["is_error"] is True
        assert block["tool_use_id"] == "call-1"

    def test_max_tokens_stop_is_reported(self, anthropic_conversation):
        anthropic_conversation._next = FakeAnthropicMessage(
            [_block(type="text", text="half a summ")], "max_tokens")
        anthropic_conversation.start("go")
        assert anthropic_conversation.run().stop_reason == "max_tokens"


# ---------------------------------------------------------------- OpenAI

class FakeOpenAIMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_none=False):
        return {"role": "assistant", "content": self.content}


def _openai_response(message, finish_reason):
    return pytypes.SimpleNamespace(
        choices=[pytypes.SimpleNamespace(message=message,
                                         finish_reason=finish_reason)],
        usage=pytypes.SimpleNamespace(prompt_tokens=3, completion_tokens=4))


def _openai_conversation(model_name):
    conversation = ac.build_conversation(
        FakeProvider("openai", model_name), "SYSTEM", TOOLS, 12288)
    sent = []

    def create(**kwargs):
        sent.append(kwargs)
        return conversation._next

    conversation._client = pytypes.SimpleNamespace(
        chat=pytypes.SimpleNamespace(
            completions=pytypes.SimpleNamespace(create=create)))
    conversation.sent = sent
    return conversation


class TestOpenAIAdapter:
    def test_system_prompt_is_the_first_message(self):
        conversation = _openai_conversation("gpt-4o")
        assert conversation._messages[0] == {"role": "system", "content": "SYSTEM"}

    def test_gpt5_gets_max_completion_tokens_and_no_temperature(self):
        conversation = _openai_conversation("gpt-5.5")
        conversation._next = _openai_response(FakeOpenAIMessage("done"), "stop")
        conversation.start("go")
        conversation.run()
        sent = conversation.sent[0]
        assert sent["max_completion_tokens"] == 12288
        assert "max_tokens" not in sent
        assert "temperature" not in sent

    def test_older_models_get_max_tokens(self):
        conversation = _openai_conversation("gpt-4o")
        conversation._next = _openai_response(FakeOpenAIMessage("done"), "stop")
        conversation.start("go")
        conversation.run()
        assert conversation.sent[0]["max_tokens"] == 12288

    def test_tool_calls_are_parsed(self):
        conversation = _openai_conversation("gpt-4o")
        call = pytypes.SimpleNamespace(
            id="call-9",
            function=pytypes.SimpleNamespace(
                name="response_details",
                arguments=json.dumps({"side": "previous", "query_id": "Q2"})))
        conversation._next = _openai_response(
            FakeOpenAIMessage(None, [call]), "tool_calls")
        conversation.start("go")
        turn = conversation.run()

        assert turn.stop_reason == "tool_use"
        assert turn.tool_calls[0].arguments == {"side": "previous", "query_id": "Q2"}

    def test_malformed_arguments_do_not_crash_the_loop(self):
        conversation = _openai_conversation("gpt-4o")
        call = pytypes.SimpleNamespace(
            id="call-9",
            function=pytypes.SimpleNamespace(name="compare_scopes",
                                             arguments="{not json"))
        conversation._next = _openai_response(
            FakeOpenAIMessage(None, [call]), "tool_calls")
        conversation.start("go")
        assert conversation.run().tool_calls[0].arguments == {}

    def test_a_failed_tool_result_says_so_in_words(self):
        """Chat completions has no is_error flag, so the payload must carry it."""
        conversation = _openai_conversation("gpt-4o")
        conversation.submit_tool_results(
            [ac.ToolResult(_call(), "search unreachable", is_error=True)])
        message = conversation._messages[-1]
        assert message["role"] == "tool"
        assert message["tool_call_id"] == "call-1"
        assert "did not run" in message["content"]

    def test_length_finish_reason_maps_to_max_tokens(self):
        conversation = _openai_conversation("gpt-4o")
        conversation._next = _openai_response(FakeOpenAIMessage("cut off"), "length")
        conversation.start("go")
        assert conversation.run().stop_reason == "max_tokens"


# ---------------------------------------------------------------- Google

def _google_conversation():
    return ac.build_conversation(
        FakeProvider("google", "gemini-3.5-flash"), "SYSTEM", TOOLS, 12288)


class TestGoogleAdapter:
    def test_a_no_argument_tool_is_declared_without_parameters(self):
        """Gemini rejects an object schema with an empty properties map."""
        conversation = _google_conversation()
        declarations = conversation._config.tools[0].function_declarations
        by_name = {d.name: d for d in declarations}
        assert by_name["compare_scopes"].parameters_json_schema in (None, {})
        assert by_name["response_details"].parameters_json_schema["required"] == [
            "side", "query_id"]

    def test_automatic_function_calling_is_disabled(self):
        """Letting the SDK run tools itself would bypass the audit trail."""
        conversation = _google_conversation()
        assert conversation._config.automatic_function_calling.disable is True

    def test_a_failed_tool_result_goes_under_an_error_key(self):
        conversation = _google_conversation()
        conversation.submit_tool_results(
            [ac.ToolResult(_call(), "boom", is_error=True)])
        part = conversation._contents[-1].parts[0]
        assert part.function_response.name == "response_details"
        assert part.function_response.response == {"error": "boom"}

    def test_a_successful_tool_result_goes_under_a_result_key(self):
        conversation = _google_conversation()
        conversation.submit_tool_results([ac.ToolResult(_call(), "{}")])
        assert conversation._contents[-1].parts[0].function_response.response == {
            "result": "{}"}

    def test_function_calls_are_normalised(self, monkeypatch):
        conversation = _google_conversation()
        from google.genai import types as gt

        candidate = pytypes.SimpleNamespace(
            content=gt.Content(role="model", parts=[
                gt.Part(function_call=gt.FunctionCall(
                    name="compare_scopes", args={}))]),
            finish_reason="STOP")
        response = pytypes.SimpleNamespace(
            candidates=[candidate],
            usage_metadata=pytypes.SimpleNamespace(prompt_token_count=5,
                                                   candidates_token_count=6))
        conversation._client = pytypes.SimpleNamespace(
            models=pytypes.SimpleNamespace(
                generate_content=lambda **kwargs: response))

        conversation.start("go")
        turn = conversation.run()
        assert turn.stop_reason == "tool_use"
        assert turn.tool_calls[0].name == "compare_scopes"
        # A call id is synthesised when Gemini omits one; the loop only needs it
        # to pair a result with its call.
        assert turn.tool_calls[0].id

    def test_max_tokens_finish_reason_is_detected(self):
        conversation = _google_conversation()
        from google.genai import types as gt

        candidate = pytypes.SimpleNamespace(
            content=gt.Content(role="model", parts=[gt.Part(text="cut off")]),
            finish_reason="MAX_TOKENS")
        response = pytypes.SimpleNamespace(
            candidates=[candidate],
            usage_metadata=pytypes.SimpleNamespace(prompt_token_count=5,
                                                   candidates_token_count=6))
        conversation._client = pytypes.SimpleNamespace(
            models=pytypes.SimpleNamespace(
                generate_content=lambda **kwargs: response))

        conversation.start("go")
        turn = conversation.run()
        assert turn.stop_reason == "max_tokens"
        assert turn.text == "cut off"
