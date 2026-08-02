"""
Auto-triggers: when a collection should open an investigation by itself.

The interesting cases are all the ones where it must NOT fire. A trigger that
raises an investigation for a month with no collection in it, or a second one
for a month that already has one, turns the feature into noise, and a noisy
alert is ignored, which is the same as having none.

Thresholds are set through the environment here rather than relying on the
golden dataset happening to move by more than ten points. That keeps the tests
about the trigger logic instead of about the fixture's arithmetic, which is
already covered against hand-derived expectations elsewhere.
"""
import json

import pytest

from app import models
from app.services.investigation import triggers
from app.services.investigation.scope import build_scope
from tests.fixtures.golden_dataset import BRAND_1_ID, USER_1_ID

FEBRUARY = "2026-02-01"


@pytest.fixture
def february(golden_db):
    from app.services.period_ranges import parse_period_start
    return parse_period_start(FEBRUARY)


@pytest.fixture
def sensitive(monkeypatch):
    """Thresholds low enough that any real movement crosses them."""
    for metric in triggers.DEFAULT_THRESHOLDS:
        monkeypatch.setenv(f"INVESTIGATION_THRESHOLD_{metric.upper()}", "0.1")


@pytest.fixture
def insensitive(monkeypatch):
    for metric in triggers.DEFAULT_THRESHOLDS:
        monkeypatch.setenv(f"INVESTIGATION_THRESHOLD_{metric.upper()}", "500")


class TestConfiguration:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv(triggers._ENABLED_ENV, raising=False)
        assert triggers.auto_trigger_enabled() is True

    def test_can_be_switched_off(self, monkeypatch):
        monkeypatch.setenv(triggers._ENABLED_ENV, "false")
        assert triggers.auto_trigger_enabled() is False

    def test_thresholds_are_overridable(self, monkeypatch):
        monkeypatch.setenv("INVESTIGATION_THRESHOLD_MENTION_RATE", "3.5")
        assert triggers.threshold_for("mention_rate") == 3.5

    def test_a_nonsense_threshold_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("INVESTIGATION_THRESHOLD_MENTION_RATE", "quite a lot")
        assert triggers.threshold_for("mention_rate") == (
            triggers.DEFAULT_THRESHOLDS["mention_rate"])


class TestCrossings:
    def test_movement_is_reported_with_the_numbers_behind_it(
            self, golden_db, february, sensitive):
        scope = build_scope(golden_db, USER_1_ID, BRAND_1_ID, "month", february)
        crossings = triggers.find_crossings(golden_db, scope)

        assert crossings, "February and January differ; something should cross"
        for crossing in crossings:
            assert crossing["label"]
            assert crossing["change"] is not None
            # A trigger that cannot say what moved from what to what is not
            # checkable against the write-up it produces.
            assert "current" in crossing and "previous" in crossing

    def test_nothing_crosses_an_unreachable_threshold(self, golden_db, february,
                                                      insensitive):
        scope = build_scope(golden_db, USER_1_ID, BRAND_1_ID, "month", february)
        assert triggers.find_crossings(golden_db, scope) == []

    def test_competitor_share_is_checked_separately_from_the_brand(
            self, golden_db, february, sensitive):
        """A competitor can surge without the brand's own share moving much."""
        scope = build_scope(golden_db, USER_1_ID, BRAND_1_ID, "month", february)
        crossings = triggers.find_crossings(golden_db, scope)
        subjects = {c["subject"] for c in crossings}
        assert subjects - {"brand"}, (
            "Competitor-level share of voice must be able to fire on its own")


class TestMaybeTrigger:
    def test_creates_an_auto_investigation_and_queues_it(
            self, golden_db, february, sensitive, queued_investigations):
        investigation_id = triggers.maybe_trigger(
            golden_db, USER_1_ID, BRAND_1_ID, period_start=february)

        assert investigation_id is not None
        record = golden_db.query(models.Investigation).get(investigation_id)
        assert record.trigger_type == "auto"
        assert record.status == "pending"
        assert record.comparison_mode == "month"
        assert record.current_period_label == "February 2026"
        assert json.loads(record.trigger_metrics)
        assert queued_investigations == [investigation_id]

    def test_does_not_fire_twice_for_the_same_period(
            self, golden_db, february, sensitive):
        first = triggers.maybe_trigger(golden_db, USER_1_ID, BRAND_1_ID,
                                       period_start=february)
        second = triggers.maybe_trigger(golden_db, USER_1_ID, BRAND_1_ID,
                                        period_start=february)
        assert first is not None
        assert second is None, (
            "Later batches in the same month re-check but must not open a "
            "second investigation for a period that already has one.")

    def test_a_manual_investigation_also_blocks_the_auto_one(
            self, golden_client, golden_db, february, sensitive):
        """Dedupe is on the period, not on who asked."""
        response = golden_client.post("/api/investigations/trigger",
                                      json={"comparison_mode": "month",
                                            "period_start": FEBRUARY})
        assert response.status_code == 202
        assert triggers.maybe_trigger(golden_db, USER_1_ID, BRAND_1_ID,
                                      period_start=february) is None

    def test_no_movement_means_no_investigation(self, golden_db, february,
                                                insensitive):
        assert triggers.maybe_trigger(golden_db, USER_1_ID, BRAND_1_ID,
                                      period_start=february) is None

    def test_an_empty_window_never_fires(self, golden_db, sensitive):
        """The golden data stops in February; the last complete month today has
        nothing in it. A period with no collection would read as a total
        collapse in every metric."""
        assert triggers.maybe_trigger(golden_db, USER_1_ID, BRAND_1_ID) is None

    def test_respects_the_off_switch(self, golden_db, february, sensitive,
                                     monkeypatch):
        monkeypatch.setenv(triggers._ENABLED_ENV, "0")
        assert triggers.maybe_trigger(golden_db, USER_1_ID, BRAND_1_ID,
                                      period_start=february) is None


class TestNeverBreaksACollection:
    def test_a_failure_is_swallowed(self, golden_db, monkeypatch):
        def explode(*args, **kwargs):
            raise RuntimeError("database on fire")

        monkeypatch.setattr(triggers, "maybe_trigger", explode)
        # No exception: a collection that succeeded must not be reported as
        # failed because the follow-up could not start.
        triggers.check_after_collection(golden_db, USER_1_ID, BRAND_1_ID)

    def test_the_happy_path_still_runs(self, golden_db, february, insensitive):
        triggers.check_after_collection(golden_db, USER_1_ID, BRAND_1_ID)
