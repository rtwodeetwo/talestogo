"""
The agent loop.

An investigation is a model reading evidence it cannot compute for itself. Every
number it can quote was produced by metrics_core and proved against the golden
fixture before the model ever saw it, so the expensive, non-deterministic step is
narration over arithmetic that is already known to be right.

What this module is responsible for is the boundary between the two: presenting
the evidence honestly, recording exactly what was looked at, and above all
keeping "the tool failed" distinguishable from "the tool found nothing". Those
two are the same shape in a JSON payload and opposite in meaning, and conflating
them turns a broken search into a confident finding of no external news.

Nothing here computes a rate. The AST guard in tests/test_metrics_guards.py
enforces that.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ... import models
from ..llm_provider_manager import LLMProviderManager
from . import evidence
from .agent_client import (
    AgentUnavailable,
    ToolResult,
    ToolSpec,
    build_conversation,
    select_agent_provider,
)
from .scope import ComparisonScope, scope_from_investigation
from .search import SEARCH_SCOPES, SEARCH_TOOL_NAME, SearchError, WebSearch

logger = logging.getLogger(__name__)

#: Enough turns to look at the metrics, drill into the movers, read some
#: answers and search, without letting a confused run spend forever.
MAX_ITERATIONS = 15

#: The whole write-up (title, findings, actions, summary) arrives in one
#: response. Too low and it is cut off mid-findings and stored as though
#: complete.
MAX_TOKENS = 12288

#: Stored per tool invocation. The audit trail should be readable, not a
#: verbatim copy of every response body the agent looked at.
STORED_OUTPUT_LIMIT = 10_000

#: Handed to the model. Larger, because response_details legitimately returns a
#: lot, but still bounded so one greedy call cannot crowd out the rest.
MODEL_PAYLOAD_LIMIT = 40_000

#: Investigations are minutes-long and hold a database connection throughout.
#: A thread per request would mean N connections held by N simultaneous
#: triggers; this bounds it, following app/scheduler.py.
MAX_CONCURRENT_INVESTIGATIONS = 4

_executor = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_INVESTIGATIONS,
    thread_name_prefix="investigation_",
)


# ------------------------------------------------------------- tool schemas

def _schema(properties: Dict[str, Any], required: Optional[List[str]] = None
            ) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


EVIDENCE_TOOL_SPECS: Tuple[ToolSpec, ...] = (
    ToolSpec("brand_context",
             "The brand being tracked, its queries (including which are branded "
             "and therefore excluded from visibility metrics), its competitors "
             "and its target descriptors. Start here.",
             _schema({})),
    ToolSpec("compare_scopes",
             "Every canonical metric for both windows with deltas, plus "
             "data_quality showing what was excluded from each side and why. "
             "Check data_quality before attributing any change to reputation.",
             _schema({})),
    ToolSpec("query_level_deltas",
             "Which individual queries moved most, ranked by absolute change in "
             "mention rate.",
             _schema({"limit": {"type": "integer",
                                "description": "How many queries to return "
                                               "(default 10)."}})),
    ToolSpec("platform_breakdown",
             "Mention rate per AI platform on both sides. A change confined to "
             "one platform is usually that platform re-ranking; a change across "
             "all of them suggests something external.",
             _schema({})),
    ToolSpec("response_details",
             "What the AI platforms actually said for one query, with sentiment, "
             "position, descriptors and competitors named. Use this to see the "
             "wording behind a number that moved.",
             _schema({
                 "side": {"type": "string", "enum": ["current", "previous"],
                          "description": "Which window to read."},
                 "query_id": {"type": "string",
                              "description": "The query_id from brand_context "
                                             "or query_level_deltas."},
                 "platform": {"type": "string",
                              "description": "Optional: restrict to one "
                                             "platform."},
             }, required=["side", "query_id"])),
    ToolSpec("competitor_changes",
             "Share of voice per organization on both sides. Competitor gains "
             "can move the brand's share without the brand being mentioned less "
             "often.",
             _schema({})),
    ToolSpec("descriptor_changes",
             "Which words are being used about the brand and how that shifted, "
             "plus the target-descriptor match rate.",
             _schema({})),
    ToolSpec("historical_trend",
             "The same metrics across several consecutive windows, oldest "
             "first, to tell a one-off shift from a sustained direction.",
             _schema({"count": {"type": "integer",
                                "description": "How many windows (2-8, default "
                                               "5)."}})),
)

SEARCH_TOOL_SPEC = ToolSpec(
    SEARCH_TOOL_NAME,
    "Search the web for external events during the period: announcements, "
    "coverage, competitor news. Use it to test a hypothesis the internal data "
    "raised, not as a first step.",
    _schema({
        "scope": {"type": "string", "enum": list(SEARCH_SCOPES),
                  "description": "'brand' for news about the brand itself, "
                                 "'industry' for sector news, 'competitor' for "
                                 "news about competing organizations."},
        "query": {"type": "string",
                  "description": "What to search for, as a plain question."},
    }, required=["scope", "query"]),
)


# -------------------------------------------------------------- the prompt

SYSTEM_PROMPT = """You are an analyst explaining why a brand's visibility across \
AI platforms (ChatGPT, Claude, Gemini, Perplexity) changed between two periods.

