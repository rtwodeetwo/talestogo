"""
Tests for /auth/config endpoint and OAuth security guards (email_verified, is_active).
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


class TestAuthConfig:
    """Tests for GET /auth/config response shape."""

    def test_config_includes_auth_flow_type(self, client):
        resp = client.get("/auth/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "auth_flow_type" in data
        assert data["auth_flow_type"] in ("popup", "redirect")

    def test_config_includes_auto_login(self, client):
        resp = client.get("/auth/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "auto_login" in data
        assert isinstance(data["auto_login"], bool)

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.AUTO_LOGIN_MICROSOFT", True)
    @patch("app.routers.auth.ENABLE_LOCAL_AUTH", False)
    @patch("app.routers.auth.ENABLE_MICROSOFT_AUTH", True)
    @patch("app.routers.auth.MICROSOFT_CLIENT_ID", "test-client-id")
    @patch("app.routers.auth.ENABLE_GOOGLE_AUTH", False)
    @patch("app.routers.auth.GOOGLE_CLIENT_ID", None)
    def test_auto_login_true_when_conditions_met(self, client):
        resp = client.get("/auth/config")
        data = resp.json()
        assert data["auto_login"] is True

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "popup")
    @patch("app.routers.auth.AUTO_LOGIN_MICROSOFT", True)
    @patch("app.routers.auth.ENABLE_LOCAL_AUTH", False)
    @patch("app.routers.auth.ENABLE_MICROSOFT_AUTH", True)
    @patch("app.routers.auth.MICROSOFT_CLIENT_ID", "test-client-id")
    @patch("app.routers.auth.ENABLE_GOOGLE_AUTH", False)
    @patch("app.routers.auth.GOOGLE_CLIENT_ID", None)
    def test_auto_login_false_when_popup_mode(self, client):
        resp = client.get("/auth/config")
        data = resp.json()
        assert data["auto_login"] is False

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.AUTO_LOGIN_MICROSOFT", True)
    @patch("app.routers.auth.ENABLE_LOCAL_AUTH", True)
    @patch("app.routers.auth.ENABLE_MICROSOFT_AUTH", True)
    @patch("app.routers.auth.MICROSOFT_CLIENT_ID", "test-client-id")
    @patch("app.routers.auth.ENABLE_GOOGLE_AUTH", False)
    @patch("app.routers.auth.GOOGLE_CLIENT_ID", None)
    def test_auto_login_false_when_local_auth_enabled(self, client):
        resp = client.get("/auth/config")
        data = resp.json()
        assert data["auto_login"] is False


class TestGoogleOAuthGuards:
    """Tests that POST /auth/google enforces email_verified and is_active."""

    @patch("app.routers.auth.verify_google_token")
    def test_rejects_unverified_email(self, mock_verify, client):
        mock_verify.return_value = {
            "email": "user@gmail.com",
            "name": "Test",
            "google_id": "g-1",
            "email_verified": False,
            "picture": None,
        }
        resp = client.post("/auth/google", json={"token": "fake-token"})
        assert resp.status_code == 400
        assert "not verified" in resp.json()["detail"].lower()

    @patch("app.routers.auth.get_or_create_oauth_user")
    @patch("app.routers.auth.verify_google_token")
    def test_rejects_inactive_user(self, mock_verify, mock_create, client):
        mock_verify.return_value = {
            "email": "user@gmail.com",
            "name": "Test",
            "google_id": "g-1",
            "email_verified": True,
            "picture": None,
        }
        mock_user = MagicMock()
        mock_user.is_active = False
        mock_create.return_value = mock_user
        resp = client.post("/auth/google", json={"token": "fake-token"})
        assert resp.status_code == 403
        assert "not active" in resp.json()["detail"].lower()


class TestMicrosoftOAuthGuards:
    """Tests that POST /auth/microsoft enforces email_verified and is_active."""

    @patch("app.routers.auth.verify_microsoft_token")
    def test_rejects_unverified_email(self, mock_verify, client):
        mock_verify.return_value = {
            "email": "user@corp.com",
            "name": "Test",
            "microsoft_id": "ms-1",
            "email_verified": False,
        }
        resp = client.post("/auth/microsoft", json={"token": "fake-token"})
        assert resp.status_code == 400
        assert "not verified" in resp.json()["detail"].lower()

    @patch("app.routers.auth.get_or_create_oauth_user")
    @patch("app.routers.auth.verify_microsoft_token")
    def test_rejects_inactive_user(self, mock_verify, mock_create, client):
        mock_verify.return_value = {
            "email": "user@corp.com",
            "name": "Test",
            "microsoft_id": "ms-1",
            "email_verified": True,
        }
        mock_user = MagicMock()
        mock_user.is_active = False
        mock_create.return_value = mock_user
        resp = client.post("/auth/microsoft", json={"token": "fake-token"})
        assert resp.status_code == 403
        assert "not active" in resp.json()["detail"].lower()
