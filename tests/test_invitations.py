"""
Tests for the admin invitation flow with local (email/password) auth.

Before this flow was wired up, create_invitation_token() had zero call sites:
the admin UI created users with no password hash and no invitation token, and
the invitation email only mentioned OAuth. On an email/password-only
deployment an invited user therefore had no way to log in at all (reported by
LLNL, 2026-08). These tests pin down the full loop: invite mints a token,
the emailed link validates, accepting it sets the password, and the token
dies after use.
"""
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.auth import (
    create_invitation_token,
    get_current_admin_user,
    get_password_hash,
    verify_password,
)
from app.database import Base, get_db
from app.main import app
from app.routers import users as users_router

ADMIN_ID = 1


@pytest.fixture()
def session_factory():
    """Fresh in-memory DB seeded with one admin."""
    uri = "sqlite:///file:invitations?mode=memory&cache=shared&uri=true"
    engine = create_engine(uri, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    seed = factory()
    try:
        seed.add(models.User(
            id=ADMIN_ID,
            email="admin@example.com",
            full_name="Admin",
            hashed_password=get_password_hash("admin-pw"),
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

    def override_admin(db: Session = Depends(get_db)):
        return db.query(models.User).filter(models.User.id == ADMIN_ID).first()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin_user] = override_admin
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def get_user(session_factory, email):
    db = session_factory()
    try:
        return db.query(models.User).filter(models.User.email == email).first()
    finally:
        db.close()


def invite(client, email="newuser@llnl.gov", full_name="New User"):
    return client.post("/admin/users/create-invite", json={
        "email": email,
        "full_name": full_name,
    })


def test_create_invite_mints_token_with_local_auth(client, session_factory, monkeypatch):
    monkeypatch.setattr(users_router, "ENABLE_LOCAL_AUTH", True)
    resp = invite(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["invitation_token"]
    assert "/invite/accept?token=" in body["invitation_url"]
    assert body["expires_at"] is not None

    user = get_user(session_factory, "newuser@llnl.gov")
    assert user.invitation_token == body["invitation_token"]
    assert user.invitation_expires_at is not None
    assert user.hashed_password is None
    assert user.is_active is True


def test_create_invite_oauth_only_mints_no_token(client, session_factory, monkeypatch):
    monkeypatch.setattr(users_router, "ENABLE_LOCAL_AUTH", False)
    resp = invite(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["invitation_token"] == ""
    assert "token=" not in body["invitation_url"]

    user = get_user(session_factory, "newuser@llnl.gov")
    assert user.invitation_token is None
    assert user.is_active is True


def test_full_accept_loop_sets_password_and_kills_token(client, session_factory, monkeypatch):
    monkeypatch.setattr(users_router, "ENABLE_LOCAL_AUTH", True)
    token = invite(client).json()["invitation_token"]

    # The emailed link validates
    resp = client.get(f"/invite/validate?token={token}")
    assert resp.status_code == 200
    assert resp.json()["email"] == "newuser@llnl.gov"

    # Accepting sets the password and returns a working access token
    resp = client.post("/invite/accept", json={"token": token, "password": "chosen-pw-123"})
    assert resp.status_code == 200
    assert resp.json()["access_token"]

    user = get_user(session_factory, "newuser@llnl.gov")
    assert verify_password("chosen-pw-123", user.hashed_password)
    assert user.is_active is True
    assert user.invitation_token is None

    # The user can now actually log in with email/password
    resp = client.post("/auth/login", json={
        "email": "newuser@llnl.gov", "password": "chosen-pw-123",
    })
    assert resp.status_code == 200

    # The token is dead: neither validate nor a second accept works
    assert client.get(f"/invite/validate?token={token}").status_code == 400
    resp = client.post("/invite/accept", json={"token": token, "password": "other-pw-456"})
    assert resp.status_code == 400
    assert "already been used" in resp.json()["detail"]


def test_expired_token_rejected(client, monkeypatch):
    monkeypatch.setattr(users_router, "ENABLE_LOCAL_AUTH", True)
    invite(client)
    expired, _ = create_invitation_token(
        email="newuser@llnl.gov", full_name="New User", expires_days=-1,
    )
    resp = client.post("/invite/accept", json={"token": expired, "password": "chosen-pw-123"})
    assert resp.status_code == 400


def test_mismatched_token_rejected(client, monkeypatch):
    """A structurally valid token that is not the one stored on the user fails."""
    monkeypatch.setattr(users_router, "ENABLE_LOCAL_AUTH", True)
    invite(client)
    # A different expiry guarantees a different JWT than the stored one
    other, _ = create_invitation_token(
        email="newuser@llnl.gov", full_name="New User", expires_days=3,
    )
    resp = client.get(f"/invite/validate?token={other}")
    assert resp.status_code == 400
    assert "Invalid invitation token" in resp.json()["detail"]


def test_send_invitation_email_contains_set_password_link(client, session_factory, monkeypatch):
    monkeypatch.setattr(users_router, "ENABLE_LOCAL_AUTH", True)
    invite(client)
    user = get_user(session_factory, "newuser@llnl.gov")

    sent = {}

    async def fake_send_email(to, subject, body):
        sent.update(to=to, subject=subject, body=body)

    import app.services.email_notifications as email_notifications
    monkeypatch.setattr(email_notifications, "send_email", fake_send_email)

    resp = client.post(f"/admin/users/{user.id}/send-invitation")
    assert resp.status_code == 200
    assert "/invite/accept?token=" in sent["body"]

    # The token in the email is the one now stored on the user (resends refresh it)
    refreshed = get_user(session_factory, "newuser@llnl.gov")
    assert refreshed.invitation_token in sent["body"]


def test_send_invitation_email_oauth_only_has_no_password_link(client, session_factory, monkeypatch):
    monkeypatch.setattr(users_router, "ENABLE_LOCAL_AUTH", False)
    monkeypatch.setattr(users_router, "ENABLE_GOOGLE_AUTH", True)
    monkeypatch.setattr(users_router, "GOOGLE_CLIENT_ID", "test-client-id")
    invite(client)
    user = get_user(session_factory, "newuser@llnl.gov")

    sent = {}

    async def fake_send_email(to, subject, body):
        sent.update(to=to, subject=subject, body=body)

    import app.services.email_notifications as email_notifications
    monkeypatch.setattr(email_notifications, "send_email", fake_send_email)

    resp = client.post(f"/admin/users/{user.id}/send-invitation")
    assert resp.status_code == 200
    assert "/invite/accept" not in sent["body"]
    assert "Google" in sent["body"]


def test_send_invitation_email_leads_with_sso_when_both_enabled(client, session_factory, monkeypatch):
    """
    On a deployment running both local auth and SSO (the default env), an
    invited lab user should be told to use their work account first, with the
    set-password link offered as the alternative. Leading with the password
    link sends Entra ID users down the wrong path.
    """
    monkeypatch.setattr(users_router, "ENABLE_LOCAL_AUTH", True)
    monkeypatch.setattr(users_router, "ENABLE_MICROSOFT_AUTH", True)
    monkeypatch.setattr(users_router, "MICROSOFT_CLIENT_ID", "test-client-id")
    invite(client, email="newuser@pnnl.gov")
    user = get_user(session_factory, "newuser@pnnl.gov")

    sent = {}

    async def fake_send_email(to, subject, body):
        sent.update(to=to, subject=subject, body=body)

    import app.services.email_notifications as email_notifications
    monkeypatch.setattr(email_notifications, "send_email", fake_send_email)

    resp = client.post(f"/admin/users/{user.id}/send-invitation")
    assert resp.status_code == 200

    body = sent["body"]
    # Both routes are offered...
    assert "Sign in with Microsoft" in body
    assert "/invite/accept?token=" in body
    # ...but the SSO instruction comes first.
    assert body.index("Sign in with Microsoft") < body.index("/invite/accept?token=")
    # Google is not advertised on a Microsoft-only deployment
    assert "Google" not in body
