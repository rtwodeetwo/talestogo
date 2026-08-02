"""
Bind app/services/metrics_core.py to the hand-derived contract in golden_expected.py.

These are the tests that say what each metric MEANS. If one fails, either the
implementation drifted or someone changed a definition without changing the
documented arithmetic. Both are things you want to hear about.
"""
import pytest

from app.services import metrics_core as mc
from app.services import metrics_query as mq
from tests import golden_expected as gx
from tests.fixtures.golden_dataset import (
    BATCH_1_ID, BATCH_2_ID, BATCH_3_ID, BRAND_1_ID, BRAND_2_ID,
    USER_1_ID, USER_2_ID,
)


@pytest.fixture()
def batch1(golden_db):
    return mq.resolve(golden_db, mq.MetricScope.for_batch(USER_1_ID, BRAND_1_ID, BATCH_1_ID))


@pytest.fixture()
def batch2(golden_db):
    return mq.resolve(golden_db, mq.MetricScope.for_batch(USER_1_ID, BRAND_1_ID, BATCH_2_ID))


def _values(mapping):
    return {key: metric.value for key, metric in mapping.items()}


class TestPopulation:
    def test_population_is_forty(self, batch1):
        assert len(batch1.organic_rows()) == gx.B1_POPULATION

    def test_nothing_is_dropped_before_the_metrics_see_it(self, batch1):
        assert len(batch1.rows) == gx.B1_TOTAL_ROWS

    def test_exclusions_are_reported_not_hidden(self, batch1):
        quality = mc.data_quality(batch1)
        assert quality["counted"] == gx.B1_POPULATION
        assert quality["branded_excluded"] == gx.B1_BRANDED_EXCLUDED
        assert quality["unanalyzed_excluded"] == gx.B1_UNANALYZED_EXCLUDED
        assert quality["invalid_enum_excluded"] == gx.B1_INVALID_ENUM_EXCLUDED
        assert quality["orphan_query_excluded"] == gx.B1_ORPHAN_EXCLUDED

    def test_exclusions_account_for_every_row(self, batch1):
        quality = mc.data_quality(batch1)
        accounted = (quality["counted"] + quality["branded_excluded"]
                     + quality["unanalyzed_excluded"] + quality["invalid_enum_excluded"]
                     + quality["orphan_query_excluded"])
        assert accounted == quality["total_rows"]


class TestMentionRate:
    def test_matches_golden(self, batch1):
        result = mc.mention_rate(batch1)
        assert result.value == gx.B1_MENTION_RATE
        assert result.numerator == gx.B1_MENTION_NUMERATOR
        assert result.denominator == gx.B1_POPULATION

    def test_direct_only_excludes_indirect(self, batch1):
        assert mc.direct_mention_rate(batch1).value == gx.B1_DIRECT_MENTION_RATE

    def test_unanalyzed_rows_are_not_counted_as_not_mentioned(self, batch1):
        """The single most consequential fix: a parse failure is not a verdict."""
        result = mc.mention_rate(batch1)
        assert result.denominator == gx.B1_POPULATION
        assert result.detail["excluded_unanalyzed"] == gx.B1_UNANALYZED_EXCLUDED

    def test_off_enum_value_is_excluded_not_treated_as_no(self, batch1):
        """"Probably" must not silently become a denominator row."""
        assert mc.mention_rate(batch1).detail["excluded_invalid"] == 1

    def test_empty_population_returns_none_not_zero(self):
        empty = mc.MetricPopulation()
        assert mc.mention_rate(empty).value is None


class TestSentiment:
    def test_positive_rate_matches_golden(self, batch1):
        result = mc.positive_sentiment_rate(batch1)
        assert result.value == gx.B1_POSITIVE_SENTIMENT_RATE
        assert result.denominator == gx.B1_SENTIMENT_POPULATION

    def test_distribution_matches_golden(self, batch1):
        assert _values(mc.sentiment_distribution(batch1)) == gx.B1_SENTIMENT_DISTRIBUTION

    def test_slices_sum_to_one_hundred(self, batch1):
        """Fails today on every cached_metrics.py:97-102 sentiment trend chart."""
        total = sum(v.value for v in mc.sentiment_distribution(batch1).values())
        assert total == pytest.approx(100.0, abs=0.1)

    def test_headline_equals_its_own_slices(self, batch1):
        """The Dashboard card and the pie beneath it must not disagree."""
        distribution = mc.sentiment_distribution(batch1)
        headline = mc.positive_sentiment_rate(batch1).value
        slices = distribution["Very Positive"].value + distribution["Positive"].value
        assert headline == pytest.approx(slices, abs=0.1)

    def test_denominator_and_numerator_share_a_population(self, batch1):
        """Guards the Yes-over-(Yes+Indirect) mismatch at analytics_cache.py:208."""
        result = mc.positive_sentiment_rate(batch1)
        direct_with_sentiment = [
            r for r in batch1.analyzed_rows()
            if r.is_direct_mention and r.sentiment in mc.SENTIMENT_VALUES
        ]
        assert result.denominator == len(direct_with_sentiment)


