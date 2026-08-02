"""
Tool-use conversations, one thin adapter per provider dialect.

The investigation agent needs something the rest of Tales has never needed: a
multi-turn conversation in which the model calls tools and reads their results.
GenericLLMClient is single-shot by design, so rather than distort it this module
adds the one extra shape, normalised so service.py never has to know which
provider it is talking to.

Three dialects are covered because a lab may realistically have only one key:

- Anthropic messages API (`anthropic`)
- OpenAI chat completions (`openai`, `azure`, `openai_compatible`)
- Google GenAI function calling (`google`)

Providers and keys still come from LLMProviderManager. Nothing here reads an
environment variable or hardcodes a model name; a deployment that changes its
configured model changes what investigations run on, with no code edit.

The normalised turn carries `stop_reason`, and callers must act on
`"max_tokens"`: a synthesis cut off mid-sentence is not a completed
investigation, and storing it as one is the failure mode this whole feature
exists to avoid.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..generic_llm_client import (
    ANTHROPIC_AVAILABLE,
    GOOGLE_AVAILABLE,
    OPENAI_AVAILABLE,
    LLMAPIError,
    LLMConfigurationError,
    _openai_rejects_sampling,
)

logger = logging.getLogger(__name__)

#: Which api_types can hold a tool-use conversation at all, best first.
#:
#: Perplexity's sonar models are excluded below by model name rather than by
#: api_type: they are openai_compatible but do not do function calling, while an
#: internal LiteLLM-style proxy is also openai_compatible and does.
AGENT_API_TYPE_PREFERENCE = ("anthropic", "openai", "azure", "google",
                             "openai_compatible")

#: Model-name markers for search models that speak an OpenAI-shaped API but
#: cannot call tools.
_NO_TOOL_CALLING_MARKERS = ("sonar",)


class AgentUnavailable(LLMConfigurationError):
    """No configured provider can run a tool-use conversation."""


def provider_can_run_agent(provider) -> bool:
    """True if this provider is usable as the investigation's reasoning model."""
    if provider.api_type not in AGENT_API_TYPE_PREFERENCE:
        return False
    model = (provider.model_name or "").lower()
    return not any(marker in model for marker in _NO_TOOL_CALLING_MARKERS)


def select_agent_provider(providers) -> Optional[Any]:
    """Pick the reasoning model from the configured providers.

    Preference is by api_type, not by a hardcoded model name, so an admin who
    upgrades their Claude or GPT model in Admin → LLM Providers upgrades
    investigations at the same time.
    """
    usable = [p for p in providers if provider_can_run_agent(p)]
    if not usable:
        return None
    order = {api_type: i for i, api_type in enumerate(AGENT_API_TYPE_PREFERENCE)}
    usable.sort(key=lambda p: (order.get(p.api_type, 99), p.sort_order or 0))
    return usable[0]


# ------------------------------------------------------------------ shapes

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    #: JSON Schema for the arguments. Deliberately plain: no $ref, no anyOf, no
    #: nested objects, because the three dialects agree on that subset and
    #: nothing here needs more.
    input_schema: Dict[str, Any]

    @property
    def has_arguments(self) -> bool:
        return bool(self.input_schema.get("properties"))


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call: ToolCall
    payload: str
    is_error: bool = False


@dataclass
class AgentTurn:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    #: "tool_use" | "end_turn" | "max_tokens"
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0


class AgentConversation:
    """A running tool-use conversation with one provider."""

    def __init__(self, provider, system: str, tools: List[ToolSpec],
                 max_tokens: int, timeout: float = 240.0):
        self.provider = provider
        self.system = system
        self.tools = tools
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._by_name = {tool.name: tool for tool in tools}

    # -- subclass contract
    def start(self, user_text: str) -> None:
        raise NotImplementedError

    def submit_tool_results(self, results: List[ToolResult]) -> None:
        raise NotImplementedError

    def run(self) -> AgentTurn:
        raise NotImplementedError


def build_conversation(provider, system: str, tools: List[ToolSpec],
                       max_tokens: int, timeout: float = 240.0
                       ) -> AgentConversation:
    """The one place an api_type becomes a conversation object."""
    if not provider_can_run_agent(provider):
        raise AgentUnavailable(
            f"Provider '{provider.provider_key}' ({provider.api_type}, "
            f"{provider.model_name}) cannot run a tool-use conversation.")

    if provider.api_type == "anthropic":
        return _AnthropicConversation(provider, system, tools, max_tokens, timeout)
    if provider.api_type == "google":
        return _GoogleConversation(provider, system, tools, max_tokens, timeout)
    return _OpenAIConversation(provider, system, tools, max_tokens, timeout)


