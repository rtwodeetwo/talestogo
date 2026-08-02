"""
The evidence pack, against hand-derived expectations.

An investigation's conclusions are only worth as much as the evidence behind
them, so the evidence is tested the same way metrics_core is: deterministic
functions over the golden fixture, checked against constants in
tests/golden_expected.py that were computed by hand.

No LLM is involved in anything tested here. That is the design: the expensive,
non-deterministic part of an investigation is narration over numbers that have
already been proven correct.
"""
import pytest

from app.services import metrics_core as mc
from app.services.investigation import evidence as ev
from app.services.investigation import scope as sc
from tests import golden_expected as gx
from tests.fixtures.golden_dataset import (
    BATCH_1_ID, BATCH_2_ID, BRAND_1_ID, USER_1_ID, USER_2_ID, BRAND_2_ID,
)


@pytest.fixture()
def batch_scope(golden_db):
    """February (batch 2) against January (batch 1)."""
    return sc.build_batch_scope(golden_db, USER_1_ID, BRAND_1_ID)


class TestScopeResolution:
    def test_latest_batch_compares_against_its_predecessor(self, batch_scope):
        assert batch_scope.mode == "batch"
        assert batch_scope.current.batch_id == BATCH_2_ID
        assert batch_scope.previous.batch_id == BATCH_1_ID

    def test_explicit_batch_compares_backwards_not_forwards(self, golden_db):
        """Ordering by started_at alone would pick a NEWER batch when an older
        batch_id is passed, and compare the two windows the wrong way round."""
        scope = sc.build_batch_scope(golden_db, USER_1_ID, BRAND_1_ID, batch_id=BATCH_2_ID)
        assert scope.current.batch_id == BATCH_2_ID
        assert scope.previous.batch_id == BATCH_1_ID

    def test_earliest_batch_has_nothing_to_compare(self, golden_db):
        with pytest.raises(sc.ScopeError, match="earliest collection"):
            sc.build_batch_scope(golden_db, USER_1_ID, BRAND_1_ID, batch_id=BATCH_1_ID)

    def test_unknown_batch_is_rejected(self, golden_db):
        with pytest.raises(sc.ScopeError, match="not found"):
            sc.build_batch_scope(golden_db, USER_1_ID, BRAND_1_ID, batch_id=9999)

    def test_invalid_mode_is_rejected(self, golden_db):
        with pytest.raises(sc.ScopeError, match="Invalid comparison_mode"):
            sc.build_scope(golden_db, USER_1_ID, BRAND_1_ID, "fortnight")

    def test_empty_period_is_refused_rather_than_read_as_a_collapse(self, golden_db):
        """Q4 2025 has no data. Comparing against it would report the current
        quarter's whole value as the size of the change."""
        import datetime
        with pytest.raises(sc.ScopeError, match="nothing to compare"):
            sc.build_period_scope(golden_db, USER_1_ID, BRAND_1_ID, "quarter",
                                  datetime.datetime(2026, 1, 1))

    def test_scope_survives_a_round_trip_through_a_record(self, golden_db):
        from app import models
        record = models.Investigation(user_id=USER_1_ID, brand_id=BRAND_1_ID)
        scope = sc.build_batch_scope(golden_db, USER_1_ID, BRAND_1_ID)
        sc.apply_scope_to_record(record, scope)
        rebuilt = sc.scope_from_investigation(record)
        assert rebuilt.current.batch_id == scope.current.batch_id
        assert rebuilt.previous.batch_id == scope.previous.batch_id
        assert rebuilt.current_label == scope.current_label


