"""
Recording how each response was collected, and keeping "unknown" out of "no".

A grounded answer is what a model says after searching the web. An ungrounded
one is what it remembers from training. They are different measurements, and
switching between them moves every rate in metrics_core without anything about
the brand having changed. PPPL's own history has exactly this break in it: data
collected before July 2026 is ungrounded, after it is grounded.

The whole point of the column is that the break becomes a recorded fact instead
of something a person has to remember. So the tests that matter here are about
provenance surviving each hop: collection writes it, the export carries it, the
import can backfill it from a known switch date, the metrics report it, and the
investigation agent is handed it before it starts explaining a movement.

The third state does the real work. NULL means nobody recorded it, and folding
that into "ungrounded" would assert a method for an entire imported history that
nobody actually checked.
"""
import csv
import io

import pytest

from app import models
from app.services import metrics_core as mc
from app.services import metrics_query as mq
from tests.fixtures.golden_dataset import BATCH_1_ID, BATCH_2_ID, BRAND_1_ID, USER_1_ID


def _record(response_id, grounded, branded=False, analyzed=True):
    return mc.ResponseRecord(
        response_id=response_id, query_id="Q1", platform="ChatGPT",
        brand_mentioned="Yes", brand_position="Leader", sentiment="Positive",
        analyzed=analyzed, is_branded_query=branded,
        collected_grounded=grounded,
    )


class TestGroundingComposition:
    def test_counts_the_three_states_separately(self):
        pop = mc.MetricPopulation(rows=[
            _record(1, True), _record(2, True), _record(3, False), _record(4, None),
        ])
        assert mc.grounding_composition(pop) == {
            "grounded": 2, "ungrounded": 1, "unknown": 1}

    def test_unknown_is_never_folded_into_ungrounded(self):
        """The distinction the column exists for."""
        pop = mc.MetricPopulation(rows=[_record(1, None), _record(2, None)])
        composition = mc.grounding_composition(pop)
        assert composition["unknown"] == 2
        assert composition["ungrounded"] == 0

    def test_only_counts_rows_the_metrics_counted(self):
        """The question is what the published numbers were made from, so rows
        excluded from the metrics must not appear in their provenance either."""
        pop = mc.MetricPopulation(rows=[
            _record(1, True),
            _record(2, True, branded=True),      # excluded: brand named in query
            _record(3, True, analyzed=False),    # excluded: never analyzed
        ])
        assert mc.grounding_composition(pop)["grounded"] == 1
        assert sum(mc.grounding_composition(pop).values()) == len(pop.organic_rows())

    def test_empty_population_reports_zeroes(self):
        assert mc.grounding_composition(mc.MetricPopulation()) == {
            "grounded": 0, "ungrounded": 0, "unknown": 0}

    def test_data_quality_carries_it(self):
        pop = mc.MetricPopulation(rows=[_record(1, True), _record(2, False)])
        quality = mc.data_quality(pop)
        assert quality["grounding"] == {"grounded": 1, "ungrounded": 1, "unknown": 0}

    def test_data_quality_row_accounting_still_holds(self):
        """The nested key must not disturb the flat exclusion arithmetic."""
        pop = mc.MetricPopulation(rows=[
            _record(1, True), _record(2, None, branded=True),
            _record(3, False, analyzed=False),
        ])
        quality = mc.data_quality(pop)
        accounted = (quality["counted"] + quality["branded_excluded"]
                     + quality["unanalyzed_excluded"] + quality["invalid_enum_excluded"]
                     + quality["orphan_query_excluded"])
        assert accounted == quality["total_rows"]


class TestItSurvivesTheQueryLayer:
    def test_the_column_reaches_the_population(self, golden_db):
        """The golden fixture predates the column, so everything is unknown,
        which is exactly what an untagged history should look like."""
        population = mq.resolve(
            golden_db, mq.MetricScope.for_batch(USER_1_ID, BRAND_1_ID, BATCH_1_ID))
        composition = mc.grounding_composition(population)
        assert composition["unknown"] == len(population.organic_rows())
        assert composition["grounded"] == 0

    def test_a_tagged_batch_reports_as_grounded(self, golden_db):
        golden_db.query(models.Response).filter(
            models.Response.batch_id == BATCH_2_ID
        ).update({"collected_grounded": True})
        golden_db.commit()

        population = mq.resolve(
            golden_db, mq.MetricScope.for_batch(USER_1_ID, BRAND_1_ID, BATCH_2_ID))
        composition = mc.grounding_composition(population)
        assert composition["grounded"] == len(population.organic_rows())
        assert composition["unknown"] == 0