class TestPositioning:
    def test_distribution_matches_golden(self, batch1):
        assert _values(mc.positioning_distribution(batch1)) == gx.B1_POSITION_DISTRIBUTION

    def test_top_3_is_reported_not_dropped(self, batch1):
        """batch_analytics.py:98-103 and routers/analytics.py:801 drop this value."""
        assert mc.positioning_distribution(batch1)["Top 3"].value == 5.0
        assert mc.positioning_distribution(batch1)["Top 3"].numerator == 2

    def test_counts_sum_to_the_population(self, batch1):
        distribution = mc.positioning_distribution(batch1)
        assert sum(v.numerator for v in distribution.values()) == gx.B1_POPULATION

    def test_leadership_visibility_matches_golden(self, batch1):
        assert mc.leadership_visibility(batch1).value == gx.B1_LEADERSHIP_VISIBILITY

    def test_leadership_visibility_includes_top_3_and_featured(self, batch1):
        """The value and its trend arrow must be the same formula."""
        result = mc.leadership_visibility(batch1)
        expected = sum(gx.B1_POSITION_COUNTS[p] for p in mc.LEADERSHIP_POSITIONS)
        assert result.numerator == expected

    def test_average_matches_golden(self, batch1):
        result = mc.positioning_average(batch1)
        assert result.value == gx.B1_POSITIONING_AVERAGE
        assert result.numerator == gx.B1_POSITIONING_SCORE_TOTAL

    def test_top_3_scores_above_listed(self):
        """POSITION_SCORES had no "Top 3" key, so .get(pos, 1) scored it as 1."""
        assert mc.POSITION_SCORES["Top 3"] == 4
        assert mc.POSITION_SCORES["Top 3"] > mc.POSITION_SCORES["Listed"]
        assert mc.POSITION_SCORES["Top 3"] < mc.POSITION_SCORES["Leader"]

    def test_scale_is_one_to_five(self):
        assert min(mc.POSITION_SCORES.values()) == 1
        assert max(mc.POSITION_SCORES.values()) == 5


class TestShareOfVoice:
    def test_brand_share_matches_golden(self, batch1):
        brand_share, _ = mc.share_of_voice(batch1)
        assert brand_share.value == gx.B1_SHARE_OF_VOICE

    def test_competitor_shares_match_golden(self, batch1):
        _, competitors = mc.share_of_voice(batch1)
        assert _values(competitors) == gx.B1_COMPETITOR_SHARE_OF_VOICE

    def test_competitors_counted_across_all_organic_answers(self, batch1):
        """Not only within answers where the brand was already mentioned.

        analytics_cache.py:327-336 applies that restriction and then labels the
        result as a share of the whole corpus, inflating brand share.
        """
        _, competitors = mc.share_of_voice(batch1)
        counts = {name: metric.numerator for name, metric in competitors.items()}
        assert counts == gx.B1_COMPETITOR_MENTION_COUNTS

    def test_shares_sum_to_one_hundred(self, batch1):
        brand_share, competitors = mc.share_of_voice(batch1)
        total = brand_share.value + sum(c.value for c in competitors.values())
        assert total == pytest.approx(100.0, abs=0.1)

    def test_no_top_n_truncation(self, batch1):
        """metrics.py:563 truncates to top 5 before threat scoring."""
        _, competitors = mc.share_of_voice(batch1)
        assert len(competitors) == len(gx.B1_COMPETITOR_MENTION_COUNTS)


class TestNormalization:
    def test_substring_trap_is_gone(self):
        """metrics.py:79 rewrote anything containing "step" to "UKAEA"."""
        assert mc.normalize_organization("Stepwise Analytics") == "Stepwise Analytics"
        assert mc.normalize_organization("STEP") == "STEP"

    def test_alias_map_is_explicit_and_exact(self):
        aliases = {"step": "UKAEA", "mast-u": "UKAEA"}
        assert mc.normalize_organization("STEP", aliases) == "UKAEA"
        assert mc.normalize_organization("MAST-U", aliases) == "UKAEA"
        assert mc.normalize_organization("Stepwise Analytics", aliases) == "Stepwise Analytics"

    def test_descriptors_fold_case_but_not_punctuation(self):
        assert mc.normalize_descriptor("High-Temperature Plasma") == "high-temperature plasma"
        assert mc.normalize_descriptor("  innovative  ") == "innovative"
        assert mc.normalize_descriptor("High Temperature Plasma") != "high-temperature plasma"


class TestDescriptors:
    def test_match_rate_matches_golden(self, batch1):
        result = mc.descriptor_match_rate(batch1)
        assert result.value == gx.B1_DESCRIPTOR_MATCH_RATE
        assert sorted(result.detail["matched"]) == sorted(gx.B1_DESCRIPTOR_MATCHED)

    def test_denominator_is_target_descriptors_only(self, batch1):
        """app/analytics.py:110 uses every descriptor row, ignoring is_target."""
        assert mc.descriptor_match_rate(batch1).denominator == 3

    def test_no_substring_matching(self, batch1):
        """analytics_cache.py:283 matches bidirectionally, inflating the rate."""
        result = mc.descriptor_match_rate(batch1)
        assert "ai-driven" in result.detail["unmatched"]

    def test_frequency_folds_case(self, batch1):
        assert mc.descriptor_frequency(batch1) == gx.B1_DESCRIPTOR_FREQUENCY


