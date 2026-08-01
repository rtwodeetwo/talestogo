"""
Shared pytest fixtures for the Tales test suite.

Before this file existed every test module built its own in-memory database.
The pattern here follows the one established in tests/test_crud.py: a named
shared-cache SQLite URI so that multiple connections (the test session and the
TestClient's request sessions) see the same in-memory database.

The golden fixtures below back the metric reconciliation suite. They are
deterministic by construction: every value in tests/fixtures/golden_dataset.py
is a literal, there is no randomness and no call to utcnow(), so the numbers in
tests/golden_expected.py can be hand-verified with a calculator.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base


@pytest.fixture(scope="function")
def golden_engine():
    """Engine bound to a fresh in-memory database holding the golden dataset."""
    import app.models  # noqa: F401 - registers the models on Base.metadata

    uri = "sqlite:///file:metricsgolden?mode=memory&cache=shared&uri=true"
    engine = create_engine(
        uri, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)

    from tests.fixtures.golden_dataset import seed_golden_dataset

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    seed = session_factory()
    try:
        seed_golden_dataset(seed)
        seed.commit()
    finally:
        seed.close()

    yield engine

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def golden_session_factory(golden_engine):
    """Session factory bound to the golden database."""
    return sessionmaker(autocommit=False, autoflush=False, bind=golden_engine)


@pytest.fixture(scope="function")
def golden_db(golden_session_factory):
    """A single session over the golden database, closed on teardown."""
    db = golden_session_factory()
    try:
        yield db
    finally:
        db.close()