class TestTheInvestigationSeesIt:
    def test_a_method_change_is_visible_in_the_evidence(self, golden_db):
        """The scenario PPPL is about to create: an ungrounded month compared
        against a grounded one. The agent is told to check this before it
        attributes anything to reputation, so it has to be in the evidence."""
        from app.services.investigation import evidence
        from app.services.investigation.scope import build_scope

        golden_db.query(models.Response).filter(
            models.Response.batch_id == BATCH_1_ID
        ).update({"collected_grounded": False})
        golden_db.query(models.Response).filter(
            models.Response.batch_id == BATCH_2_ID
        ).update({"collected_grounded": True})
        golden_db.commit()

        scope = build_scope(golden_db, USER_1_ID, BRAND_1_ID, "batch")
        comparison = evidence.compare_scopes(golden_db, scope)

        assert comparison["current"]["data_quality"]["grounding"]["grounded"] > 0
        assert comparison["previous"]["data_quality"]["grounding"]["ungrounded"] > 0
        assert comparison["current"]["data_quality"]["grounding"]["ungrounded"] == 0

        # And the agent is told what to do with it, not left to infer it.
        assert any("grounding" in note for note in comparison["notes"])


class TestTheExportColumn:
    def _rows(self, client):
        response = client.get("/exports/responses.csv", params={"period": "all"})
        assert response.status_code == 200, response.text
        return list(csv.DictReader(io.StringIO(response.text)))

    def test_unrecorded_reads_as_unknown_not_no(self, golden_client):
        rows = self._rows(golden_client)
        assert rows
        assert {row["Grounded"] for row in rows} == {"Unknown"}

    def test_recorded_values_come_through(self, golden_client, golden_db):
        golden_db.query(models.Response).filter(
            models.Response.batch_id == BATCH_1_ID
        ).update({"collected_grounded": False})
        golden_db.query(models.Response).filter(
            models.Response.batch_id == BATCH_2_ID
        ).update({"collected_grounded": True})
        golden_db.commit()

        values = {row["Grounded"] for row in self._rows(golden_client)}
        assert values == {"Yes", "No"}


class TestImportBackfill:
    """--grounded-from, which is how PPPL's July 2026 switch gets recorded."""

    @staticmethod
    def _resolve(*args):
        from scripts.admin.import_brand_data import resolve_grounded
        return resolve_grounded(*args)

    def test_a_recorded_value_beats_the_date_inference(self):
        """A fact from collection time outranks a guess about a deployment."""
        import datetime
        july = datetime.datetime(2026, 7, 1)
        # Collected in June but recorded as grounded: trust the record.
        assert self._resolve(True, datetime.datetime(2026, 6, 15), july) is True
        assert self._resolve(False, datetime.datetime(2026, 8, 15), july) is False

    def test_the_switch_date_splits_an_untagged_history(self):
        import datetime
        july = datetime.datetime(2026, 7, 1)
        assert self._resolve(None, datetime.datetime(2026, 6, 30), july) is False
        assert self._resolve(None, datetime.datetime(2026, 7, 1), july) is True
        assert self._resolve(None, datetime.datetime(2026, 9, 2), july) is True

    def test_without_a_date_everything_stays_unknown(self):
        """Refusing to guess. Marking a whole history 'ungrounded' because
        nobody said otherwise would invent its provenance."""
        import datetime
        assert self._resolve(None, datetime.datetime(2026, 6, 30), None) is None

    def test_a_response_with_no_timestamp_stays_unknown(self):
        import datetime
        assert self._resolve(None, None, datetime.datetime(2026, 7, 1)) is None


class TestExportAgainstAnOlderDatabase:
    """The migration reads a deployment that predates this column.

    Selecting a column the source table does not have fails the entire export,
    which is the difference between a migration that runs and one that stops on
    an unhelpful "column does not exist".
    """

    def test_responses_can_be_read_when_the_column_is_absent(self, tmp_path):
        from sqlalchemy import create_engine, inspect as sa_inspect, text
        from sqlalchemy.orm import defer, sessionmaker

        from app.database import Base

        path = tmp_path / "older.db"
        engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(bind=engine)

        # Roll the schema back to before the column existed.
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE responses DROP COLUMN collected_grounded"))

        columns = {c["name"] for c in sa_inspect(engine).get_columns("responses")}
        assert "collected_grounded" not in columns

        session = sessionmaker(bind=engine)()
        try:
            query = session.query(models.Response).options(
                defer(models.Response.collected_grounded))
            assert query.all() == []
            with pytest.raises(Exception):
                # Without the defer the same query is an error, which is what
                # the export guards against.
                session.query(models.Response).all()
        finally:
            session.close()
            engine.dispose()
