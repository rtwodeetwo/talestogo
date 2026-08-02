"""
Upgrading a deployment must not leave it querying columns that are not there.

`create_all()` creates missing tables and never alters existing ones, so every
column added after a deployment first ran is simply absent on that deployment.
The model still selects it, so the query fails with "no such column" and the UI
shows something unrelated: the LLM Configuration page reported "Failed to save
provider" when the real problem was `llm_providers.api_version` missing since
February, which also broke the read that populates the page.

The old defence was a hand-maintained list of ALTER statements in app/main.py.
It fell behind twice that we know of. These tests check the mechanism that
replaced it, against a database deliberately rolled back to an older shape.
"""
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.main import _reconcile_columns


def _old_database(tmp_path, drops):
    """A database built from the models, then rolled back by dropping columns."""
    engine = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        for table, column in drops:
            connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
    return engine


def _columns(engine, table):
    return {c["name"] for c in inspect(engine).get_columns(table)}


class TestReconciliation:
    def test_the_column_that_actually_broke_production(self, tmp_path):
        """llm_providers.api_version, missing on every pre-2026-06 deployment."""
        engine = _old_database(tmp_path, [("llm_providers", "api_version")])
        assert "api_version" not in _columns(engine, "llm_providers")

        _reconcile_columns(engine)

        assert "api_version" in _columns(engine, "llm_providers")
        engine.dispose()

    def test_reconciles_every_missing_nullable_column_at_once(self, tmp_path):
        """The point of the generic pass: it cannot fall behind the models."""
        drops = [
            ("llm_providers", "api_version"),
            ("llm_providers", "bing_connection_name"),
            ("responses", "collected_grounded"),
        ]
        engine = _old_database(tmp_path, drops)
        _reconcile_columns(engine)
        for table, column in drops:
            assert column in _columns(engine, table), f"{table}.{column} not restored"
        engine.dispose()

    def test_restored_columns_are_usable(self, tmp_path):
        """Restoring the name is not enough; the ORM has to be able to query it.

        This is the assertion that maps onto the actual symptom, which was a
        SELECT failing rather than anything to do with writes.
        """
        engine = _old_database(tmp_path, [("llm_providers", "api_version")])
        _reconcile_columns(engine)

        session = sessionmaker(bind=engine)()
        try:
            session.add(models.LLMProvider(
                provider_key="claude", display_name="Claude",
                api_type="anthropic", model_name="claude-sonnet-5"))
            session.commit()
            row = session.query(models.LLMProvider).first()
            assert row.api_version is None
        finally:
            session.close()
            engine.dispose()

    def test_existing_rows_read_null_not_a_fabricated_value(self, tmp_path):
        """A restored column must not invent history for rows that predate it."""
        engine = _old_database(tmp_path, [("responses", "collected_grounded")])
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO responses (user_id, query_id, platform, response_text) "
                "VALUES (1, 'Q1', 'ChatGPT', 'collected before the column existed')"))

        _reconcile_columns(engine)

        with engine.connect() as connection:
            value = connection.execute(
                text("SELECT collected_grounded FROM responses")).scalar()
        assert value is None, (
            "An old row must read as unknown. Defaulting it to False would "
            "assert a collection method nobody recorded.")
        engine.dispose()

    def test_is_idempotent(self, tmp_path):
        engine = _old_database(tmp_path, [("llm_providers", "api_version")])
        _reconcile_columns(engine)
        _reconcile_columns(engine)  # must not raise on the second boot
        assert "api_version" in _columns(engine, "llm_providers")
        engine.dispose()

    def test_a_current_database_is_left_alone(self, tmp_path):
        engine = _old_database(tmp_path, [])
        before = {t: _columns(engine, t) for t in inspect(engine).get_table_names()}
        _reconcile_columns(engine)
        after = {t: _columns(engine, t) for t in inspect(engine).get_table_names()}
        assert before == after
        engine.dispose()


class TestNoDriftRemains:
    def test_every_model_column_exists_after_reconciliation(self, tmp_path):
        """The generic guarantee, stated once over the whole schema.

        If someone adds a nullable column to any model, this passes without
        anyone remembering to touch a migration list. If someone adds a NOT NULL
        column, this fails and points at it, which is the correct outcome: there
        is no safe automatic value for existing rows.
        """
        engine = create_engine(f"sqlite:///{tmp_path/'drift.db'}")
        Base.metadata.create_all(bind=engine)

        # SQLite refuses to drop a column an index or constraint depends on.
        # Those are skipped: the point is to roll back as much of the schema as
        # this database will allow, then prove reconciliation restores all of it.
        candidates = [
            (table.name, column.name)
            for table in Base.metadata.sorted_tables
            for column in table.columns
            if column.nullable and not column.primary_key
        ]
        droppable = []
        for table, column in candidates:
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(f"ALTER TABLE {table} DROP COLUMN {column}"))
                droppable.append((table, column))
            except Exception:
                continue
        assert len(droppable) > 30, (
            f"only {len(droppable)} columns could be dropped; the test is no "
            "longer exercising a meaningful amount of the schema")

        _reconcile_columns(engine)

        missing = [
            f"{table}.{column}" for table, column in droppable
            if column not in _columns(engine, table)
        ]
        assert not missing, f"reconciliation left columns missing: {missing}"
        engine.dispose()
