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


@pytest.fixture(scope="function")
def golden_db_with_stored_analytics(golden_db):
    """Golden database plus batch_analytics rows written by the CURRENT code.

    Opt-in, because those rows are "what the app stored", not ground truth. The
    reconciliation harness needs them since the Dashboard serves several fields
    straight off BatchAnalytics (app/routers/analytics.py:254-274).
    """
    from tests.fixtures.golden_dataset import seed_batch_analytics

    seed_batch_analytics(golden_db)
    return golden_db


@pytest.fixture(scope="function")
def golden_client(golden_session_factory):
    """TestClient wired to the golden database.

    Follows the override pattern established in tests/test_responses_router.py:82.
    get_current_user takes the request's session via Depends so the User stays
    attached for the life of the request.
    """
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app import models
    from app.auth import get_current_user
    from app.database import get_db
    from app.main import app
    from app.utils.brand_access import get_active_brand_id
    from tests.fixtures.golden_dataset import BRAND_1_ID, USER_1_ID

    def override_get_db():
        db = golden_session_factory()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_user(db: Session = Depends(get_db)):
        return db.query(models.User).filter(models.User.id == USER_1_ID).first()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_active_brand_id] = lambda: BRAND_1_ID

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
