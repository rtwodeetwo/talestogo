#!/usr/bin/env python3
"""
Find out what an LLM gateway will actually do before deploying against it.

Many labs reach the model vendors through a shared internal gateway (LiteLLM,
an API-management layer, a reseller proxy) rather than directly. The gateway
speaks the OpenAI chat-completions shape, so a plain call works and everything
looks fine, while two capabilities Tales depends on may be quietly missing:

  Tool calling. Investigations are a tool-use loop. If the gateway does not
  forward `tools`, or drops `tool_calls` on the way back, investigations do not
  degrade, they do not run.

  Grounded web search. Collection is supposed to reflect what a person using the
  consumer app sees, which means the model searches the web. Grounding is not a
  property of the model and cannot be selected by model name: it lives in
  vendor-specific endpoints (OpenAI's Responses API, Anthropic's server-side
  tool, Google's grounding config). A chat-completions gateway carries none of
  them, so a grounded-looking configuration can silently collect ungrounded
  answers.

Timeouts are the third question, and the easiest to be caught by: a gateway that
cuts requests at 60 seconds will fail long collection prompts that the vendor
would have answered.

Usage:

    export OHMIC_API_KEY=...
    python scripts/admin/probe_llm_gateway.py \
        --base-url https://api.ohmic.pppl.gov/v1 \
        --models gpt-5.5,vertex_ai/claude-opus-4-8,gemini-3.1-pro-preview

Nothing here writes to the database. It makes a handful of small API calls plus
one deliberately large one, and prints what it found.
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: the openai package is required. pip install openai")
    sys.exit(1)


#: Mirrors app/services/investigation/service.py MODEL_PAYLOAD_LIMIT. A tool
#: result really can be this big, and a gateway with a smaller body limit will
#: fail mid-investigation rather than at configuration time.
LARGE_PAYLOAD_CHARS = 40_000

#: Shaped like a real evidence tool so the probe exercises the same thing the
#: agent will: a required enum, a required string, and a description.
PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "compare_scopes",
        "description": ("Return every metric for both windows being compared, "
                        "with deltas."),
        "parameters": {
            "type": "object",
            "properties": {
                "side": {"type": "string", "enum": ["current", "previous"],
                         "description": "Which window to read."},
                "metric": {"type": "string",
                           "description": "Which metric to return."},
            },
            "required": ["side", "metric"],
        },
    },
}


class Result:
    def __init__(self, name: str):
        self.name = name
        self.ok: Optional[bool] = None
        self.seconds: float = 0.0
        self.detail: str = ""

    def mark(self, ok: bool, detail: str = "") -> "Result":
        self.ok = ok
        self.detail = detail
        return self

    @property
    def symbol(self) -> str:
        return "ok  " if self.ok else "FAIL"

    def line(self) -> str:
        detail = f"  {self.detail}" if self.detail else ""
        return f"    [{self.symbol}] {self.name:<28} {self.seconds:6.1f}s{detail}"


def _first_choice(response):
    """The one choice, or None if the gateway returned a response without any.

    A gateway can return HTTP 200 with an empty `choices` list, which is neither
    a success nor an exception. Reaching straight for choices[0] turns that into
    an IndexError and loses the finding, so it is treated as its own result.
    """
    choices = getattr(response, "choices", None) or []
    return choices[0] if choices else None


def _timed(fn):
    started = time.monotonic()
    try:
        value = fn()
        return value, None, time.monotonic() - started
    except Exception as exc:  # noqa: BLE001 - the probe reports, never raises
        return None, exc, time.monotonic() - started


def _max_tokens_kwarg(model: str, value: int) -> Dict[str, int]:
    """GPT-5 and the o-series want max_completion_tokens."""
    lowered = model.lower()
    reasoning = any(marker in lowered for marker in ("gpt-5", "o1-", "o3-", "o4-"))
    return {"max_completion_tokens": value} if reasoning else {"max_tokens": value}


def probe_plain(client: OpenAI, model: str) -> Result:
    result = Result("plain completion")

    def call():
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            **_max_tokens_kwarg(model, 32),
        )

    response, error, result.seconds = _timed(call)
    if error:
        return result.mark(False, f"{type(error).__name__}: {str(error)[:160]}")
    choice = _first_choice(response)
    if choice is None:
        return result.mark(False, "HTTP 200 but no choices returned")
    text = (choice.message.content or "").strip()
    return result.mark(bool(text), f"returned {len(text)} chars")


def probe_tool_call(client: OpenAI, model: str) -> Result:
    """The one that decides whether investigations are possible at all."""
    result = Result("tool call offered")

    def call():
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system",
                 "content": "You investigate metric changes. Use the tools provided."},
                {"role": "user",
                 "content": "What was the mention rate in the current window? "
                            "Use compare_scopes to find out."},
            ],
            tools=[PROBE_TOOL],
            **_max_tokens_kwarg(model, 256),
        )

    response, error, result.seconds = _timed(call)
    if error:
        return result.mark(False, f"{type(error).__name__}: {str(error)[:160]}")

    choice = _first_choice(response)
    if choice is None:
        return result.mark(False, "HTTP 200 but no choices returned")
    message = choice.message
    calls = message.tool_calls or []
    if not calls:
        # The gateway answered, but nothing came back that the agent loop can
        # act on. Indistinguishable from a model that chose not to call a tool,
        # which is why the prompt above leaves it no other reasonable move.
        return result.mark(
            False,
            "no tool_calls returned (gateway may strip tools, or the model "
            "declined)")
    try:
        arguments = json.loads(calls[0].function.arguments or "{}")
    except ValueError:
        return result.mark(False, "tool_calls returned unparseable arguments")
    return result.mark(True, f"{calls[0].function.name}({', '.join(sorted(arguments))})")


def probe_tool_round_trip(client: OpenAI, model: str) -> Result:
    """Sending a tool RESULT back is a separate thing from receiving a call.

    Some gateways forward `tools` but reject the `tool` role on the way back in,
    which fails on the agent loop's second turn rather than its first.
    """
    result = Result("tool result accepted")

    def call():
        first = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user",
                 "content": "Call compare_scopes for the current window's "
                            "mention_rate."},
            ],
            tools=[PROBE_TOOL],
            **_max_tokens_kwarg(model, 256),
        )
        choice = _first_choice(first)
        if choice is None:
            raise RuntimeError("HTTP 200 but no choices returned")
        message = choice.message
        if not message.tool_calls:
            raise RuntimeError("no tool call to respond to")
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user",
                 "content": "Call compare_scopes for the current window's "
                            "mention_rate."},
                message.model_dump(exclude_none=True),
                {"role": "tool",
                 "tool_call_id": message.tool_calls[0].id,
                 "content": json.dumps({"mention_rate": {"value": 55.0,
                                                         "numerator": 22,
                                                         "denominator": 40}})},
            ],
            tools=[PROBE_TOOL],
            **_max_tokens_kwarg(model, 256),
        )

    response, error, result.seconds = _timed(call)
    if error:
        return result.mark(False, f"{type(error).__name__}: {str(error)[:160]}")
    choice = _first_choice(response)
    if choice is None:
        return result.mark(False, "HTTP 200 but no choices returned")
    text = (choice.message.content or "").strip()
    return result.mark(bool(text), f"replied with {len(text)} chars")


def probe_large_payload(client: OpenAI, model: str) -> Result:
    """A real tool result can be tens of thousands of characters."""
    result = Result(f"{LARGE_PAYLOAD_CHARS // 1000}k char payload")
    filler = json.dumps({"rows": [{"query_id": f"Q{i}", "text": "x" * 60}
                                  for i in range(LARGE_PAYLOAD_CHARS // 80)]})

    def call():
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user",
                 "content": "Here is a tool result. Reply with the single word "
                            "'received'.\n\n" + filler[:LARGE_PAYLOAD_CHARS]},
            ],
            **_max_tokens_kwarg(model, 32),
        )

    response, error, result.seconds = _timed(call)
    if error:
        return result.mark(False, f"{type(error).__name__}: {str(error)[:160]}")
    return result.mark(True, "accepted")


def probe_responses_api(base_url: str, api_key: str, model: str) -> Result:
    """Whether the gateway passes through OpenAI's Responses API.

    This is the only route by which grounded collection through a gateway could
    work for OpenAI models. A 404 here means grounding must come from a direct
    vendor key, and any provider row pointed at this gateway should have
    supports_web_search left off so it does not claim grounding it cannot do.
    """
    result = Result("Responses API + web_search")

    def call():
        return httpx.post(
            f"{base_url.rstrip('/')}/responses",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"model": model,
                  "input": "What happened in fusion research this week?",
                  "tools": [{"type": "web_search"}]},
            timeout=120.0,
        )

    response, error, result.seconds = _timed(call)
    if error:
        return result.mark(False, f"{type(error).__name__}: {str(error)[:160]}")
    if response.status_code == 200:
        return result.mark(True, "grounded collection through the gateway is possible")
    return result.mark(
        False,
        f"HTTP {response.status_code}: {response.text[:120]}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe an LLM gateway for the capabilities Tales needs")
    parser.add_argument("--base-url", required=True,
                        help="Gateway base URL, e.g. https://api.ohmic.pppl.gov/v1")
    parser.add_argument("--api-key-env", default="OHMIC_API_KEY",
                        help="Environment variable holding the key "
                             "(default: OHMIC_API_KEY)")
    parser.add_argument("--models", required=True,
                        help="Comma-separated model names to probe")
    parser.add_argument("--timeout", type=float, default=180.0,
                        help="Per-request timeout in seconds (default: 180)")
    parser.add_argument("--skip-large", action="store_true",
                        help="Skip the large-payload probe")
    args = parser.parse_args()

    api_key = os.getenv(args.api_key_env, "")
    if not api_key:
        print(f"ERROR: {args.api_key_env} is not set in the environment.")
        return 1

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    client = OpenAI(api_key=api_key, base_url=args.base_url, timeout=args.timeout)

    print(f"\nGateway: {args.base_url}")
    print(f"Key from: {args.api_key_env} (value not shown)")
    print(f"Per-request timeout: {args.timeout}s\n")

    verdicts: Dict[str, Dict[str, Any]] = {}

    for model in models:
        print(f"  {model}")
        results: List[Result] = [probe_plain(client, model)]
        if results[0].ok:
            results.append(probe_tool_call(client, model))
            if results[-1].ok:
                results.append(probe_tool_round_trip(client, model))
            if not args.skip_large:
                results.append(probe_large_payload(client, model))
        for result in results:
            print(result.line())
        print()

        by_name = {r.name: r for r in results}
        verdicts[model] = {
            "collection": bool(by_name["plain completion"].ok),
            "investigations": bool(by_name.get("tool call offered")
                                   and by_name["tool call offered"].ok
                                   and by_name.get("tool result accepted")
                                   and by_name["tool result accepted"].ok),
            "slowest": max(r.seconds for r in results),
        }

    print("  gateway-wide")
    grounding = probe_responses_api(args.base_url, api_key, models[0])
    print(grounding.line())
    print()

    print("=" * 68)
    print("VERDICT")
    print("=" * 68)
    for model, verdict in verdicts.items():
        print(f"\n  {model}")
        print(f"    collection      {'yes' if verdict['collection'] else 'NO'}")
        print(f"    investigations  {'yes' if verdict['investigations'] else 'NO'}")
        print(f"    slowest probe   {verdict['slowest']:.1f}s")

    print(f"\n  grounded collection through this gateway: "
          f"{'yes' if grounding.ok else 'NO'}")
    if not grounding.ok:
        print("    Set supports_web_search = false on any provider row pointed "
              "at this gateway.")
        print("    Otherwise Tales will fall back to an ungrounded call and "
              "record it as such,")
        print("    which is correct but means no grounded data is being "
              "collected at all.")

    if not any(v["investigations"] for v in verdicts.values()):
        print("\n  No probed model can run an investigation through this "
              "gateway. Investigations")
        print("  need a direct vendor key, or a gateway model that forwards "
              "tool calls.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