You have tools that return figures computed from the same definitions the \
dashboard and the data exports use. Every rate they give you carries its \
numerator and denominator. Never recompute a rate yourself and never estimate \
one; quote what the tools return.

How to work:

1. Call compare_scopes first and read data_quality on BOTH sides before \
concluding anything. Rows excluded as unanalyzed are collection or analysis \
failures, not evidence that the brand went unmentioned. Six unanalyzed \
responses look exactly like a reputation drop and are not one. If data quality \
differs materially between the windows, say so and treat the comparison as \
suspect.
2. Compare rates, not raw counts. Collection volume can differ between windows.
3. Narrow down: which queries moved, which platforms moved, which competitors \
gained. A change confined to one platform is usually that platform re-ranking. \
A change across all of them suggests something external.
4. Read actual responses with response_details before claiming you know what \
changed in how the brand is described.
5. Use web_search only to test a specific hypothesis the internal data raised.

About web_search:

- A search result marked as an error means the search DID NOT RUN. That is not \
evidence that there was no news. Say the external check could not be completed, \
and do not attribute the change to an absence of external events.
- If a search runs and finds nothing relevant, say that plainly rather than \
speculating.
- Do not retry a failed search more than once. It is failing for infrastructure \
reasons and retrying wastes the budget.

Cite specific evidence: numbers with their numerator and denominator, query ids, \
platform names, competitor names, and short quotes from responses. A finding \
without a number in it is not a finding. If the evidence does not support a \
conclusion, say what you could not determine.

When you have enough, reply with exactly this structure and nothing else:

TITLE: <one line naming what changed and, if known, why>

KEY_FINDINGS:
- <finding, with the evidence in it>
- <finding, with the evidence in it>

RECOMMENDED_ACTIONS:
- <action a communications team could actually take>

