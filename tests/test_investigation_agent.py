"""
The agent loop, with the model stubbed out.

No test here calls a real API. What is being checked is everything around the
model: that the evidence tools are dispatched correctly, that a broken tool is
handed back marked as broken, that a deployment with no grounded provider gets a
degraded run rather than a failed one, and that a write-up cut off by the token
limit is recorded as incomplete instead of being stored as though it finished.

Those are the failure modes that make an investigation lie, and none of them
needs a live model to reproduce.
"""
import json

import pytest

from app import models
from app.services.investigation import service
from app.services.investigation.agent_client import AgentTurn, ToolCall
from tests import golden_expected as gx
from tests.fixtures.golden_dataset import BRAND_1_ID, USER_1_ID


# ------------------------------------------------------------------ stubs

class FakeProvider:
    """Enough of a ProviderConfig for the loop to choose it."""

    def __init__(self, api_type="anthropic", model_name="claude-opus-4-8",
                 provider_key="claude", search_result=None, search_error=None):
        self.api_type = api_type
        self.model_name = model_name
        self.provider_key = provider_key
        self.sort_order = 0
        self.api_endpoint = None
        self.api_version = None
        self._search_result = search_result
        self._search_error = search_error

    def call_with_web_search(self, prompt, analysis_provider=None, max_tokens=None):
        if self._search_error:
            raise RuntimeError(self._search_error)
        return self._search_result


class FakeManager:
    def __init__(self, agent_providers, search_providers=()):
        self._agent = list(agent_providers)
        self._search = list(search_providers)

    def get_enabled_providers(self):
        return self._agent

    def get_web_search_providers(self):
        return self._search

    def get_analysis_provider(self):
        return self._agent[0] if self._agent else None


class FakeConversation:
    """Replays a scripted list of turns and records what it was handed back."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.system = None
        self.opening = None
        self.results = []

    def start(self, user_text):
        self.opening = user_text

    def submit_tool_results(self, results):
        self.results.extend(results)

    def run(self):
        if not self._turns:
            return AgentTurn(text="TITLE: Ran out of script", stop_reason="end_turn")
        return self._turns.pop(0)


FINAL_TEXT = """TITLE: Mention rate fell on one platform

KEY_FINDINGS:
- Gemini moved while the others held steady

RECOMMENDED_ACTIONS:
- Re-check the Gemini collection