class TestQueries:
    def test_per_query_rates_use_the_headline_definition(self, batch1):
        rates = mc.query_mention_rates(batch1)
        headline = mc.mention_rate(batch1)
        assert sum(r.numerator for r in rates.values()) == headline.numerator
        assert sum(r.denominator for r in rates.values()) == headline.denominator

    def test_branded_queries_are_absent(self, batch1):
        """A branded query measures nothing about organic visibility."""
        assert not any(q.startswith("QB") for q in mc.query_mention_rates(batch1))

    def test_carries_the_query_text(self, batch1):
        rates = mc.query_mention_rates(batch1)
        assert all(r.detail.get("query_text") for r in rates.values())


class TestPlatforms:
    def test_per_platform_rates_match_golden(self, batch1):
        assert _values(mc.platform_mention_rates(batch1)) == gx.B1_PLATFORM_MENTION_RATES

    def test_platform_rates_use_the_headline_definition(self, batch1):
        """routers/analytics.py:739 counts Yes only, so the per-LLM chart sits
        under a headline it can never reconcile with."""
        rates = mc.platform_mention_rates(batch1)
        headline = mc.mention_rate(batch1)
        assert sum(r.numerator for r in rates.values()) == headline.numerator
        assert sum(r.denominator for r in rates.values()) == headline.denominator


class TestTenantIsolation:
    def test_brand_1_is_unaffected_by_brand_2(self, batch1):
        assert mc.mention_rate(batch1).value == gx.B1_MENTION_RATE

    def test_canary_brand_reads_only_its_own_rows(self, golden_db):
        pop = mq.resolve(golden_db, mq.MetricScope.for_batch(USER_2_ID, BRAND_2_ID, BATCH_3_ID))
        assert len(pop.organic_rows()) == gx.B3_POPULATION
        assert mc.mention_rate(pop).value == gx.B3_MENTION_RATE

    def test_wrong_owner_sees_nothing(self, golden_db):
        """Both user_id and brand_id are always filtered."""
        pop = mq.resolve(golden_db, mq.MetricScope.for_batch(USER_2_ID, BRAND_1_ID, BATCH_1_ID))
        assert pop.rows == []


class TestPeriodScoping:
    """One batch, three windows, three different "February 2026"."""

    def test_by_batch(self, batch2):
        result = mc.mention_rate(batch2)
        assert result.value == gx.B2_MENTION_RATE_BY_BATCH
        assert result.denominator == gx.B2_POPULATION_BY_BATCH

    def test_eastern_february(self, golden_db):
        start, end = mq.month_bounds(2026, 2, "America/New_York")
        pop = mq.resolve(golden_db, mq.MetricScope(USER_1_ID, BRAND_1_ID, start=start, end=end))
        result = mc.mention_rate(pop)
        assert result.value == gx.B2_MENTION_RATE_EASTERN_FEB
        assert result.denominator == gx.B2_POPULATION_EASTERN_FEB

    def test_utc_february(self, golden_db):
        start, end = mq.utc_month_bounds(2026, 2)
        pop = mq.resolve(golden_db, mq.MetricScope(USER_1_ID, BRAND_1_ID, start=start, end=end))
        result = mc.mention_rate(pop)
        assert result.value == gx.B2_MENTION_RATE_UTC_FEB
        assert result.denominator == gx.B2_POPULATION_UTC_FEB

    def test_the_three_windows_genuinely_disagree(self, golden_db, batch2):
        """Documents the bug rather than asserting it away.

        The UI renders Eastern (frontend/src/utils/dateUtils.ts:19) while every
        period boundary is naive UTC (period_ranges.py:87-91), so the month the
        user reads about is not the month the app measured.
        """
        eastern_start, eastern_end = mq.month_bounds(2026, 2, "America/New_York")
        utc_start, utc_end = mq.utc_month_bounds(2026, 2)
        eastern = mc.mention_rate(mq.resolve(
            golden_db, mq.MetricScope(USER_1_ID, BRAND_1_ID, start=eastern_start, end=eastern_end)))
        utc = mc.mention_rate(mq.resolve(
            golden_db, mq.MetricScope(USER_1_ID, BRAND_1_ID, start=utc_start, end=utc_end)))
        by_batch = mc.mention_rate(batch2)
        assert len({eastern.value, utc.value, by_batch.value}) == 3

    def test_windows_are_half_open(self):
        """[start, end). period_ranges.month_bounds ends at 23:59:59 with <=,
        dropping the final sub-second of every period."""
        _, jan_end = mq.month_bounds(2026, 1, "America/New_York")
        feb_start, _ = mq.month_bounds(2026, 2, "America/New_York")
        assert jan_end == feb_start
