"""
The scheduled collection blocks for up to 90 minutes in a subprocess, then up
to 60 more in analysis. Whatever database connection the scheduler is holding
across that wait can be dropped by the network, and pool_pre_ping cannot help
a connection that is already checked out.

On 2026-09-14 that is exactly what happened on tales.pppl.gov: the history row
sat at 'running' forever and 66 collected responses were never analyzed.
These tests pin two things: the scheduler holds no open transaction while the
pipeline runs, and every outcome is still recorded when every connection it
opened beforehand has died.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, scheduler
from app.database import Base
from app.services import data_pipeline

USER_ID = 6
BRAND_ID = 1
SCHEDULE_ID = 1


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """
    A file-backed SQLite database (so each session gets its own connection,
    as with PostgreSQL), a tracking SessionLocal patched into the scheduler,
    and a stub for the failure email.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'scheduler.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    seed = factory()
    seed.add(models.User(id=USER_ID, email="owner@example.gov", is_admin=True))
    seed.add(models.BrandInfo(id=BRAND_ID, user_id=USER_ID, brand_name="PPPL"))
    seed.add(models.ScheduledTask(
        id=SCHEDULE_ID, user_id=USER_ID, brand_id=BRAND_ID,
        collection_frequency="monthly", is_enabled=True,
    ))
    seed.commit()
    seed.close()

    created = []

    def tracking_factory():
        session = factory()
        created.append(session)
        return session

    monkeypatch.setattr(scheduler, "SessionLocal", tracking_factory)

    emails = []

    async def fake_email(schedule, history, db, task_type="collection"):
        emails.append((history.status, history.error_message))

    monkeypatch.setattr(scheduler, "send_completion_email", fake_email)
    scheduler._running_brands.clear()

    def drop_every_held_connection():
        """
        What the network did on 2026-09-14: every connection the scheduler
        still holds inside a transaction dies under it. Returns how many were
        open, which the invariant test wants to be zero.
        """
        held = [s for s in created if s.in_transaction()]
        for s in held:
            s.connection().invalidate()
        return len(held)

    def history():
        db = factory()
        try:
            rows = db.query(models.ScheduledTaskHistory).all()
            assert len(rows) == 1
            row = rows[0]
            db.expunge(row)
            return row
        finally:
            db.close()

    yield {
        "drop": drop_every_held_connection,
        "history": history,
        "emails": emails,
        "monkeypatch": monkeypatch,
    }
    engine.dispose()


def _collection(harness, result, observed):
    def fake(user_id, brand_id, triggered_by="scheduled"):
        observed["held_during_collection"] = harness["drop"]()
        return result
    harness["monkeypatch"].setattr(data_pipeline, "run_collection_only", fake)


def _analysis(harness, result, observed):
    def fake(user_id, brand_id, batch_id, triggered_by="scheduled"):
        observed["held_during_analysis"] = harness["drop"]()
        observed["batch_id"] = batch_id
        return result
    harness["monkeypatch"].setattr(data_pipeline, "run_analysis_only", fake)


def _run(coro):
    asyncio.run(coro)


def test_no_transaction_is_held_while_the_pipeline_runs(harness):
    observed = {}
    _collection(harness, {"success": True, "responses_collected": 66, "batch_id": 425}, observed)
    _analysis(harness, {"success": True, "responses_analyzed": 66}, observed)

    _run(scheduler.execute_collection_and_analysis(SCHEDULE_ID, USER_ID, BRAND_ID))

    assert observed["held_during_collection"] == 0
    assert observed["held_during_analysis"] == 0


def test_success_is_recorded_even_after_every_connection_died(harness):
    observed = {}
    _collection(harness, {"success": True, "responses_collected": 66, "batch_id": 425}, observed)
    _analysis(harness, {"success": True, "responses_analyzed": 66}, observed)

    _run(scheduler.execute_collection_and_analysis(SCHEDULE_ID, USER_ID, BRAND_ID))

    row = harness["history"]()
    assert row.status == "success"
    assert row.collection_responses == 66
    assert row.analysis_responses == 66
    assert row.completed_at is not None
    assert observed["batch_id"] == 425
    assert harness["emails"] == []


def test_collection_failure_is_recorded_and_emailed(harness):
    observed = {}
    _collection(harness, {"success": False, "error": "Collection failed: no keys"}, observed)
    _analysis(harness, {"success": True, "responses_analyzed": 0}, observed)

    _run(scheduler.execute_collection_and_analysis(SCHEDULE_ID, USER_ID, BRAND_ID))

    row = harness["history"]()
    assert row.status == "failed"
    assert row.error_message == "Collection failed: no keys"
    assert row.completed_at is not None
    assert "batch_id" not in observed, "analysis must not run after a failed collection"
    assert harness["emails"] == [("failed", "Collection failed: no keys")]


def test_analysis_failure_is_partial_and_emailed(harness):
    observed = {}
    _collection(harness, {"success": True, "responses_collected": 66, "batch_id": 425}, observed)
    _analysis(harness, {"success": False, "error": "Analysis timed out after 60 minutes"}, observed)

    _run(scheduler.execute_collection_and_analysis(SCHEDULE_ID, USER_ID, BRAND_ID))

    row = harness["history"]()
    assert row.status == "partial"
    assert row.collection_responses == 66
    assert "Analysis timed out" in row.error_message
    assert harness["emails"] == [("partial", row.error_message)]


def test_unexpected_exception_is_recorded_as_failed(harness):
    observed = {}

    def exploding(user_id, brand_id, triggered_by="scheduled"):
        harness["drop"]()
        raise RuntimeError("boom")

    harness["monkeypatch"].setattr(data_pipeline, "run_collection_only", exploding)

    _run(scheduler.execute_collection_and_analysis(SCHEDULE_ID, USER_ID, BRAND_ID))

    row = harness["history"]()
    assert row.status == "failed"
    assert row.error_message == "Unexpected error: boom"
    assert harness["emails"] == [("failed", "Unexpected error: boom")]
    assert (USER_ID, BRAND_ID) not in scheduler._running_brands


def test_collection_only_records_success_after_connection_drop(harness):
    observed = {}
    _collection(harness, {"success": True, "responses_collected": 44, "batch_id": 9}, observed)

    _run(scheduler.execute_collection_only(SCHEDULE_ID, USER_ID, BRAND_ID))

    row = harness["history"]()
    assert row.status == "success"
    assert row.collection_responses == 44
    assert observed["held_during_collection"] == 0
    assert harness["emails"] == []


def test_disabled_schedule_creates_no_history(harness):
    db = scheduler.SessionLocal()
    db.query(models.ScheduledTask).filter_by(id=SCHEDULE_ID).update({"is_enabled": False})
    db.commit()
    db.close()

    called = []
    harness["monkeypatch"].setattr(
        data_pipeline, "run_collection_only", lambda **kw: called.append(kw) or {"success": True}
    )

    _run(scheduler.execute_collection_and_analysis(SCHEDULE_ID, USER_ID, BRAND_ID))

    assert called == []
    db = scheduler.SessionLocal()
    assert db.query(models.ScheduledTaskHistory).count() == 0
    db.close()