SUMMARY:
The change is confined to one platform.
"""


def _final_turn(stop_reason="end_turn"):
    return AgentTurn(text=FINAL_TEXT, stop_reason=stop_reason,
                     input_tokens=100, output_tokens=50)


def _tool_turn(name, arguments=None, call_id="call-1"):
    return AgentTurn(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments or {})],
        stop_reason="tool_use", input_tokens=10, output_tokens=5)


@pytest.fixture
def investigation(golden_client, golden_db):
    """A pending batch-mode investigation over the golden dataset."""
    response = golden_client.post("/api/investigations/trigger",
                                  json={"comparison_mode": "batch"})
    assert response.status_code == 202, response.text
    record_id = response.json()["investigation_id"]
    return golden_db.query(models.Investigation).get(record_id)


@pytest.fixture
def run_with(monkeypatch, golden_db):
    """Run an investigation against a scripted conversation."""
    def runner(record, turns, agent_providers=None, search_providers=()):
        conversation = FakeConversation(turns)
        manager = FakeManager(
            agent_providers if agent_providers is not None else [FakeProvider()],
            search_providers)
        monkeypatch.setattr(service, "LLMProviderManager",
                            lambda db, tenant_id: manager)
        monkeypatch.setattr(service, "build_conversation",
                            lambda *args, **kwargs: conversation)
        service.run_investigation(golden_db, record.id)
        golden_db.refresh(record)
        return conversation
    return runner


def _invocations(db, record):
    return db.query(models.InvestigationToolInvocation).filter(
        models.InvestigationToolInvocation.investigation_id == record.id
    ).order_by(models.InvestigationToolInvocation.sequence).all()


# ------------------------------------------------------------------ tests

class TestHappyPath:
    def test_evidence_tool_is_dispatched_and_recorded(self, investigation, run_with,
                                                      golden_db):
        run_with(investigation, [_tool_turn("compare_scopes"), _final_turn()])

        calls = _invocations(golden_db, investigation)
        assert [c.tool_name for c in calls] == ["compare_scopes"]
        assert calls[0].status == "success"

        payload = json.loads(calls[0].tool_output_json)
        # The agent is handed the canonical figure, not a second implementation
        # of it. If this drifts from the golden expectation, an investigation is
        # quoting numbers the dashboard does not agree with.
        assert payload["current"]["mention_rate"]["value"] == pytest.approx(
            gx.B2_MENTION_RATE_BY_BATCH)

    def test_findings_are_parsed_onto_the_record(self, investigation, run_with):
        run_with(investigation, [_final_turn()])

        assert investigation.status == "completed"
        assert investigation.title == "Mention rate fell on one platform"
        assert json.loads(investigation.key_findings) == [
            "Gemini moved while the others held steady"]
        assert json.loads(investigation.recommended_actions) == [
            "Re-check the Gemini collection"]
        assert "confined to one platform" in investigation.summary
        assert investigation.total_tokens_used == 150
        assert investigation.completed_at is not None

    def test_arguments_reach_the_tool(self, investigation, run_with, golden_db):
        run_with(investigation,
                 [_tool_turn("historical_trend", {"count": 3}), _final_turn()])
        payload = json.loads(_invocations(golden_db, investigation)[0].tool_output_json)
        assert len(payload["points"]) <= 3


class TestFailedTools:
    """A broken tool and an empty result must never look the same."""

    def test_unknown_tool_is_recorded_as_failed_and_flagged_to_the_model(
            self, investigation, run_with, golden_db):
        conversation = run_with(
            investigation,
            [_tool_turn("guess_the_answer"), _final_turn()])

        call = _invocations(golden_db, investigation)[0]
        assert call.status == "failed"
        assert call.error

        # The flag is the whole point: without it the model reads a failure
        # payload as an ordinary answer.
        assert len(conversation.results) == 1
        assert conversation.results[0].is_error is True

        # A tool failure is not a run failure.
        assert investigation.status == "completed"

    def test_bad_arguments_fail_the_call_not_the_run(self, investigation, run_with,
                                                     golden_db):
        run_with(investigation,
                 [_tool_turn("historical_trend", {"count": "not a number"}),
                  _final_turn()])
        assert _invocations(golden_db, investigation)[0].status == "failed"
        assert investigation.status == "completed"


class TestWebSearch:
    def test_no_grounded_provider_degrades_the_run_rather_than_failing_it(
            self, investigation, run_with):
        conversation = run_with(investigation, [_final_turn()], search_providers=[])

        assert investigation.status == "completed"
        assert investigation.error_message is None
        limitations = json.loads(investigation.limitations)
        assert any("search unavailable" in entry["limitation"].lower()
                   for entry in limitations)
        assert any("internal data only" in entry["impact"] for entry in limitations)

        # The tool is not offered at all when it cannot work, so the model
        # cannot spend a turn discovering that.
        assert conversation.opening is not None

    def test_a_search_that_fails_everywhere_is_an_error_and_a_limitation(
            self, investigation, run_with, golden_db):
        searcher = FakeProvider(provider_key="gemini", api_type="google",
                                search_error="503 upstream unavailable")
        conversation = run_with(
            investigation,
            [_tool_turn("web_search", {"scope": "brand", "query": "any news?"}),
             _final_turn()],
            search_providers=[searcher])

        call = _invocations(golden_db, investigation)[0]
        assert call.tool_name == "web_search"
        assert call.status == "failed"
        assert conversation.results[0].is_error is True

        limitations = json.loads(investigation.limitations)
        assert any("not evidence" in entry["impact"] for entry in limitations), (
            "A failed search must be recorded as an unchecked external cause, "
            "never as an absence of news.")

    def test_an_empty_grounded_answer_counts_as_a_failure(
            self, investigation, run_with, golden_db):
        """Google grounding can return an empty string without raising."""
        searcher = FakeProvider(provider_key="gemini", api_type="google",
                                search_result="   ")
        run_with(investigation,
                 [_tool_turn("web_search", {"scope": "brand", "query": "news?"}),
                  _final_turn()],
                 search_providers=[searcher])
        assert _invocations(golden_db, investigation)[0].status == "failed"

    def test_a_successful_search_is_passed_through(self, investigation, run_with,
                                                   golden_db):
        searcher = FakeProvider(provider_key="gemini", api_type="google",
                                search_result="Reuters, 3 Feb 2026: a merger.")
        conversation = run_with(
            investigation,
            [_tool_turn("web_search", {"scope": "industry", "query": "news?"}),
             _final_turn()],
            search_providers=[searcher])

        call = _invocations(golden_db, investigation)[0]
        assert call.status == "success"
        assert "Reuters" in call.tool_output_json
        assert conversation.results[0].is_error is False
        assert investigation.limitations == "[]"


class TestRunLevelFailures:
    def test_no_tool_capable_provider_fails_with_an_actionable_message(
            self, investigation, run_with):
        run_with(investigation, [_final_turn()], agent_providers=[])
        assert investigation.status == "failed"
        assert "tool use" in investigation.error_message
        assert "LLM Providers" in investigation.error_message

    def test_a_search_model_is_not_chosen_as_the_reasoning_model(
            self, investigation, run_with):
        """Perplexity speaks an OpenAI-shaped API but cannot call tools."""
        run_with(investigation, [_final_turn()],
                 agent_providers=[FakeProvider(api_type="openai_compatible",
                                               model_name="sonar-pro",
                                               provider_key="perplexity")])
        assert investigation.status == "failed"

    def test_a_truncated_write_up_is_recorded_as_incomplete(self, investigation,
                                                            run_with):
        run_with(investigation, [_final_turn(stop_reason="max_tokens")])
        assert investigation.status == "completed"
        assert any("length limit" in entry["limitation"]
                   for entry in json.loads(investigation.limitations))

    def test_the_loop_is_capped(self, investigation, run_with, golden_db):
        """A model that never stops calling tools must still terminate."""
        run_with(investigation,
                 [_tool_turn("brand_context", call_id=f"call-{i}")
                  for i in range(service.MAX_ITERATIONS + 5)])

        assert len(_invocations(golden_db, investigation)) == service.MAX_ITERATIONS
        assert investigation.status == "completed"
        assert any("step limit" in entry["limitation"]
                   for entry in json.loads(investigation.limitations))


class TestParsing:
    def test_bold_headers_are_tolerated(self):
        parsed = service.parse_final_output(
            "**TITLE:** Something moved\n\n**KEY_FINDINGS:**\n- one\n\n"
            "**SUMMARY:**\nBecause.")
        assert parsed["title"] == "Something moved"
        assert parsed["key_findings"] == ["one"]
        assert parsed["summary"] == "Because."

    def test_unstructured_output_is_kept_as_the_summary(self):
        """A badly formatted investigation is worth more than an empty one."""
        parsed = service.parse_final_output("I could not determine the cause.")
        assert parsed["summary"] == "I could not determine the cause."
        assert parsed["title"] is None

    def test_numbered_findings_and_wrapped_lines(self):
        parsed = service.parse_final_output(
            "TITLE: t\n\nKEY_FINDINGS:\n1. first finding\n   continued here\n"
            "2. second finding\n\nSUMMARY:\ns")
        assert parsed["key_findings"] == [
            "first finding continued here", "second finding"]
