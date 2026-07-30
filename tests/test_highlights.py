"""
Tests for app/routers/highlights.py.

The metric computers are pure functions over Response-like objects, so most
tests use lightweight stand-ins instead of database rows. Endpoint auth is
tested through the FastAPI app with the HIGHLIGHTS_CRON_SECRET env var
patched.
"""
from datetime import datetime
from types import SimpleNamespace

import pytest

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


def make_response(query_id="Q001", brand_mentioned="Yes", sentiment=None,
                  descriptors=None, platform="ChatGPT", query_text="test query",
                  timestamp=None):
    return SimpleNamespace(
        query_id=query_id,
        brand_mentioned=brand_mentioned,
        sentiment=sentiment,
        descriptors=descriptors,
        platform=platform,
        query_text=query_text,
        timestamp=timestamp or datetime(2026, 5, 15),
    )


class TestComputeMentionRate:
    def test_counts_yes_and_indirect(self):
        responses = [
            make_response(brand_mentioned="Yes"),
            make_response(brand_mentioned="Indirect"),
            make_response(brand_mentioned="No"),
            make_response(brand_mentioned="No"),
        ]
        total, mentioned, rate = _compute_mention_rate(responses, {"Q001"})
        assert total == 4
        assert mentioned == 2
        assert rate == 50.0

    def test_excludes_branded_queries(self):
        responses = [
            make_response(query_id="Q001", brand_mentioned="Yes"),
            make_response(query_id="Q_BRANDED", brand_mentioned="Yes"),
        ]
        total, mentioned, rate = _compute_mention_rate(responses, {"Q001"})
        assert total == 1
        assert mentioned == 1
        assert rate == 100.0

    def test_zero_eligible(self):
        responses = [make_response(query_id="Q_BRANDED")]
        total, mentioned, rate = _compute_mention_rate(responses, {"Q001"})
        assert (total, mentioned, rate) == (0, 0, 0.0)


class TestComputeSentiment:
    def test_direct_mentions_only(self):
        responses = [
            make_response(brand_mentioned="Yes", sentiment="Positive"),
            make_response(brand_mentioned="Yes", sentiment="Negative"),
            make_response(brand_mentioned="Indirect", sentiment="Positive"),  # excluded
            make_response(brand_mentioned="Yes", sentiment=None),  # excluded
        ]
        sentiment, total = _compute_sentiment(responses)
        assert total == 2
        assert sentiment["Positive"]["count"] == 1
        assert sentiment["Positive"]["pct"] == 50.0
        assert sentiment["Negative"]["count"] == 1

    def test_empty(self):
        sentiment, total = _compute_sentiment([make_response(brand_mentioned="No")])
        assert sentiment == {}
        assert total == 0


class TestComputeDescriptors:
    def test_splits_and_counts(self):
        responses = [
            make_response(descriptors="innovative, respected"),
            make_response(descriptors="innovative"),
            make_response(brand_mentioned="No", descriptors="ignored"),
        ]
        top = _compute_descriptors(responses)
        assert top[0] == ("innovative", 2)
        assert ("respected", 1) in top
        assert all(d != "ignored" for d, _ in top)

    def test_top_ten_cap(self):
        responses = [make_response(descriptors=", ".join(f"d{i}" for i in range(15)))]
        top = _compute_descriptors(responses)
        assert len(top) == 10


class TestComputePlatformRates:
    def test_per_platform(self):
        responses = [
            make_response(platform="ChatGPT", brand_mentioned="Yes"),
            make_response(platform="ChatGPT", brand_mentioned="No"),
            make_response(platform="Claude", brand_mentioned="Indirect"),
        ]
        rates = _compute_platform_rates(responses, {"Q001"})
        assert rates["ChatGPT"] == {"total": 2, "mentioned": 1, "rate": 50.0}
        assert rates["Claude"]["rate"] == 100.0


class TestComputeMonthlyBreakdown:
    def test_chronological_order(self):
        responses = [
            make_response(timestamp=datetime(2026, 6, 5), brand_mentioned="Yes"),
            make_response(timestamp=datetime(2026, 4, 10), brand_mentioned="No"),
            make_response(timestamp=datetime(2026, 5, 20), brand_mentioned="Yes"),
        ]
        breakdown = _compute_monthly_breakdown(responses, {"Q001"})
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