SUMMARY:
<2 to 4 paragraphs of markdown with specific numbers>
"""


def describe_trigger(trigger_metrics: Optional[str]) -> Optional[str]:
    """Render the stored trigger deltas as a sentence.

    triggers.py stores structured JSON so the record stays machine-readable.
    Pasting that JSON into the prompt would spend tokens on punctuation, so it
    is flattened here.
    """
    if not trigger_metrics:
        return None
    try:
        crossings = json.loads(trigger_metrics)
    except (TypeError, ValueError):
        return trigger_metrics
    if not isinstance(crossings, list):
        return trigger_metrics

    parts = []
    for crossing in crossings:
        if not isinstance(crossing, dict):
            continue
        change = crossing.get("change")
        label = crossing.get("label") or crossing.get("metric") or "a metric"
        movement = f"{change:+.1f} points" if isinstance(change, (int, float)) else "past its threshold"
        parts.append(f"{label} moved {movement}")
    return "; ".join(parts) or None


def _opening_message(scope: ComparisonScope, trigger_metrics: Optional[str]) -> str:
    lines = [
        f"Investigate what changed for this brand between {scope.current_label} "
        f"(current) and {scope.previous_label} (previous). The comparison unit "
        f"is one {scope.unit}.",
    ]
    described = describe_trigger(trigger_metrics)
    if described:
        lines.append(
            "This investigation was triggered automatically because these "
            f"metrics crossed their thresholds: {described}. Confirm the "
            "movement against the tools before explaining it; the threshold "
            "check does not know whether the data was complete.")
    lines.append("Begin with brand_context and compare_scopes.")
    return "\n\n".join(lines)


# --------------------------------------------------------------- parsing

_SECTION_RE = re.compile(
    r"^[ \t]*\**\s*(TITLE|KEY_FINDINGS|KEY FINDINGS|RECOMMENDED_ACTIONS|"
    r"RECOMMENDED ACTIONS|SUMMARY)\s*\**\s*:\**",
    re.IGNORECASE | re.MULTILINE,
)

_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _canonical_section(name: str) -> str:
    return name.upper().replace(" ", "_")


def _split_bullets(block: str) -> List[str]:
    """Bullets if the model used them, otherwise non-empty lines.

    Falling back to lines matters: an otherwise good write-up that forgot the
    dashes should not be stored with an empty findings list.
    """
    items, current = [], None
    for line in block.splitlines():
        if not line.strip():
            continue
        if _BULLET_RE.match(line):
            if current:
                items.append(current.strip())
            current = _BULLET_RE.sub("", line).strip()
        elif current is not None:
            current = f"{current} {line.strip()}"
        else:
            items.append(line.strip())
    if current:
        items.append(current.strip())
    return [item.strip(" *") for item in items if item.strip(" *")]


def parse_final_output(text: str) -> Dict[str, Any]:
    """Pull the four sections out of the model's last message.

    Tolerant on purpose. If the structure is missing entirely the whole text
    becomes the summary rather than being discarded: a badly formatted
    investigation is still worth more than an empty one.
    """
    text = (text or "").strip()
    sections: Dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[_canonical_section(match.group(1))] = text[match.end():end].strip()

    title = " ".join(sections.get("TITLE", "").split())[:500]
    summary = sections.get("SUMMARY", "")
    if not matches:
        summary = text

    return {
        "title": title or None,
        "summary": summary or None,
        "key_findings": _split_bullets(sections.get("KEY_FINDINGS", "")),
        "recommended_actions": _split_bullets(sections.get("RECOMMENDED_ACTIONS", "")),
    }


# ---------------------------------------------------------- tool execution

def _call_evidence_tool(db: Session, scope: ComparisonScope, name: str,
                        arguments: Dict[str, Any]) -> Dict[str, Any]:
    function = evidence.EVIDENCE_TOOLS[name]
    if name == "query_level_deltas":
        return function(db, scope, limit=int(arguments.get("limit") or 10))
    if name == "historical_trend":
        return function(db, scope, count=int(arguments.get("count") or 5))
    if name == "response_details":
        return function(db, scope,
                        side=str(arguments.get("side") or "current"),
                        query_id=str(arguments.get("query_id") or ""),
                        platform=arguments.get("platform") or None)
    return function(db, scope)


def _truncate(payload: str, limit: int) -> str:
    if len(payload) <= limit:
        return payload
    return payload[:limit] + f"\n...[truncated at {limit} characters]"


class _Runner:
    """One investigation, start to finish."""

    def __init__(self, db: Session, investigation: models.Investigation):
        self.db = db
        self.investigation = investigation
        self.limitations: List[Dict[str, str]] = []
        self.sequence = 0
        self.tokens = 0

    # -- persistence helpers

    def _heartbeat(self) -> None:
        self.investigation.last_heartbeat_at = datetime.datetime.utcnow()
        self.db.commit()

    def _record(self, name: str, arguments: Dict[str, Any], output: str,
                failed: bool, error: Optional[str], duration_ms: int) -> None:
        self.sequence += 1
        self.db.add(models.InvestigationToolInvocation(
            investigation_id=self.investigation.id,
            sequence=self.sequence,
            tool_name=name,
            tool_input_json=json.dumps(arguments, default=str)[:STORED_OUTPUT_LIMIT],
            tool_output_json=_truncate(output, STORED_OUTPUT_LIMIT),
            status='failed' if failed else 'success',
            error=error,
            duration_ms=duration_ms,
        ))
        self.db.commit()

    def _add_limitation(self, limitation: Optional[Dict[str, str]]) -> None:
        if not limitation:
            return
        if any(existing["limitation"] == limitation["limitation"]
               for existing in self.limitations):
            return
        self.limitations.append(limitation)

    # -- the loop

    def run(self) -> None:
        investigation = self.investigation
        investigation.status = 'running'
        investigation.started_at = datetime.datetime.utcnow()
        investigation.last_heartbeat_at = investigation.started_at
        investigation.error_message = None
        self.db.commit()

        scope = scope_from_investigation(investigation)
        context = evidence.brand_context(self.db, scope)

        manager = LLMProviderManager(self.db, self._tenant_id())
        provider = select_agent_provider(manager.get_enabled_providers())
        if provider is None:
            raise AgentUnavailable(
                "No configured LLM provider can run an investigation. "
                "Investigations need a provider that supports tool use: "
                "Anthropic, OpenAI, Azure OpenAI, Google Gemini, or an "
                "OpenAI-compatible endpoint. Set the matching API key and "
                "enable the provider under Admin, LLM Providers.")

        search = WebSearch(
            manager,
            brand_name=context.get("brand_name") or "the brand",
            industry=context.get("industry"),
            window_label=f"{scope.previous_label} to {scope.current_label}",
        )
        self._add_limitation(search.limitation())

        tools = list(EVIDENCE_TOOL_SPECS)
        if search.configured:
            tools.append(SEARCH_TOOL_SPEC)

        conversation = build_conversation(
            provider, SYSTEM_PROMPT, tools, max_tokens=MAX_TOKENS)
        conversation.start(_opening_message(scope, investigation.trigger_metrics))

        final_text, truncated = "", False
        for iteration in range(MAX_ITERATIONS):
            turn = conversation.run()
            self.tokens += turn.input_tokens + turn.output_tokens
            self._heartbeat()

            if turn.stop_reason == "max_tokens":
                truncated = True

            if turn.stop_reason != "tool_use" or not turn.tool_calls:
                final_text = turn.text
                break

            results = [self._execute(scope, search, call) for call in turn.tool_calls]
            conversation.submit_tool_results(results)

            if iteration == MAX_ITERATIONS - 1:
                self._add_limitation({
                    "limitation": (f"The investigation reached its {MAX_ITERATIONS}"
                                   "-step limit before finishing"),
                    "impact": ("The write-up is based on the evidence gathered so "
                               "far and may not have followed every lead."),
                })
                final_text = turn.text

        if truncated:
            # Recording this rather than storing a half-sentence write-up as a
            # completed investigation.
            self._add_limitation({
                "limitation": "The write-up hit the response length limit",
                "impact": ("The summary or the findings list may be cut off. "
                           "Re-run to get a complete write-up."),
            })

        self._finish(parse_final_output(final_text))

    def _tenant_id(self) -> Optional[int]:
        user = self.db.query(models.User).filter(
            models.User.id == self.investigation.user_id).first()
        return getattr(user, "tenant_id", None) if user else None

    def _execute(self, scope: ComparisonScope, search: WebSearch, call) -> ToolResult:
        started = time.monotonic()
        try:
            if call.name == SEARCH_TOOL_NAME:
                text = search.run(str(call.arguments.get("scope") or "brand"),
                                  str(call.arguments.get("query") or ""))
                payload = text
            elif call.name in evidence.EVIDENCE_TOOLS:
                payload = json.dumps(
                    _call_evidence_tool(self.db, scope, call.name, call.arguments),
                    default=str)
            else:
                raise KeyError(f"Unknown tool {call.name!r}")
        except SearchError as exc:
            self._add_limitation(search.limitation())
            return self._failure(call, str(exc), started)
        except Exception as exc:  # noqa: BLE001 - every tool failure is reported
            # A tool that raised may have left the session unusable, and every
            # later tool in the run would then fail for an unrelated reason.
            # Swallowing this into a success-shaped payload is worse still: the
            # model cannot tell a broken tool from an empty result.
            self.db.rollback()
            logger.exception("Investigation %s: tool %s failed",
                             self.investigation.id, call.name)
            return self._failure(call, f"{type(exc).__name__}: {exc}", started)

        duration = int((time.monotonic() - started) * 1000)
        self._record(call.name, call.arguments, payload, False, None, duration)
        return ToolResult(call=call, payload=_truncate(payload, MODEL_PAYLOAD_LIMIT))

    def _failure(self, call, message: str, started: float) -> ToolResult:
        duration = int((time.monotonic() - started) * 1000)
        self._record(call.name, call.arguments, message, True, message, duration)
        return ToolResult(call=call, payload=message, is_error=True)

    def _finish(self, parsed: Dict[str, Any]) -> None:
        investigation = self.investigation
        investigation.title = parsed["title"]
        investigation.summary = parsed["summary"]
        investigation.key_findings = json.dumps(parsed["key_findings"])
        investigation.recommended_actions = json.dumps(parsed["recommended_actions"])
        investigation.limitations = json.dumps(self.limitations)
        investigation.total_tool_calls = self.sequence
        investigation.total_tokens_used = self.tokens
        investigation.status = 'completed'
        investigation.completed_at = datetime.datetime.utcnow()
        investigation.last_heartbeat_at = investigation.completed_at
        self.db.commit()


def run_investigation(db: Session, investigation_id: int) -> models.Investigation:
    """Run one investigation to completion on the caller's session.

    Failure is recorded on the record itself, not raised: a caller polling the
    API has no other way to learn what went wrong.
    """
    investigation = db.query(models.Investigation).filter(
        models.Investigation.id == investigation_id).first()
    if investigation is None:
        raise LookupError(f"Investigation {investigation_id} not found")

    runner = _Runner(db, investigation)
    try:
        runner.run()
    except Exception as exc:  # noqa: BLE001 - surfaced on the record
        logger.exception("Investigation %s failed", investigation_id)
        db.rollback()
        investigation = db.query(models.Investigation).filter(
            models.Investigation.id == investigation_id).first()
        if investigation is not None:
            investigation.status = 'failed'
            investigation.error_message = f"{type(exc).__name__}: {exc}"
            investigation.completed_at = datetime.datetime.utcnow()
            investigation.total_tool_calls = runner.sequence
            investigation.total_tokens_used = runner.tokens
            if runner.limitations:
                investigation.limitations = json.dumps(runner.limitations)
            db.commit()
    return investigation


def _run_in_background(investigation_id: int) -> None:
    from ...database import SessionLocal

    db = SessionLocal()
    try:
        run_investigation(db, investigation_id)
    except Exception:  # noqa: BLE001 - a worker thread must never die silently
        logger.exception("Investigation %s crashed outside the runner",
                         investigation_id)
    finally:
        db.close()


def submit(investigation_id: int) -> None:
    """Queue an investigation on the bounded worker pool."""
    _executor.submit(_run_in_background, investigation_id)