# --------------------------------------------------------------- Anthropic

class _AnthropicConversation(AgentConversation):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not ANTHROPIC_AVAILABLE:
            raise LLMConfigurationError(
                "Anthropic SDK not installed. Run: pip install anthropic")
        import anthropic

        self._client = anthropic.Anthropic(
            api_key=self.provider._get_api_key(), timeout=self.timeout)
        self._messages: List[Dict[str, Any]] = []
        self._tool_defs = [
            {"name": tool.name, "description": tool.description,
             "input_schema": tool.input_schema}
            for tool in self.tools
        ]

    def start(self, user_text: str) -> None:
        self._messages.append({"role": "user", "content": user_text})

    def submit_tool_results(self, results: List[ToolResult]) -> None:
        self._messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": result.call.id,
                    "content": result.payload,
                    # Without this the model reads a failure payload as an
                    # ordinary answer, and a dead search becomes "no news found".
                    "is_error": result.is_error,
                }
                for result in results
            ],
        })

    def run(self) -> AgentTurn:
        try:
            # No temperature: Opus 4.7/4.8 and Sonnet 5 reject it with a 400.
            message = self._client.messages.create(
                model=self.provider.model_name,
                max_tokens=self.max_tokens,
                system=self.system,
                tools=self._tool_defs,
                messages=self._messages,
            )
        except Exception as exc:
            raise LLMAPIError(f"Anthropic API error: {exc}") from exc

        self._messages.append({"role": "assistant", "content": message.content})

        text = "".join(
            block.text for block in message.content
            if getattr(block, "type", None) == "text"
        )
        calls = [
            ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}))
            for block in message.content
            if getattr(block, "type", None) == "tool_use"
        ]

        stop = message.stop_reason
        return AgentTurn(
            text=text,
            tool_calls=calls,
            stop_reason=("tool_use" if stop == "tool_use"
                         else "max_tokens" if stop == "max_tokens" else "end_turn"),
            input_tokens=getattr(message.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(message.usage, "output_tokens", 0) or 0,
        )


# ------------------------------------------------------------------ OpenAI

class _OpenAIConversation(AgentConversation):
    """Chat completions with tools: openai, azure, and OpenAI-compatible."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not OPENAI_AVAILABLE:
            raise LLMConfigurationError(
                "OpenAI SDK not installed. Run: pip install openai")
        from openai import AzureOpenAI, OpenAI

        api_key = self.provider._get_api_key()
        if self.provider.api_type == "azure":
            if not self.provider.api_endpoint or not self.provider.api_version:
                raise LLMConfigurationError(
                    "Azure OpenAI requires both api_endpoint and api_version.")
            self._client = AzureOpenAI(
                api_key=api_key, azure_endpoint=self.provider.api_endpoint,
                api_version=self.provider.api_version, timeout=self.timeout)
        elif self.provider.api_endpoint:
            self._client = OpenAI(api_key=api_key,
                                  base_url=self.provider.api_endpoint,
                                  timeout=self.timeout)
        else:
            self._client = OpenAI(api_key=api_key, timeout=self.timeout)

        self._messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system}]
        self._tool_defs = [
            {"type": "function",
             "function": {"name": tool.name, "description": tool.description,
                          "parameters": tool.input_schema}}
            for tool in self.tools
        ]

    def start(self, user_text: str) -> None:
        self._messages.append({"role": "user", "content": user_text})

    def submit_tool_results(self, results: List[ToolResult]) -> None:
        for result in results:
            # The chat completions tool message has no is_error flag, so the
            # failure has to be stated in the payload itself. Saying it in words
            # is what stops the model reading a dead tool as an empty answer.
            payload = (f"TOOL ERROR - this call did not run: {result.payload}"
                       if result.is_error else result.payload)
            self._messages.append({
                "role": "tool",
                "tool_call_id": result.call.id,
                "content": payload,
            })

    def run(self) -> AgentTurn:
        kwargs: Dict[str, Any] = {
            "model": self.provider.model_name,
            "messages": self._messages,
            "tools": self._tool_defs,
        }
        # GPT-5 and the o-series need max_completion_tokens and reject sampling
        # parameters; neither path sends temperature at all.
        if _openai_rejects_sampling(self.provider.model_name):
            kwargs["max_completion_tokens"] = self.max_tokens
        else:
            kwargs["max_tokens"] = self.max_tokens

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise LLMAPIError(f"OpenAI API error: {exc}") from exc

        choice = response.choices[0]
        message = choice.message
        self._messages.append(message.model_dump(exclude_none=True))

        calls = []
        for call in (message.tool_calls or []):
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except (TypeError, ValueError):
                # Malformed arguments are the model's mistake, not a crash. The
                # tool runs with nothing and reports what went wrong.
                arguments = {}
            calls.append(ToolCall(id=call.id, name=call.function.name,
                                  arguments=arguments))

        finish = choice.finish_reason
        usage = response.usage
        return AgentTurn(
            text=message.content or "",
            tool_calls=calls,
            stop_reason=("tool_use" if finish == "tool_calls"
                         else "max_tokens" if finish == "length" else "end_turn"),
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )


# ------------------------------------------------------------------ Google

class _GoogleConversation(AgentConversation):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not GOOGLE_AVAILABLE:
            raise LLMConfigurationError(
                "Google GenAI SDK not installed. Run: pip install google-genai")
        from google import genai as google_genai
        from google.genai import types as google_types

        self._types = google_types
        self._client = google_genai.Client(api_key=self.provider._get_api_key())
        self._contents: List[Any] = []

        declarations = []
        for tool in self.tools:
            declaration: Dict[str, Any] = {
                "name": tool.name, "description": tool.description}
            # Gemini rejects an object schema with no properties, so a no-argument
            # tool is declared with no parameters at all.
            if tool.has_arguments:
                declaration["parameters_json_schema"] = tool.input_schema
            declarations.append(google_types.FunctionDeclaration(**declaration))

        self._config = google_types.GenerateContentConfig(
            system_instruction=self.system,
            tools=[google_types.Tool(function_declarations=declarations)],
            max_output_tokens=self.max_tokens,
            # Tales runs the loop itself so that every call is recorded as an
            # InvestigationToolInvocation. Letting the SDK auto-execute would
            # bypass the audit trail entirely.
            automatic_function_calling=google_types.AutomaticFunctionCallingConfig(
                disable=True, maximum_remote_calls=0),
        )

    def start(self, user_text: str) -> None:
        self._contents.append(self._types.Content(
            role="user", parts=[self._types.Part.from_text(text=user_text)]))

    def submit_tool_results(self, results: List[ToolResult]) -> None:
        parts = []
        for result in results:
            # A function response must be a dict. Errors go under an "error"
            # key so the failure is unmistakable in the transcript.
            payload = ({"error": result.payload} if result.is_error
                       else {"result": result.payload})
            parts.append(self._types.Part.from_function_response(
                name=result.call.name, response=payload))
        self._contents.append(self._types.Content(role="user", parts=parts))

    def run(self) -> AgentTurn:
        try:
            response = self._client.models.generate_content(
                model=self.provider.model_name,
                contents=self._contents,
                config=self._config,
            )
        except Exception as exc:
            raise LLMAPIError(f"Google GenAI API error: {exc}") from exc

        candidates = response.candidates or []
        if not candidates:
            raise LLMAPIError("Google GenAI returned no candidates.")
        candidate = candidates[0]
        if candidate.content is not None:
            self._contents.append(candidate.content)

        text_parts, calls = [], []
        for index, part in enumerate(getattr(candidate.content, "parts", None) or []):
            if getattr(part, "text", None):
                text_parts.append(part.text)
            call = getattr(part, "function_call", None)
            if call is not None:
                calls.append(ToolCall(
                    # Gemini does not always send a call id; the loop only needs
                    # it to pair a result with its call, so a positional one is
                    # sufficient and stable within the turn.
                    id=getattr(call, "id", None) or f"{call.name}-{index}",
                    name=call.name,
                    arguments=dict(call.args or {}),
                ))

        finish = str(getattr(candidate, "finish_reason", "") or "")
        usage = response.usage_metadata
        return AgentTurn(
            text="".join(text_parts),
            tool_calls=calls,
            stop_reason=("tool_use" if calls
                         else "max_tokens" if "MAX_TOKENS" in finish.upper()
                         else "end_turn"),
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )
