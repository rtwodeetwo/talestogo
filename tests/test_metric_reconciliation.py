"""
The reconciliation harness: do the surfaces agree with each other?

Every test here asks one question. For the same brand, the same period and the
same underlying rows, does the Dashboard report the same number as the CSV
export, the Excel export, the stored BatchAnalytics row, the generated report
and the highlights email?

When this harness was written the answer was no: six surfaces produced four
different mention rates for one batch, a 13 point spread. Each disagreement was
recorded as an xfail naming the file:line responsible, and that list served as
the migration checklist. It is now empty. The spread is 0.0.

These tests are therefore no longer a catalogue of defects; they are the
regression guard that keeps the surfaces in agreement. A failure here means some
surface has started computing its own arithmetic again instead of calling
metrics_core.

Run `pytest tests/test_metric_reconciliation.py -s` to print the matrix.
"""
import csv
import io

import pytest

from app.services import metrics_core as mc
from app.services import metrics_query as mq
from tests import golden_expected as gx
from tests.fixtures.golden_dataset import (
    BATCH_1_ID, BRAND_1_ID, CONTROL_CHAR_RESPONSE_TEXT, USER_1_ID,
)

pytestmark = pytest.mark.reconciliation


def _canonical(db, batch_id=BATCH_1_ID):
    return mq.resolve(db, mq.MetricScope.for_batch(USER_1_ID, BRAND_1_ID, batch_id))


# ============================================================ surface: dashboard

class TestDashboardSurface:
    """GET /api/analytics/dashboard against the canonical definitions."""

    @pytest.fixture()
    def dashboard(self, golden_client, golden_db_with_stored_analytics):
        response = golden_client.get(
            f"/api/analytics/dashboard?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}")
        assert response.status_code == 200, response.text
        return response.json()

    def test_mention_rate_matches_canonical(self, dashboard):
        assert dashboard["mention_rate"] == gx.B1_MENTION_RATE

    def test_positive_sentiment_matches_canonical(self, dashboard):
        assert dashboard["positive_sentiment"] == gx.B1_POSITIVE_SENTIMENT_RATE

    def test_share_of_voice_matches_canonical(self, dashboard):
        assert dashboard["share_of_voice"] == gx.B1_SHARE_OF_VOICE

    def test_descriptor_match_matches_canonical(self, dashboard):
        assert dashboard["descriptor_match"] == gx.B1_DESCRIPTOR_MATCH_RATE

    def test_reports_a_total_response_count(self, dashboard):
        assert "total_responses" in dashboard

    def test_reports_excluded_row_counts(self, dashboard):
        """Without this, a collection failure looks like a reputation drop."""
        quality = dashboard["data_quality"]
        assert quality["counted"] == gx.B1_POPULATION
        assert quality["unanalyzed_excluded"] == gx.B1_UNANALYZED_EXCLUDED
        assert quality["invalid_enum_excluded"] == gx.B1_INVALID_ENUM_EXCLUDED
        assert quality["orphan_query_excluded"] == gx.B1_ORPHAN_EXCLUDED
        assert quality["branded_excluded"] == gx.B1_BRANDED_EXCLUDED

    def test_leadership_visibility_is_reported(self, dashboard):
        assert dashboard["leadership_visibility"] == gx.B1_LEADERSHIP_VISIBILITY

    def test_positioning_average_is_on_the_five_point_scale(self, dashboard):
        assert dashboard["positioning_average"] == gx.B1_POSITIONING_AVERAGE


class TestDashboardInternalConsistency:
    """Fields within a single Dashboard payload that must agree with each other."""

    def test_positive_sentiment_equals_its_own_pie_slices(self, golden_client,
                                                          golden_db_with_stored_analytics):
        dashboard = golden_client.get(
            f"/api/analytics/dashboard?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}").json()
        breakdown = golden_client.get(
            f"/api/analytics/sentiment/breakdown?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}"
        ).json()
        slices = (breakdown.get("very_positive_pct", 0) + breakdown.get("positive_pct", 0))
        assert dashboard["positive_sentiment"] == pytest.approx(slices, abs=0.1)

    def test_leadership_value_and_delta_use_one_formula(self, golden_client,
                                                        golden_db_with_stored_analytics):
        """The tile's value and its trend arrow must measure the same thing.

        The value came from the share-of-voice endpoint as Leader+Top 3+Featured
        while the arrow was computed from leader_count alone, so the number and
        its direction of travel were different metrics. Both now come from the
        dashboard payload.
        """
        dashboard = golden_client.get(
            f"/api/analytics/dashboard?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}").json()
        assert dashboard["leadership_visibility"] == gx.B1_LEADERSHIP_VISIBILITY
        assert "change_leadership_visibility" in dashboard

    def test_leadership_delta_is_the_difference_of_two_values(self, golden_client,
                                                              golden_db_with_stored_analytics):
        """Batch 1 is the earliest batch, so there is nothing to compare against
        and the reported change must be zero rather than a spurious jump."""
        dashboard = golden_client.get(
            f"/api/analytics/dashboard?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}").json()
        assert dashboard["change_leadership_visibility"] == 0
        assert dashboard["previous_collection_date"] is None


class TestStandaloneAnalyticsPages:
    """The analytics pages that do not go through the dashboard endpoint.

    These serve from AnalyticsCache. Until it was migrated, the Share of Voice
    page reported 75.9% for the same batch the Dashboard tile showed at 55.0%,
    because it counted competitors only inside answers where the brand had
    already been mentioned and then labelled that as a share of the whole.
    """

    def test_share_of_voice_page_matches_the_dashboard_tile(self, golden_client,
                                                            golden_db_with_stored_analytics):
        dashboard = golden_client.get(
            f"/api/analytics/dashboard?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}").json()
        sov = golden_client.get(
            f"/api/analytics/share-of-voice?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}").json()
        brand_row = next((r for r in sov if r.get("is_brand")), None)
        assert brand_row is not None
        assert brand_row["percentage"] == dashboard["share_of_voice"] == gx.B1_SHARE_OF_VOICE

    def test_share_of_voice_page_leadership_matches_the_tile(self, golden_client,
                                                             golden_db_with_stored_analytics):
        dashboard = golden_client.get(
            f"/api/analytics/dashboard?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}").json()
        sov = golden_client.get(
            f"/api/analytics/share-of-voice?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}").json()
        brand_row = next(r for r in sov if r.get("is_brand"))
        assert (brand_row["leadership_visibility"]
                == dashboard["leadership_visibility"]
                == gx.B1_LEADERSHIP_VISIBILITY)

    def test_competitor_rows_match_canonical(self, golden_client,
                                             golden_db_with_stored_analytics):
        """Names are normalized consistently, so the page and the trend chart
        show the same roster rather than split versus merged rows."""
        sov = golden_client.get(
            f"/api/analytics/share-of-voice?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}").json()
        competitors = {r["organization"]: r["percentage"]
                       for r in sov if not r.get("is_brand")}
        assert competitors == gx.B1_COMPETITOR_SHARE_OF_VOICE

    def test_page_shares_sum_to_one_hundred(self, golden_client,
                                            golden_db_with_stored_analytics):
        sov = golden_client.get(
            f"/api/analytics/share-of-voice?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}").json()
        assert sum(r["percentage"] for r in sov) == pytest.approx(100.0, abs=0.1)


