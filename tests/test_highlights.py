"""
Tests for app/routers/highlights.py.

The metric computers now delegate to app/services/metrics_core.py, so the email
reports the same numbers as the dashboard. They take a MetricPopulation rather
than a raw response list, which is what moved the branded-query exclusion, the
analyzed_at filter and the tenancy filter into one place.

The definitions themselves are tested in tests/test_metrics_core.py against
hand-derived constants. What is tested here is the email's own shaping: ordering,
top-N caps, the fact-sheet builders, and endpoint auth. Populations are built
directly from records so these stay fast and need no database.
"""
from datetime import datetime

import pytest

from app.services.metrics_core import MetricPopulation, ResponseRecord
from app.routers.highlights import (
    _build_quarterly_fact_sheet,
    _build_verified_fact_sheet,
    _compute_descriptors,
    _compute_mention_rate,
    _compute_monthly_breakdown,
    _compute_platform_rates,
    _compute_sentiment,
    _get_month_before_range,
    _get_previous_month_range,
)

_next_id = iter(range(1, 10_000))


def make_record(query_id="Q001", brand_mentioned="Yes", sentiment=None,
                descriptors=None, platform="ChatGPT", query_text="test query",
                timestamp=None, is_branded_query=False, analyzed=True):
    return ResponseRecord(
        response_id=next(_next_id),
        query_id=query_id,
        platform=platform,
        brand_mentioned=brand_mentioned,
        brand_position=None,
        sentiment=sentiment,
        descriptors=tuple(d.strip() for d in descriptors.split(",")) if descriptors else (),
        competitors=(),
        analyzed=analyzed,
        is_branded_query=is_branded_query,
        query_known=True,
        query_text=query_text,
        timestamp=timestamp or datetime(2026, 5, 15),
    )


def make_population(records, target_descriptors=()):
    return MetricPopulation(rows=list(records), target_descriptors=target_descriptors)


class TestComputeMentionRate:
    def test_counts_yes_and_indirect(self):
        population = make_population([
            make_record(brand_mentioned="Yes"),
            make_record(brand_mentioned="Indirect"),
            make_record(brand_mentioned="No"),
            make_record(brand_mentioned="No"),
        ])
        total, mentioned, rate = _compute_mention_rate(population)
        assert total == 4
        assert mentioned == 2
        assert rate == 50.0

    def test_excludes_branded_queries(self):
        population = make_population([
            make_record(query_id="Q001", brand_mentioned="Yes"),
            make_record(query_id="Q_BRANDED", brand_mentioned="Yes",
                        is_branded_query=True),
        ])
        total, mentioned, rate = _compute_mention_rate(population)
        assert total == 1
        assert mentioned == 1
        assert rate == 100.0

    def test_excludes_unanalyzed_rows(self):
        """The email used to count these as "brand not mentioned", so a failed
        analysis pass lowered the emailed rate with nothing to indicate it."""
        population = make_population([
            make_record(brand_mentioned="Yes"),
            make_record(brand_mentioned=None, analyzed=False),
        ])
        total, mentioned, rate = _compute_mention_rate(population)
        assert total == 1
        assert rate == 100.0

    def test_zero_eligible(self):
        population = make_population([
            make_record(query_id="Q_BRANDED", is_branded_query=True)])
        total, mentioned, rate = _compute_mention_rate(population)
        assert (total, mentioned, rate) == (0, 0, 0.0)


class TestComputeSentiment:
    def test_direct_mentions_only(self):
        population = make_population([
            make_record(brand_mentioned="Yes", sentiment="Positive"),
            make_record(brand_mentioned="Yes", sentiment="Negative"),
            make_record(brand_mentioned="Indirect", sentiment="Positive"),  # excluded
            make_record(brand_mentioned="Yes", sentiment=None),  # excluded
        ])
        sentiment, total = _compute_sentiment(population)
        assert total == 2
        assert sentiment["Positive"]["count"] == 1
        assert sentiment["Positive"]["pct"] == 50.0
        assert sentiment["Negative"]["count"] == 1

    def test_empty(self):
        sentiment, total = _compute_sentiment(
            make_population([make_record(brand_mentioned="No")]))
        assert sentiment == {}
        assert total == 0


class TestComputeDescriptors:
    def test_splits_and_counts(self):
        population = make_population([
            make_record(descriptors="innovative, respected"),
            make_record(descriptors="innovative"),
            make_record(brand_mentioned="No", descriptors="ignored"),
        ])
        top = _compute_descriptors(population)
        assert top[0] == ("innovative", 2)
        assert ("respected", 1) in top
        assert all(d != "ignored" for d, _ in top)

    def test_case_variants_merge(self):
        """Variants used to compete for slots in the same top-10 list."""
        population = make_population([
            make_record(descriptors="High-Temperature Plasma"),
            make_record(descriptors="high-temperature plasma"),
        ])
        top = _compute_descriptors(population)
        assert len(top) == 1
        assert top[0][1] == 2

    def test_top_ten_cap(self):
        population = make_population([
            make_record(descriptors=", ".join(f"d{i}" for i in range(15)))])
        assert len(_compute_descriptors(population)) == 10