class TestCompareScopes:
    def test_both_sides_match_the_canonical_metrics(self, golden_db, batch_scope):
        result = ev.compare_scopes(golden_db, batch_scope)
        assert result["previous"]["mention_rate"]["value"] == gx.B1_MENTION_RATE
        assert result["previous"]["mention_rate"]["numerator"] == gx.B1_MENTION_NUMERATOR
        assert result["previous"]["mention_rate"]["denominator"] == gx.B1_POPULATION
        assert result["current"]["mention_rate"]["value"] == gx.B2_MENTION_RATE_BY_BATCH

    def test_delta_is_current_minus_previous(self, golden_db, batch_scope):
        result = ev.compare_scopes(golden_db, batch_scope)
        # 60.0 (February) - 55.0 (January)
        assert result["deltas"]["mention_rate"] == 5.0

    def test_sentiment_matches_the_dashboard(self, golden_db, batch_scope):
        result = ev.compare_scopes(golden_db, batch_scope)
        assert (result["previous"]["positive_sentiment_rate"]["value"]
                == gx.B1_POSITIVE_SENTIMENT_RATE)

    def test_share_of_voice_matches_the_dashboard(self, golden_db, batch_scope):
        result = ev.compare_scopes(golden_db, batch_scope)
        assert result["previous"]["share_of_voice"]["value"] == gx.B1_SHARE_OF_VOICE

    def test_positioning_average_is_on_the_five_point_scale(self, golden_db, batch_scope):
        result = ev.compare_scopes(golden_db, batch_scope)
        assert (result["previous"]["positioning_average"]["value"]
                == gx.B1_POSITIONING_AVERAGE)

    def test_reports_what_was_excluded_on_each_side(self, golden_db, batch_scope):
        """The check no other surface offers: is this a reputation change, or did
        the collection simply fail?"""
        result = ev.compare_scopes(golden_db, batch_scope)
        quality = result["previous"]["data_quality"]
        assert quality["counted"] == gx.B1_POPULATION
        assert quality["unanalyzed_excluded"] == gx.B1_UNANALYZED_EXCLUDED
        assert quality["branded_excluded"] == gx.B1_BRANDED_EXCLUDED

    def test_warns_against_reading_excluded_rows_as_reputation(self, golden_db, batch_scope):
        result = ev.compare_scopes(golden_db, batch_scope)
        assert any("data_quality" in note for note in result["notes"])

    def test_every_figure_carries_its_numerator_and_denominator(self, golden_db, batch_scope):
        """The agent is told to cite evidence; a bare percentage invites vague
        claims."""
        result = ev.compare_scopes(golden_db, batch_scope)
        for side in ("current", "previous"):
            for key in ("mention_rate", "positive_sentiment_rate", "share_of_voice"):
                assert set(result[side][key]) == {"value", "numerator", "denominator"}


class TestQueryLevelDeltas:
    def test_ranked_by_absolute_change(self, golden_db, batch_scope):
        result = ev.query_level_deltas(golden_db, batch_scope, limit=5)
        changes = [abs(r["change"]) for r in result["queries"] if r["change"] is not None]
        assert changes == sorted(changes, reverse=True)

    def test_excludes_branded_queries(self, golden_db, batch_scope):
        """A branded query measures nothing about organic visibility."""
        result = ev.query_level_deltas(golden_db, batch_scope, limit=50)
        assert all(not r["query_id"].startswith("QB") for r in result["queries"])

    def test_respects_the_limit(self, golden_db, batch_scope):
        assert len(ev.query_level_deltas(golden_db, batch_scope, limit=2)["queries"]) == 2


class TestPlatformBreakdown:
    def test_matches_canonical_platform_rates(self, golden_db, batch_scope):
        result = ev.platform_breakdown(golden_db, batch_scope)
        previous = {name: value["value"]
                    for name, value in result["previous"]["platforms"].items()}
        assert previous == gx.B1_PLATFORM_MENTION_RATES

    def test_reports_a_change_per_platform(self, golden_db, batch_scope):
        result = ev.platform_breakdown(golden_db, batch_scope)
        assert set(result["changes"]) == set(gx.B1_PLATFORM_MENTION_RATES)


class TestResponseDetails:
    def test_returns_the_actual_answer_text(self, golden_db, batch_scope):
        result = ev.response_details(golden_db, batch_scope, "previous", "Q001")
        assert result["responses"]
        assert all(r["response_text"] for r in result["responses"])

    def test_truncates_long_bodies_and_says_so(self, golden_db, batch_scope):
        """The fixture carries a 40,000 character answer."""
        found = False
        for query_id in {row.query_id for row
                         in ev._population(golden_db, batch_scope, "previous").organic_rows()}:
            result = ev.response_details(golden_db, batch_scope, "previous", query_id)
            for row in result["responses"]:
                if row["response_text_truncated"]:
                    assert len(row["response_text"]) == ev.RESPONSE_TEXT_LIMIT
                    found = True
        assert found, "the long fixture body should have been truncated somewhere"

    def test_filters_by_platform(self, golden_db, batch_scope):
        result = ev.response_details(golden_db, batch_scope, "previous", "Q001",
                                     platform="ChatGPT")
        assert all(r["platform"] == "ChatGPT" for r in result["responses"])

    def test_rejects_an_unknown_side(self, golden_db, batch_scope):
        with pytest.raises(sc.ScopeError):
            ev.response_details(golden_db, batch_scope, "sideways", "Q001")


