"""
Scheduler bookkeeping that nothing used to repair.

Two things were found wrong on tales.pppl.gov on 2026-09-21, a week after the
dropped-connection incident that tests/test_scheduler_session.py covers:

- The history row for the 2026-09-14 run was still 'running' with zero counts,
  although its batch held 66 responses that had since been analyzed by hand.
  The run that owned the row was long gone, so nothing would ever close it.
- next_collection_at read 2026-09-07 while the cron kept firing on time,
  because the cron scheduler never wrote that column.
"""
import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, scheduler
from app.database import Base
from app.services import data_pipeline

USER_ID = 6
BRAND_ID = 1
SCHEDULE_ID = 1

RUN_STARTED = datetime(2026, 9, 14, 6, 30, 0)
BATCH_STARTED = datetime(2026, 9, 14, 6, 30, 14)
BATCH_COMPLETED = datetime(2026, 9, 14, 7, 18, 45)


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'reconcile.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    seed = factory()
    seed.add(models.User(id=USER_ID, email="owner@example.gov", is_admin=True))
    seed.add(models.BrandInfo(id=BRAND_ID, user_id=USER_ID, brand_name="PPPL"))
    seed.add(models.ScheduledTask(
        id=SCHEDULE_ID, user_id=USER_ID, brand_id=BRAND_ID,
        collection_frequency="weekly", is_enabled=True,
        next_collection_at=datetime(2026, 9, 7, 3, 30),
        next_run_at=datetime(2026, 9, 7, 3, 30),
    ))
    seed.commit()
    seed.close()

    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    scheduler._running_brands.clear()
    yield factory
    engine.dispose()


def _stuck_row(factory, started_at=RUN_STARTED):
    db = factory()
    db.add(models.ScheduledTaskHistory(
        id=338, scheduled_task_id=SCHEDULE_ID, user_id=USER_ID, brand_id=BRAND_ID,
        started_at=started_at, status='running',
    ))
    db.commit()
    db.close()


def _batch(factory, batch_id=425, analyzed=66, total=66, started_at=BATCH_STARTED):
    db = factory()
    db.add(models.CollectionBatch(
        id=batch_id, user_id=USER_ID, brand_id=BRAND_ID,
        batch_name=f"Collection {started_at}", started_at=started_at,
        completed_at=BATCH_COMPLETED, status='completed',
    ))
    for n in range(total):
        db.add(models.Response(
            user_id=USER_ID, brand_id=BRAND_ID, batch_id=batch_id,
            query_id=f"Q{n:03d}", platform="Gemini", response_text="text",
            analyzed_at=BATCH_COMPLETED if n < analyzed else None,
        ))
    db.commit()
    db.close()


def _history(factory, history_id=338):
    db = factory()
    try:
        row = db.query(models.ScheduledTaskHistory).filter_by(id=history_id).one()
        db.expunge(row)
        return row
    finally:
        db.close()


def _schedule(factory):
    db = factory()
    try:
        row = db.query(models.ScheduledTask).filter_by(id=SCHEDULE_ID).one()
        db.expunge(row)
        return row
    finally:
        db.close()


# --- history rows stuck at 'running' ---------------------------------------

def test_stuck_row_is_rebuilt_from_its_fully_analyzed_batch(factory):
    _stuck_row(factory)
    _batch(factory, analyzed=66)

    fixed = scheduler.reconcile_on_startup()

    row = _history(factory)
    assert fixed["history_rows"] == 1
    assert row.status == 'success'
    assert row.batch_id == 425
    assert row.collection_responses == 66
    assert row.analysis_responses == 66
    assert row.completed_at == BATCH_COMPLETED
    # The counts describe the batch today, not what the lost run achieved.
    assert "Reconstructed" in row.error_message


def test_stuck_row_with_an_unanalyzed_batch_is_partial(factory):
    _stuck_row(factory)
    _batch(factory, analyzed=0)

    scheduler.reconcile_on_startup()

    row = _history(factory)
    assert row.status == 'partial'
    assert row.collection_responses == 66
    assert row.analysis_responses == 0


def test_stuck_row_with_no_batch_is_failed(factory):
    _stuck_row(factory)

    scheduler.reconcile_on_startup()

    row = _history(factory)
    assert row.status == 'failed'
    assert row.completed_at is not None
    assert "no collection batch" in row.error_message


