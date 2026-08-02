"""
Structural guards that stop the duplication from growing back.

The August 2026 audit found nine mention-rate implementations. None of them was
added maliciously; each was a reasonable local decision by someone who did not
know the other eight existed. Consolidating once fixes today. These tests are
what fix next year.

Three mechanisms:

1. Purity      -- metrics_core cannot reach for a database or a clock, so it
                  cannot quietly grow a second population-selection rule.
2. Inline math -- new percentage arithmetic outside metrics_core fails CI. The
                  allowlist starts at today's count and only ever shrinks.
3. Invariants  -- properties that must hold for ANY population, which catch the
                  whole 'Top 3' class of bug generically rather than one value
                  at a time.
"""
import ast
import os
import re

import pytest

from app.services import metrics_core as mc
from app.services import metrics_query as mq
from tests.fixtures.golden_dataset import (
    BATCH_1_ID, BATCH_2_ID, BRAND_1_ID, USER_1_ID,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METRICS_CORE_PATH = os.path.join(REPO_ROOT, "app", "services", "metrics_core.py")


# =========================================================== 1. purity

#: metrics_core must not be able to select rows or read a clock. If it could,
#: "the canonical definition" would once again depend on where it was called
#: from, which is the root cause this whole effort exists to remove.
FORBIDDEN_IMPORTS = ("sqlalchemy", "app.models", "app.database", "app.crud")
FORBIDDEN_CALLS = ("utcnow", "now", "today")


def _core_ast():
    with open(METRICS_CORE_PATH, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=METRICS_CORE_PATH)


class TestMetricsCorePurity:
    def test_imports_no_database_machinery(self):
        offenders = []
        for node in ast.walk(_core_ast()):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if any(name == bad or name.startswith(bad + ".")
                       for bad in FORBIDDEN_IMPORTS):
                    offenders.append(f"line {node.lineno}: {name}")
        assert not offenders, (
            "metrics_core must stay pure arithmetic. Row selection belongs in "
            f"metrics_query. Found: {offenders}")

    def test_reads_no_clock(self):
        offenders = [
            f"line {node.lineno}: {node.func.attr}()"
            for node in ast.walk(_core_ast())
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in FORBIDDEN_CALLS
        ]
        assert not offenders, (
            "metrics_core must not depend on the current time; a metric that "
            f"changes when you run it cannot be reconciled. Found: {offenders}")

    def test_every_public_metric_is_documented(self):
        """docs/METRIC_DEFINITIONS.md is generated from these docstrings."""
        undocumented = [
            fn.__name__ for fn in mc.RATE_METRICS.values() if not (fn.__doc__ or "").strip()
        ]
        assert not undocumented

    def test_every_rate_metric_states_its_population(self):
        """A definition without a stated denominator is how this started."""
        for name, fn in mc.RATE_METRICS.items():
            doc = (fn.__doc__ or "").lower()
            assert "denominator" in doc or "population" in doc, (
                f"{name} must document what it divides by")


# ====================================================== 2. inline metric math

#: Percentage arithmetic anywhere but metrics_core is how a tenth implementation
#: gets written. Every entry is a site that still computes a rate for itself.
#: The list may shrink. It may never grow.
#:
#: Started at 23 entries. Ten came off when the dashboard, the per-LLM endpoints,
#: BatchAnalytics, the report generator, the exports and the highlights email
#: were migrated. What remains is the legacy modules scheduled for deletion, the
#: surfaces still to migrate, and tooling that reports on the old code by design.
INLINE_MATH_ALLOWLIST = {
    # Legacy metric modules. Superseded by metrics_core; kept importable so
    # metric_baseline.py can show the contrast. Scheduled for deletion.
    "app/analytics.py",
    "app/services/metrics.py",
    # Still to migrate.
    "app/routers/admin.py",
    "app/routers/highlights.py",     # per-query rates only; the metrics are migrated
    "app/services/analytics_cache.py",  # trends and threats remain
    "app/services/cached_metrics.py",   # reads BatchAnalytics columns directly
    "scripts/admin/generate_report.py",  # narrative sections beyond period metrics
    "scripts/admin/analyze_responses.py",
    "scripts/admin/collect_responses.py",
    # Reports on the legacy implementations by design.
    "scripts/admin/metric_baseline.py",
    # Demo and debug tooling rather than app metrics. Flagged separately: the
    # first two generate randomized, backdated data and write it to whatever
    # DATABASE_URL points at.
    "scripts/generate_fake_trend_data.py",
    "scripts/data/seed_historical_data.py",
    "scripts/admin/debug_leadership.py",
}

#: `x / y * 100`, `100.0 * x / y`, `(a / b) * 100` and friends.
_PERCENT_MATH = re.compile(r"(/[^/\n]{1,60}\*\s*100|100(\.0)?\s*\*[^\n]{1,60}/)")


def _python_sources():
    for root_name in ("app", "scripts"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(REPO_ROOT, root_name)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for filename in filenames:
                if filename.endswith(".py"):
                    absolute = os.path.join(dirpath, filename)
                    yield os.path.relpath(absolute, REPO_ROOT).replace(os.sep, "/"), absolute


class TestNoNewInlineMetricMath:
    def test_percentage_math_only_in_metrics_core_or_allowlist(self):
        offenders = []
        for relative, absolute in _python_sources():
            if relative in INLINE_MATH_ALLOWLIST:
                continue
            if relative == "app/services/metrics_core.py":
                continue
            with open(absolute, encoding="utf-8") as handle:
                for number, line in enumerate(handle, start=1):
                    if line.lstrip().startswith("#"):
                        continue
                    if _PERCENT_MATH.search(line):
                        offenders.append(f"{relative}:{number}: {line.strip()}")
        assert not offenders, (
            "New percentage arithmetic outside metrics_core. Call the canonical "
            "metric instead of computing a rate here:\n  " + "\n  ".join(offenders))

    def test_allowlist_has_no_stale_entries(self):
        """As Phase 3 migrates a file, its entry must come off the list."""
        present = {relative for relative, _ in _python_sources()}
        stale = sorted(INLINE_MATH_ALLOWLIST - present)
        assert not stale, (
            f"Allowlist names files that no longer exist: {stale}. "
            "Remove them so the list keeps shrinking.")


# ============================================================== 3. invariants

@pytest.fixture(params=[BATCH_1_ID, BATCH_2_ID])
def population(request, golden_db):
    return mq.resolve(
        golden_db, mq.MetricScope.for_batch(USER_1_ID, BRAND_1_ID, request.param))


class TestInvariants:
    """Properties that must hold for ANY population, not just the fixture."""

    def test_sentiment_slices_sum_to_one_hundred(self, population):
        distribution = mc.sentiment_distribution(population)
        values = [v.value for v in distribution.values() if v.value is not None]
        if not values:
            pytest.skip("no sentiment-bearing rows")
        assert sum(values) == pytest.approx(100.0, abs=0.1)

    def test_positioning_slices_sum_to_one_hundred(self, population):
        distribution = mc.positioning_distribution(population)
        values = [v.value for v in distribution.values() if v.value is not None]
        if not values:
            pytest.skip("empty population")
        assert sum(values) == pytest.approx(100.0, abs=0.1)

    def test_positioning_counts_sum_to_the_population(self, population):
        """Catches the 'Top 3' class of bug generically.

        batch_analytics.py:98-103 buckets only Leader/Featured/Listed, so its
        counts silently fail to add up.
        """
        distribution = mc.positioning_distribution(population)
        counted = sum(v.numerator for v in distribution.values())
        assert counted == len(population.organic_rows())

    def test_share_of_voice_sums_to_one_hundred(self, population):
        brand_share, competitors = mc.share_of_voice(population)
        if brand_share.value is None:
            pytest.skip("empty population")
        total = brand_share.value + sum(
            c.value for c in competitors.values() if c.value is not None)
        assert total == pytest.approx(100.0, abs=0.1)

    def test_every_row_is_either_counted_or_explained(self, population):
        quality = mc.data_quality(population)
        accounted = (quality["counted"] + quality["branded_excluded"]
                     + quality["unanalyzed_excluded"] + quality["invalid_enum_excluded"]
                     + quality["orphan_query_excluded"])
        assert accounted == quality["total_rows"], (
            "A row was neither counted nor reported as excluded, which is how an "
            "unanalyzed response comes to be indistinguishable from 'not mentioned'.")

    def test_direct_mentions_never_exceed_all_mentions(self, population):
        assert (mc.direct_mention_rate(population).numerator
                <= mc.mention_rate(population).numerator)

    def test_platform_rates_reconcile_to_the_headline(self, population):
        """A per-LLM chart must add up to the number above it."""
        rates = mc.platform_mention_rates(population)
        headline = mc.mention_rate(population)
        assert sum(r.numerator for r in rates.values()) == headline.numerator
        assert sum(r.denominator for r in rates.values()) == headline.denominator

    def test_positioning_average_lies_within_the_scale(self, population):
        result = mc.positioning_average(population)
        if result.value is None:
            pytest.skip("empty population")
        assert 1.0 <= result.value <= 5.0

    def test_leadership_visibility_matches_its_position_slices(self, population):
        """The tile value and its trend arrow must be one formula.

        On the Dashboard today the value is Leader+Top 3+Featured while the arrow
        is Leader only (routers/analytics.py:266-268).
        """
        distribution = mc.positioning_distribution(population)
        expected = sum(distribution[p].numerator for p in mc.LEADERSHIP_POSITIONS)
        assert mc.leadership_visibility(population).numerator == expected

    def test_no_rate_exceeds_one_hundred(self, population):
        for name, fn in mc.RATE_METRICS.items():
            result = fn(population)
            if result.value is not None:
                assert 0.0 <= result.value <= 100.0, f"{name} = {result.value}"

    def test_empty_populations_report_no_value_rather_than_zero(self):
        empty = mc.MetricPopulation()
        for name, fn in mc.RATE_METRICS.items():
            assert fn(empty).value is None, (
                f"{name} returned a number for an empty population; 'no data' "
                "must be distinguishable from 'genuinely zero'.")