class TestCompetitorChanges:
    def test_brand_share_matches_canonical(self, golden_db, batch_scope):
        result = ev.competitor_changes(golden_db, batch_scope)
        assert result["brand"]["previous"]["value"] == gx.B1_SHARE_OF_VOICE

    def test_competitor_shares_match_canonical(self, golden_db, batch_scope):
        result = ev.competitor_changes(golden_db, batch_scope)
        previous = {r["organization"]: r["previous"]["value"]
                    for r in result["competitors"]
                    if r["previous"]["numerator"]}
        assert previous == gx.B1_COMPETITOR_SHARE_OF_VOICE

    def test_a_competitor_absent_from_one_window_is_a_change_not_an_unknown(
            self, golden_db, batch_scope):
        """February has no competitor mentions at all. Reporting None would hide
        exactly the case worth investigating."""
        result = ev.competitor_changes(golden_db, batch_scope)
        mit = next(r for r in result["competitors"] if r["organization"] == "MIT")
        assert mit["current"]["value"] == 0.0
        assert mit["change"] == pytest.approx(-gx.B1_COMPETITOR_SHARE_OF_VOICE["MIT"], abs=0.1)


class TestDescriptorChanges:
    def test_match_rate_matches_canonical(self, golden_db, batch_scope):
        result = ev.descriptor_changes(golden_db, batch_scope)
        assert (result["target_match_rate"]["previous"]["value"]
                == gx.B1_DESCRIPTOR_MATCH_RATE)

    def test_counts_are_case_folded(self, golden_db, batch_scope):
        result = ev.descriptor_changes(golden_db, batch_scope)
        counts = {r["descriptor"]: r["previous"] for r in result["descriptors"]}
        assert counts["high-temperature plasma"] == 5

    def test_names_the_targets_that_were_never_used(self, golden_db, batch_scope):
        result = ev.descriptor_changes(golden_db, batch_scope)
        assert "ai-driven" in result["unmatched_targets"]


class TestHistoricalTrend:
    def test_oldest_first(self, golden_db, batch_scope):
        result = ev.historical_trend(golden_db, batch_scope, count=5)
        assert result["points"]
        labels = [p["label"] for p in result["points"]]
        assert labels == ["January 2026", "February 2026"]

    def test_reports_counted_responses_so_empty_windows_are_visible(
            self, golden_db, batch_scope):
        result = ev.historical_trend(golden_db, batch_scope, count=5)
        assert all("counted_responses" in point for point in result["points"])
        assert any("must not be read as a metric collapse" in result["note"] for _ in [0])


class TestTenantIsolation:
    def test_scope_only_sees_its_own_brands_batches(self, golden_db):
        """The canary brand has exactly one batch. If scope resolution leaked
        across brands it would find brand 1's batches to compare against."""
        with pytest.raises(sc.ScopeError, match="earliest collection"):
            sc.build_batch_scope(golden_db, USER_2_ID, BRAND_2_ID)

    def test_evidence_never_crosses_brands(self, golden_db, batch_scope):
        """Every query in the pack filters user_id AND brand_id, so brand 1's
        evidence contains none of the canary brand's rows."""
        context = ev.brand_context(golden_db, batch_scope)
        assert context["brand_name"] == "Golden Labs"

        result = ev.compare_scopes(golden_db, batch_scope)
        assert result["previous"]["mention_rate"]["denominator"] == gx.B1_POPULATION

        details = ev.response_details(golden_db, batch_scope, "previous", "Q001")
        owned = {
            row.id for row in golden_db.query(
                __import__("app.models", fromlist=["models"]).Response
            ).filter_by(user_id=USER_1_ID, brand_id=BRAND_1_ID).all()
        }
        assert all(r["response_id"] in owned for r in details["responses"])


class TestEvidenceIsDeterministic:
    def test_repeated_calls_return_identical_output(self, golden_db, batch_scope):
        """Everything here must be reproducible; an investigation that cannot be
        re-derived cannot be audited."""
        import json
        first = json.dumps(ev.compare_scopes(golden_db, batch_scope), sort_keys=True)
        second = json.dumps(ev.compare_scopes(golden_db, batch_scope), sort_keys=True)
        assert first == second

    def test_every_registered_tool_is_callable(self):
        assert set(ev.EVIDENCE_TOOLS) == {
            "brand_context", "compare_scopes", "query_level_deltas",
            "platform_breakdown", "response_details", "competitor_changes",
            "descriptor_changes", "historical_trend",
        }
        assert all(callable(fn) for fn in ev.EVIDENCE_TOOLS.values())
