"""
Investigations API: record lifecycle, access control and the evidence endpoint.

No agent loop is exercised here. Phase A owns the record and the evidence it
will be given; the model that narrates over that evidence lands separately.
"""
import datetime
import json

import pytest

from app import models
from tests import golden_expected as gx
from tests.fixtures.golden_dataset import BATCH_1_ID, BATCH_2_ID, BRAND_1_ID, USER_1_ID


def _trigger(client, **body):
    return client.post("/api/investigations/trigger", json=body)


class TestTrigger:
    def test_batch_mode_creates_a_pending_record(self, golden_client, golden_db):
        response = _trigger(golden_client, comparison_mode="batch")
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] == "pending"
        assert body["comparison_mode"] == "batch"
        assert "February 2026" in body["message"]

        record = golden_db.query(models.Investigation).get(body["investigation_id"])
        assert record.current_batch_id == BATCH_2_ID
        assert record.previous_batch_id == BATCH_1_ID
        assert record.trigger_type == "manual"

    def test_period_mode_stores_resolved_bounds(self, golden_client, golden_db):
        """The window is stored, not recomputed later, so an investigation always
        reports on the period it was created for."""
        response = _trigger(golden_client, comparison_mode="month",
                            period_start="2026-02-01")
        assert response.status_code == 202, response.text
        record = golden_db.query(models.Investigation).get(
            response.json()["investigation_id"])
        assert record.current_period_label == "February 2026"
        assert record.previous_period_label == "January 2026"
        assert record.current_period_start is not None
        assert record.current_period_end is not None

    def test_defaults_to_month(self, golden_client, golden_db):
        """comparison_mode is optional. period_start is pinned here only because
        the fixture's data is historical; omitting it would resolve to the last
        complete month relative to today, which has no responses."""
        response = golden_client.post(
            "/api/investigations/trigger", json={"period_start": "2026-02-01"})
        assert response.status_code == 202, response.text
        assert response.json()["comparison_mode"] == "month"

    def test_empty_baseline_period_is_refused_with_a_reason(self, golden_client):
        """Q4 2025 has no data. Comparing against it would report the current
        quarter's whole value as the size of the change."""
        response = _trigger(golden_client, comparison_mode="quarter",
                            period_start="2026-01-01")
        assert response.status_code == 400
        assert "nothing to compare" in response.json()["detail"]

    def test_earliest_batch_is_refused_with_a_reason(self, golden_client):
        response = _trigger(golden_client, comparison_mode="batch", batch_id=BATCH_1_ID)
        assert response.status_code == 400
        assert "earliest collection" in response.json()["detail"]

    def test_invalid_mode_is_rejected(self, golden_client):
        response = _trigger(golden_client, comparison_mode="fortnight")
        assert response.status_code == 400
        assert "Invalid comparison_mode" in response.json()["detail"]

    def test_unknown_field_is_rejected(self, golden_client):
        response = _trigger(golden_client, comparison_mode="batch", sneaky=True)
        assert response.status_code == 422


class TestListAndDetail:
    def test_lists_most_recent_first(self, golden_client):
        assert _trigger(golden_client, comparison_mode="batch").status_code == 202
        assert _trigger(golden_client, comparison_mode="month",
                        period_start="2026-02-01").status_code == 202
        rows = golden_client.get("/api/investigations/").json()
        assert len(rows) == 2
        assert rows[0]["created_at"] >= rows[1]["created_at"]

    def test_detail_round_trips(self, golden_client):
        created = _trigger(golden_client, comparison_mode="batch").json()
        detail = golden_client.get(
            f"/api/investigations/{created['investigation_id']}").json()
        assert detail["id"] == created["investigation_id"]
        assert detail["comparison_mode"] == "batch"
        assert detail["status"] == "pending"

    def test_missing_investigation_is_404(self, golden_client):
        assert golden_client.get("/api/investigations/9999").status_code == 404

    def test_delete_removes_it(self, golden_client):
        created = _trigger(golden_client, comparison_mode="batch").json()
        investigation_id = created["investigation_id"]
        assert golden_client.delete(
            f"/api/investigations/{investigation_id}").status_code == 204
        assert golden_client.get(
            f"/api/investigations/{investigation_id}").status_code == 404


