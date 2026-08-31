"""
Tests for bcrypt's 72-byte password limit.

bcrypt raises ValueError on anything longer, and neither the hasher nor the
verifier guarded against it. A password over 72 bytes therefore produced an
unhandled 500: on /auth/login, and on /invite/accept, where it meant an invited
user pasting a password-manager passphrase could not complete their invitation
at all. Found by the OWASP ZAP DAST scan on 2026-08-31, which fuzzed the login
password with an 83-byte payload and reported the resulting connection close as
a "Format String Error".

The limit is on UTF-8 bytes, not characters, so the emoji cases matter: they
are short enough to pass a character-based max_length and still blow the limit.
"""
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.auth import (
    BCRYPT_MAX_PASSWORD_BYTES,
    create_invitation_token,
    get_password_hash,
    verify_password,
)
from app.database import Base, get_db
from app.main import app

EMAIL = "user@example.com"
INVITEE = "invitee@example.com"
PASSWORD = "original-pw"

# 83 bytes: the exact payload ZAP submitted as the login password
ZAP_PAYLOAD = "ZAP" + "%n%s" * 20
# 20 characters, 80 bytes: passes a character-based length check, not a byte one
EMOJI_PASSWORD = "\U0001F600" * 20


@pytest.fixture()
def session_factory():
    uri = "sqlite:///file:pwlimits?mode=memory&cache=shared&uri=true"
    engine = create_engine(uri, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    token, expires_at = create_invitation_token(email=INVITEE, full_name="Invitee")
    seed = factory()
    try:
        seed.add(models.User(
            email=EMAIL,
            full_name="User",
            hashed_password=get_password_hash(PASSWORD),
            is_active=True,
        ))
        seed.add(models.User(
            email=INVITEE,
            full_name="Invitee",
            is_active=True,
            is_invited=True,
            invitation_token=token,
            invitation_expires_at=expires_at,
        ))
        seed.commit()
    finally:
        seed.close()

    factory.invitation_token = token
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

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def login(client, password):
    return client.post("/auth/login", json={"email": EMAIL, "password": password})


@pytest.mark.parametrize("password", [
    "x" * (BCRYPT_MAX_PASSWORD_BYTES + 1),
    ZAP_PAYLOAD,
    EMOJI_PASSWORD,
])
def test_overlong_login_password_is_401_not_500(client, password):
    """An over-length password is wrong, not a server error."""
    assert login(client, password).status_code == 401


def test_login_still_works_at_the_boundary(client):
    assert login(client, PASSWORD).status_code == 200
    assert login(client, "x" * BCRYPT_MAX_PASSWORD_BYTES).status_code == 401


@pytest.mark.parametrize("password,reason", [
    ("", "empty"),
    ("short", "under the 8 character minimum"),
    ("x" * (BCRYPT_MAX_PASSWORD_BYTES + 1), "over the byte limit"),
    (EMOJI_PASSWORD, "20 characters but 80 bytes"),
])
def test_invite_accept_rejects_unusable_password(client, session_factory, password, reason):
    """
    InvitationAccept had no length constraint at all, so these reached the
    hasher: the long ones as a 500, the empty one as a stored empty password.
    """
    resp = client.post("/invite/accept", json={
        "token": session_factory.invitation_token,
        "password": password,
    })
    assert resp.status_code == 422, f"{reason} should be rejected: got {resp.status_code}"


def test_invite_accept_succeeds_with_a_usable_password(client, session_factory):
    resp = client.post("/invite/accept", json={
        "token": session_factory.invitation_token,
        "password": "a-perfectly-good-password",
    })
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_hasher_refuses_rather_than_silently_truncating():
    """
    Truncating would store only the first 72 bytes while letting the user
    believe the whole passphrase protects the account.
    """
    with pytest.raises(ValueError):
        get_password_hash("x" * (BCRYPT_MAX_PASSWORD_BYTES + 1))
    with pytest.raises(ValueError):
        get_password_hash(EMOJI_PASSWORD)


def test_verifier_returns_false_for_overlong_input():
    stored = get_password_hash(PASSWORD)
    assert verify_password(PASSWORD, stored) is True
    assert verify_password("x" * (BCRYPT_MAX_PASSWORD_BYTES + 1), stored) is False
    assert verify_password(EMOJI_PASSWORD, stored) is False