def test_a_later_manual_batch_is_not_credited_to_the_stuck_run(factory):
    """2026-09-07 failed in 16 seconds; the manual batch came 19 hours later."""
    _stuck_row(factory, started_at=datetime(2026, 9, 7, 6, 30))
    _batch(factory, batch_id=424, started_at=datetime(2026, 9, 8, 0, 52, 43))

    scheduler.reconcile_on_startup()

    row = _history(factory)
    assert row.status == 'failed'
    assert row.batch_id is None


def test_a_run_that_may_still_be_alive_is_left_alone(factory):
    _stuck_row(factory, started_at=datetime.utcnow() - timedelta(hours=1))

    fixed = scheduler.reconcile_on_startup()

    assert fixed["history_rows"] == 0
    assert _history(factory).status == 'running'


def test_finished_rows_are_never_touched(factory):
    db = factory()
    db.add(models.ScheduledTaskHistory(
        id=337, scheduled_task_id=SCHEDULE_ID, user_id=USER_ID, brand_id=BRAND_ID,
        started_at=datetime(2026, 9, 7, 6, 30), completed_at=datetime(2026, 9, 7, 6, 30, 16),
        status='failed', error_message="Collection failed: Unknown error",
    ))
    db.commit()
    db.close()

    scheduler.reconcile_on_startup()

    row = _history(factory, 337)
    assert row.status == 'failed'
    assert row.error_message == "Collection failed: Unknown error"


def test_reconcile_never_raises(monkeypatch):
    def broken():
        raise RuntimeError("database is down")
    monkeypatch.setattr(scheduler, "SessionLocal", broken)

    # Bookkeeping must not be able to stop the app from starting.
    assert scheduler.reconcile_on_startup() == {"history_rows": 0, "schedules": 0}


# --- next_collection_at ----------------------------------------------------

def test_a_stale_next_collection_date_is_advanced_at_startup(factory):
    fixed = scheduler.reconcile_on_startup()

    schedule = _schedule(factory)
    expected = scheduler.next_fixed_collection(datetime.utcnow())
    assert fixed["schedules"] == 1
    assert schedule.next_collection_at == expected
    assert schedule.next_run_at == expected
    assert schedule.next_collection_at > datetime.utcnow()


def test_a_future_next_collection_date_is_left_alone(factory):
    future = datetime.utcnow() + timedelta(days=2)
    db = factory()
    db.query(models.ScheduledTask).update({"next_collection_at": future})
    db.commit()
    db.close()

    fixed = scheduler.reconcile_on_startup()

    assert fixed["schedules"] == 0
    assert _schedule(factory).next_collection_at == future


def test_a_disabled_schedule_is_left_alone(factory):
    db = factory()
    db.query(models.ScheduledTask).update({"is_enabled": False})
    db.commit()
    db.close()

    assert scheduler.reconcile_on_startup()["schedules"] == 0


def test_a_scheduled_run_advances_the_next_collection_date(factory, monkeypatch):
    monkeypatch.setattr(
        data_pipeline, "run_collection_only",
        lambda user_id, brand_id, triggered_by="scheduled":
            {"success": True, "responses_collected": 66, "batch_id": 426},
    )
    monkeypatch.setattr(
        data_pipeline, "run_analysis_only",
        lambda user_id, brand_id, batch_id, triggered_by="scheduled":
            {"success": True, "responses_analyzed": 66},
    )

    asyncio.run(scheduler.execute_collection_and_analysis(SCHEDULE_ID, USER_ID, BRAND_ID))

    schedule = _schedule(factory)
    assert schedule.next_collection_at == scheduler.next_fixed_collection(schedule.last_collection_at)
    assert schedule.next_run_at == schedule.next_collection_at

    db = factory()
    row = db.query(models.ScheduledTaskHistory).one()
    db.close()
    assert row.status == 'success'
    assert row.batch_id == 426


def test_next_fixed_collection_follows_the_cron_days():
    assert scheduler.next_fixed_collection(datetime(2026, 9, 21, 6, 30)) == datetime(2026, 10, 1, 6, 30)
    assert scheduler.next_fixed_collection(datetime(2026, 9, 21, 6, 29)) == datetime(2026, 9, 21, 6, 30)
    assert scheduler.next_fixed_collection(datetime(2026, 12, 25)) == datetime(2027, 1, 1, 6, 30)