class TestStaleRunReaper:
    def test_an_orphaned_run_is_failed_rather_than_left_running(
            self, golden_client, golden_db):
        """A restart mid-run would otherwise leave the record in 'running'
        forever, which is a known failure mode of the reference implementation."""
        created = _trigger(golden_client, comparison_mode="batch").json()
        record = golden_db.query(models.Investigation).get(created["investigation_id"])
        record.status = "running"
        record.last_heartbeat_at = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
        golden_db.commit()

        golden_client.get("/api/investigations/")

        golden_db.expire_all()
        record = golden_db.query(models.Investigation).get(created["investigation_id"])
        assert record.status == "failed"
        assert "stopped reporting progress" in record.error_message

    def test_a_live_run_is_left_alone(self, golden_client, golden_db):
        created = _trigger(golden_client, comparison_mode="batch").json()
        record = golden_db.query(models.Investigation).get(created["investigation_id"])
        record.status = "running"
        record.last_heartbeat_at = datetime.datetime.utcnow()
        golden_db.commit()

        golden_client.get("/api/investigations/")

        golden_db.expire_all()
        assert golden_db.query(models.Investigation).get(
            created["investigation_id"]).status == "running"


class TestEvidenceEndpoint:
    @pytest.fixture()
    def evidence(self, golden_client):
        created = _trigger(golden_client, comparison_mode="batch").json()
        response = golden_client.get(
            f"/api/investigations/{created['investigation_id']}/evidence")
        assert response.status_code == 200, response.text
        return response.json()

    def test_metrics_match_the_dashboard(self, evidence):
        """An investigation cannot contradict the screen it was launched from."""
        assert (evidence["metrics"]["previous"]["mention_rate"]["value"]
                == gx.B1_MENTION_RATE)
        assert (evidence["metrics"]["previous"]["share_of_voice"]["value"]
                == gx.B1_SHARE_OF_VOICE)
        assert (evidence["metrics"]["previous"]["positive_sentiment_rate"]["value"]
                == gx.B1_POSITIVE_SENTIMENT_RATE)

    def test_reports_what_was_excluded(self, evidence):
        quality = evidence["metrics"]["previous"]["data_quality"]
        assert quality["unanalyzed_excluded"] == gx.B1_UNANALYZED_EXCLUDED
        assert quality["counted"] == gx.B1_POPULATION

    def test_includes_every_evidence_section(self, evidence):
        assert set(evidence) == {
            "comparison", "context", "metrics", "queries", "platforms",
            "competitors", "descriptors", "trend",
        }

    def test_context_names_the_branded_queries(self, evidence):
        """The agent has to know which queries measure nothing about organic
        visibility before drawing conclusions from query-level data."""
        branded = [q for q in evidence["context"]["queries"] if q["brand_in_query"]]
        assert len(branded) == 2

    def test_evidence_is_available_before_any_model_runs(self, golden_client):
        """The whole deterministic half of the feature is reviewable without
        spending anything on inference."""
        created = _trigger(golden_client, comparison_mode="batch").json()
        detail = golden_client.get(
            f"/api/investigations/{created['investigation_id']}").json()
        assert detail["status"] == "pending"
        assert golden_client.get(
            f"/api/investigations/{created['investigation_id']}/evidence"
        ).status_code == 200


class TestToolInvocations:
    def test_empty_until_the_agent_runs(self, golden_client):
        created = _trigger(golden_client, comparison_mode="batch").json()
        response = golden_client.get(
            f"/api/investigations/{created['investigation_id']}/tool-invocations")
        assert response.status_code == 200
        assert response.json() == []