class TestComputePlatformRates:
    def test_per_platform(self):
        population = make_population([
            make_record(platform="ChatGPT", brand_mentioned="Yes"),
            make_record(platform="ChatGPT", brand_mentioned="No"),
            make_record(platform="Claude", brand_mentioned="Indirect"),
        ])
        rates = _compute_platform_rates(population)
        assert rates["ChatGPT"] == {"total": 2, "mentioned": 1, "rate": 50.0}
        assert rates["Claude"]["rate"] == 100.0

    def test_ordered_by_mention_count(self):
        population = make_population([
            make_record(platform="Gemini", brand_mentioned="No"),
            make_record(platform="ChatGPT", brand_mentioned="Yes"),
        ])
        assert list(_compute_platform_rates(population)) == ["ChatGPT", "Gemini"]


class TestComputeMonthlyBreakdown:
    def test_chronological_order(self):
        population = make_population([
            make_record(timestamp=datetime(2026, 6, 5), brand_mentioned="Yes"),
            make_record(timestamp=datetime(2026, 4, 10), brand_mentioned="No"),
            make_record(timestamp=datetime(2026, 5, 20), brand_mentioned="Yes"),
        ])
        breakdown = _compute_monthly_breakdown(population)
        assert list(breakdown.keys()) == ["April 2026", "May 2026", "June 2026"]
        assert breakdown["April 2026"]["rate"] == 0
        assert breakdown["June 2026"]["rate"] == 100.0


class TestMonthRanges:
    def test_previous_month_january_rollover(self):
        label, start, end = _get_previous_month_range(now=datetime(2026, 1, 10))
        assert label == "December 2025"
        assert start == datetime(2025, 12, 1)
        assert end == datetime(2025, 12, 31, 23, 59, 59)

    def test_month_before(self):
        prev_start, prev_end = _get_month_before_range(datetime(2026, 1, 1))
        assert prev_start == datetime(2025, 12, 1)
        assert prev_end == datetime(2025, 12, 31, 23, 59, 59)


class TestFactSheets:
    def test_monthly_fact_sheet_quotes_numbers(self):
        sheet = _build_verified_fact_sheet(
            period_label="June 2026",
            total=120, mentioned=66, mention_rate=55.0,
            prev_label="May 2026", prev_rate=50.5,
            platform_rates={"ChatGPT": {"total": 60, "mentioned": 40, "rate": 66.7}},
            sentiment={"Positive": {"count": 30, "pct": 75.0}}, sentiment_total=40,
            prev_sentiment={},
            descriptors=[("innovative", 12)],
            query_rates={"Q001": {"total": 10, "mentioned": 9, "rate": 90.0, "text": "best labs"}},
            batch_trends=[{"date": "Jun 07", "rate": 54.0, "total": 30}],
        )
        assert "55.0%" in sheet
        assert "PREVIOUS MONTH (May 2026): 50.5%" in sheet
        assert "+4.5 percentage points" in sheet
        assert "innovative: 12" in sheet

    def test_quarterly_fact_sheet_quotes_numbers(self):
        sheet = _build_quarterly_fact_sheet(
            quarter_label="FY2026 Q3", prev_quarter_label="FY2026 Q2",
            total=300, mentioned=180, mention_rate=60.0, prev_rate=52.0,
            monthly_breakdown={"April 2026": {"total": 100, "mentioned": 55, "rate": 55.0}},
            platform_rates={"Claude": {"total": 80, "mentioned": 60, "rate": 75.0}},
            sentiment={"Positive": {"count": 90, "pct": 90.0}}, sentiment_total=100,
            prev_sentiment={"Positive": {"count": 70, "pct": 87.5}},
            descriptors=[("respected", 20)],
            query_rates={"Q002": {"total": 12, "mentioned": 3, "rate": 25.0, "text": "fusion research"}},
        )
        assert "FY2026 Q3" in sheet
        assert "PREVIOUS QUARTER (FY2026 Q2): 52.0%" in sheet
        assert "+8.0 percentage points" in sheet


class TestEndpointAuth:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app, raise_server_exceptions=False)

    def test_503_when_secret_unset(self, client, monkeypatch):
        monkeypatch.delenv("HIGHLIGHTS_CRON_SECRET", raising=False)
        resp = client.post("/highlights/monthly-check", headers={"X-Cron-Secret": "anything"})
        assert resp.status_code == 503

    def test_403_on_bad_secret(self, client, monkeypatch):
        monkeypatch.setenv("HIGHLIGHTS_CRON_SECRET", "correct-secret")
        resp = client.post("/highlights/quarterly-check", headers={"X-Cron-Secret": "wrong"})
        assert resp.status_code == 403

    def test_403_on_missing_header(self, client, monkeypatch):
        monkeypatch.setenv("HIGHLIGHTS_CRON_SECRET", "correct-secret")
        resp = client.post("/highlights/monthly-check")
        assert resp.status_code == 403
