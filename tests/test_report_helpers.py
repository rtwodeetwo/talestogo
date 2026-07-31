"""
Unit tests for the date-range helpers in scripts/admin/generate_report.py
and for the Report schema fields added for quarterly/annual support.

The date helpers accept an injectable `now`, so these are pure date-math
tests with no database.
"""
from datetime import datetime

from scripts.admin.generate_report import (
    get_last_calendar_month_range,
    get_last_quarter_range,
    get_last_year_range,
)
from app import schemas


class TestLastCalendarMonthRange:
    def test_mid_year(self):
        start, end, label = get_last_calendar_month_range(now=datetime(2026, 7, 15))
        assert start == datetime(2026, 6, 1)
        assert end == datetime(2026, 7, 1)  # exclusive
        assert label == "June 2026"

    def test_january_rollover(self):
        start, end, label = get_last_calendar_month_range(now=datetime(2026, 1, 10))
        assert start == datetime(2025, 12, 1)
        assert end == datetime(2026, 1, 1)
        assert label == "December 2025"


class TestLastQuarterRange:
    def test_mid_quarter(self):
        # During Q3 (July): last complete quarter is Q2.
        start, end, label = get_last_quarter_range(now=datetime(2026, 7, 15))
        assert start == datetime(2026, 4, 1)
        assert end == datetime(2026, 7, 1)  # exclusive: first day of next quarter
        assert label == "Q2 2026"

    def test_january_rollover(self):
        # During Q1 (January): last complete quarter is Q4 of the previous year.
        start, end, label = get_last_quarter_range(now=datetime(2026, 1, 10))
        assert start == datetime(2025, 10, 1)
        assert end == datetime(2026, 1, 1)
        assert label == "Q4 2025"

    def test_q4_boundary(self):
        # During Q4 (November): last complete quarter is Q3 of the same year.
        start, end, label = get_last_quarter_range(now=datetime(2026, 11, 20))
        assert start == datetime(2026, 7, 1)
        assert end == datetime(2026, 10, 1)
        assert label == "Q3 2026"


class TestLastYearRange:
    def test_basic(self):
        start, end, label = get_last_year_range(now=datetime(2026, 7, 15))
        assert start == datetime(2025, 1, 1)
        assert end == datetime(2026, 1, 1)  # exclusive
        assert label == "2025 Annual Report"


class TestReportSchema:
    def test_period_label_round_trip(self):
        report = schemas.ReportCreate(
            title="Test Brand Quarterly AI Reputation Analysis - Q2 2026",
            report_content="# Report body",
            report_type="quarterly",
            period_label="Q2 2026",
            start_date=datetime(2026, 4, 1),
            end_date=datetime(2026, 7, 1),
            total_responses=100,
        )
        assert report.report_type == "quarterly"
        assert report.period_label == "Q2 2026"

    def test_period_label_optional(self):
        report = schemas.ReportCreate(title="t", report_content="c")
        assert report.period_label is None
        assert report.report_type == "monthly"

    def test_read_schema_includes_brand_id_and_period_label(self):
        fields = schemas.Report.model_fields
        assert "brand_id" in fields
        assert "period_label" in fields
