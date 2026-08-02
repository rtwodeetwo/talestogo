"""
Tests for POST /auth/change-password.

Covers the happy path plus the failure modes that all used to be impossible to
tell apart before this endpoint existed: wrong current password, an OAuth-only
account with no local password, a too-short new password, and a no-op change.
"""
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.auth import get_current_user, get_password_hash, verify_password
from app.database import Base, get_db
from app.main import app

USER_ID = 1


@pytest.fixture()
def session_factory():
    """Fresh in-memory DB seeded with one password-based user."""
    uri = "sqlite:///file:changepw?mode=memory&cache=shared&uri=true"
    engine = create_engine(uri, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    seed = factory()
    try:
        seed.add(models.User(
            id=USER_ID,
            email="admin@example.com",
            full_name="Admin",
            hashed_password=get_password_hash("original-pw"),
            is_admin=True,
            is_active=True,
        ))
        seed.commit()
    finally:
        seed.close()

    yield factory

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_user(db: Session = Depends(get_db)):
        return db.query(models.User).filter(models.User.id == USER_ID).first()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def test_change_password_success(client, session_factory):
    resp = client.post("/auth/change-password", json={
        "current_password": "original-pw",
        "new_password": "brand-new-pw",
    })
    assert resp.status_code == 200

    # The new hash must actually verify against the new password.
    db = session_factory()
    try:
        user = db.query(models.User).filter(models.User.id == USER_ID).first()
        assert verify_password("brand-new-pw", user.hashed_password)
        assert not verify_password("original-pw", user.hashed_password)
    finally:
        db.close()


def test_wrong_current_password_rejected(client):
    resp = client.post("/auth/change-password", json={
        "current_password": "not-the-password",
        "new_password": "brand-new-pw",
    })
    assert resp.status_code == 400
    assert "current password is incorrect" in resp.json()["detail"].lower()


def test_new_password_too_short_rejected(client):
    resp = client.post("/auth/change-password", json={
        "current_password": "original-pw",
        "new_password": "short",
    })
    assert resp.status_code == 422  # Pydantic min_length


def test_same_password_rejected(client):
    resp = client.post("/auth/change-password", json={
        "current_password": "original-pw",
        "new_password": "original-pw",
    })
    assert resp.status_code == 400
    assert "different" in resp.json()["detail"].lower()


def test_oauth_only_account_rejected(client, session_factory):
    # An account with no local password (created via OAuth) cannot change one.
    db = session_factory()
    try:
        user = db.query(models.User).filter(models.User.id == USER_ID).first()
        user.hashed_password = None
        user.oauth_provider = "microsoft"
        db.commit()
    finally:
        db.close()

    resp = client.post("/auth/change-password", json={
        "current_password": "anything",
        "new_password": "brand-new-pw",
    })
    assert resp.status_code == 400
    assert "identity provider" in resp.json()["detail"].lower()
