"""
Unit tests for app/services/period_ranges.py.

These are pure date-math tests: get_period_comparison_ranges takes an
injectable `now`, so no database rows are needed (db/brand_id are only used
to look up the fiscal-year start month, and brand_id=None short-circuits
that lookup to the calendar default).
"""
from datetime import datetime

from app.services.period_ranges import (
    fiscal_quarter_label,
    get_period_comparison_ranges,
    parse_period_start,
)


class TestFiscalQuarterLabel:
    def test_calendar_year(self):
        assert fiscal_quarter_label(1, 1, 2026) == "Q1 2026"
        assert fiscal_quarter_label(1, 4, 2026) == "Q2 2026"
        assert fiscal_quarter_label(1, 7, 2026) == "Q3 2026"
        assert fiscal_quarter_label(1, 10, 2026) == "Q4 2026"

    def test_october_fiscal_year(self):
        # Federal convention: FY named for the calendar year it ends in.
        # FY2026 runs Oct 2025 through Sep 2026.
        assert fiscal_quarter_label(10, 10, 2025) == "FY2026 Q1"
        assert fiscal_quarter_label(10, 1, 2026) == "FY2026 Q2"
        assert fiscal_quarter_label(10, 4, 2026) == "FY2026 Q3"
        assert fiscal_quarter_label(10, 7, 2026) == "FY2026 Q4"
        assert fiscal_quarter_label(10, 10, 2026) == "FY2027 Q1"

    def test_april_fiscal_year(self):
        assert fiscal_quarter_label(4, 4, 2026) == "FY2027 Q1"
        assert fiscal_quarter_label(4, 1, 2026) == "FY2026 Q4"

    def test_july_fiscal_year(self):
        assert fiscal_quarter_label(7, 7, 2026) == "FY2027 Q1"
        assert fiscal_quarter_label(7, 4, 2026) == "FY2026 Q4"


class TestParsePeriodStart:
    def test_valid(self):
        assert parse_period_start("2026-04-01") == datetime(2026, 4, 1)

    def test_valid_with_time_suffix(self):
        assert parse_period_start("2026-04-01T00:00:00") == datetime(2026, 4, 1)

    def test_none_and_invalid(self):
        assert parse_period_start(None) is None
        assert parse_period_start("") is None
        assert parse_period_start("not-a-date") is None


class TestMonthComparisonRanges:
    def test_mid_year(self):
        # On any day in July 2026: June vs May.
        cs, ce, cl, ps, pe, pl = get_period_comparison_ranges(
            None, 1, None, 'month', now=datetime(2026, 7, 6))
        assert cs == datetime(2026, 6, 1, 4, 0)
        assert ce == datetime(2026, 7, 1, 4, 0)
        assert cl == "June 2026"
        assert ps == datetime(2026, 5, 1, 4, 0)
        assert pe == datetime(2026, 6, 1, 4, 0)
        assert pl == "May 2026"

    def test_january_year_rollover(self):
        # In January 2026: December 2025 vs November 2025.
        cs, ce, cl, ps, pe, pl = get_period_comparison_ranges(
            None, 1, None, 'month', now=datetime(2026, 1, 6))
        assert cs == datetime(2025, 12, 1, 5, 0)
        assert ce == datetime(2026, 1, 1, 5, 0)
        assert cl == "December 2025"
        assert ps == datetime(2025, 11, 1, 4, 0)
        assert pl == "November 2025"

    def test_february_rollover(self):
        # In February 2026: January 2026 vs December 2025 (previous crosses the year).
        cs, ce, cl, ps, pe, pl = get_period_comparison_ranges(
            None, 1, None, 'month', now=datetime(2026, 2, 15))
        assert cl == "January 2026"
        assert pl == "December 2025"
        assert pe == datetime(2026, 1, 1, 5, 0)

    def test_pinned_period_start(self):
        # Pinning March 2026 gives March vs February regardless of "now".
        cs, ce, cl, ps, pe, pl = get_period_comparison_ranges(
            None, 1, None, 'month',
            period_start=datetime(2026, 3, 1), now=datetime(2026, 7, 6))
        assert cl == "March 2026"
        assert ce == datetime(2026, 4, 1, 4, 0)
        assert pl == "February 2026"
        assert pe == datetime(2026, 3, 1, 5, 0)


class TestQuarterComparisonRanges:
    def test_mid_year(self):
        # During Q3 2026: Q2 vs Q1.
        cs, ce, cl, ps, pe, pl = get_period_comparison_ranges(
            None, 1, None, 'quarter', now=datetime(2026, 7, 6))
        assert cs == datetime(2026, 4, 1, 4, 0)
        assert ce == datetime(2026, 7, 1, 4, 0)
        assert cl == "Q2 2026"
        assert ps == datetime(2026, 1, 1, 5, 0)
        assert pe == datetime(2026, 4, 1, 4, 0)
        assert pl == "Q1 2026"

    def test_january_year_rollover(self):
        # In January 2026 (Q1 in progress): Q4 2025 vs Q3 2025.
        cs, ce, cl, ps, pe, pl = get_period_comparison_ranges(
            None, 1, None, 'quarter', now=datetime(2026, 1, 6))
        assert cs == datetime(2025, 10, 1, 4, 0)
        assert ce == datetime(2026, 1, 1, 5, 0)
        assert cl == "Q4 2025"
        assert ps == datetime(2025, 7, 1, 4, 0)
        assert pl == "Q3 2025"

    def test_pinned_period_start(self):
        # Pinning any date inside Q1 2026 selects Q1 2026 vs Q4 2025.
        cs, ce, cl, ps, pe, pl = get_period_comparison_ranges(
            None, 1, None, 'quarter',
            period_start=datetime(2026, 1, 1), now=datetime(2026, 7, 6))
        assert cl == "Q1 2026"
        assert pl == "Q4 2025"
        assert ps == datetime(2025, 10, 1, 4, 0)
        assert pe == datetime(2026, 1, 1, 5, 0)