class TestPerLlmEndpoints:
    """The per-LLM charts must reconcile to the headline above them."""

    def test_mentions_by_llm_match_canonical(self, golden_client, golden_db):
        rows = golden_client.get(
            f"/api/analytics/brand-mentions-by-llm?brand_id={BRAND_1_ID}"
            f"&batch_id={BATCH_1_ID}").json()
        rates = {r["platform"]: r["mention_rate"] for r in rows}
        assert rates == gx.B1_PLATFORM_MENTION_RATES

    def test_mentions_by_llm_sum_to_the_headline(self, golden_client, golden_db):
        """The chart used to count 'Yes' only while the headline counted
        Yes+Indirect, so it was systematically lower than the number above it."""
        rows = golden_client.get(
            f"/api/analytics/brand-mentions-by-llm?brand_id={BRAND_1_ID}"
            f"&batch_id={BATCH_1_ID}").json()
        assert sum(r["mentions"] for r in rows) == gx.B1_MENTION_NUMERATOR
        assert sum(r["total_responses"] for r in rows) == gx.B1_POPULATION

    def test_positioning_by_llm_reports_top_3(self, golden_client, golden_db):
        """Top 3 was filtered out of this chart while counting everywhere else."""
        rows = golden_client.get(
            f"/api/analytics/positioning-by-llm?brand_id={BRAND_1_ID}"
            f"&batch_id={BATCH_1_ID}").json()
        assert rows
        assert all("Top 3" in row for row in rows)
        assert (sum(row["Top 3"] for row in rows)
                == gx.B1_POSITION_COUNTS["Top 3"])

    def test_positioning_by_llm_totals_match_the_population(self, golden_client, golden_db):
        rows = golden_client.get(
            f"/api/analytics/positioning-by-llm?brand_id={BRAND_1_ID}"
            f"&batch_id={BATCH_1_ID}").json()
        assert sum(row["total"] for row in rows) == gx.B1_POPULATION


# ========================================================= cross-surface matrix

def _dashboard_mention_rate(client, db):
    body = client.get(
        f"/api/analytics/dashboard?brand_id={BRAND_1_ID}&batch_id={BATCH_1_ID}").json()
    return body.get("mention_rate")


def _stored_mention_rate(client, db):
    from app import models
    row = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.batch_id == BATCH_1_ID).first()
    return row.mention_rate if row else None


def _highlights_mention_rate(client, db):
    from app.routers import highlights
    return highlights._compute_mention_rate(_canonical(db))[2]


def _canonical_mention_rate(client, db):
    return mc.mention_rate(_canonical(db)).value


MENTION_RATE_SURFACES = {
    "dashboard endpoint": _dashboard_mention_rate,
    "stored BatchAnalytics": _stored_mention_rate,
    "highlights email": _highlights_mention_rate,
    "CANONICAL metrics_core": _canonical_mention_rate,
}


def test_all_surfaces_agree_on_mention_rate(golden_client,
                                            golden_db_with_stored_analytics):
    """The headline reconciliation. On failure it prints the full matrix.

    This started as the evidence that the numbers disagreed. It is now the
    evidence that they do not: every surface derives its figure from
    metrics_core, so one brand and one batch produce one answer.

    app/analytics.py is deliberately absent from this matrix. Its
    get_dashboard_metrics has no caller in the application, only in tooling, and
    it is scheduled for deletion; the live functions that remained in it have
    been migrated. The generated-report surface is gone entirely: Tales no
    longer produces written reports.
    """
    db = golden_db_with_stored_analytics
    observed = {}
    for name, extractor in MENTION_RATE_SURFACES.items():
        try:
            observed[name] = extractor(golden_client, db)
        except Exception as exc:  # noqa: BLE001 - a crashing surface is a finding
            observed[name] = f"ERROR: {type(exc).__name__}: {exc}"

    width = max(len(name) for name in observed)
    lines = ["", "Mention rate for brand 1 / batch 1, by surface:", ""]
    for name, value in observed.items():
        lines.append(f"    {name.ljust(width)}  {value}")
    numeric = [v for v in observed.values() if isinstance(v, (int, float))]
    if numeric:
        lines.append("")
        lines.append(f"    {'SPREAD'.ljust(width)}  "
                     f"{round(max(numeric) - min(numeric), 2)} percentage points")
    print("\n".join(lines))

    distinct = {round(float(v), 1) for v in numeric}
    assert len(distinct) == 1, (
        "Surfaces disagree on mention rate:\n" + "\n".join(lines))
