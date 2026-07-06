"""
Tests for the redirect-based OAuth flow endpoints and configuration.

Covers:
- /auth/config returns auth_flow_type and auto_login fields
- /auth/google/authorize and /auth/microsoft/authorize redirect behavior
- /auth/google/callback and /auth/microsoft/callback state validation
- PKCE code_verifier/code_challenge flow for Microsoft
- Guard: redirect endpoints reject when AUTH_FLOW_TYPE != "redirect"
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


class TestRedirectGuard:
    """Redirect endpoints reject when AUTH_FLOW_TYPE != 'redirect'."""

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "popup")
    def test_google_authorize_rejects_popup_mode(self, client):
        resp = client.get("/auth/google/authorize", follow_redirects=False)
        assert resp.status_code == 400
        assert "not enabled" in resp.json()["detail"]

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "popup")
    def test_microsoft_authorize_rejects_popup_mode(self, client):
        resp = client.get("/auth/microsoft/authorize", follow_redirects=False)
        assert resp.status_code == 400
        assert "not enabled" in resp.json()["detail"]


class TestGoogleAuthorize:
    """Tests for GET /auth/google/authorize."""

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.GOOGLE_CLIENT_ID", "google-test-id")
    @patch("app.routers.auth.GOOGLE_CLIENT_SECRET", "google-test-secret")
    def test_redirects_to_google(self, client):
        resp = client.get("/auth/google/authorize", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "accounts.google.com/o/oauth2/v2/auth" in location
        assert "google-test-id" in location
        assert "state=" in location

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.GOOGLE_CLIENT_ID", "google-test-id")
    @patch("app.routers.auth.GOOGLE_CLIENT_SECRET", "google-test-secret")
    def test_sets_state_cookie(self, client):
        resp = client.get("/auth/google/authorize", follow_redirects=False)
        assert "oauth_state" in resp.cookies

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.GOOGLE_CLIENT_ID", "google-test-id")
    @patch("app.routers.auth.GOOGLE_CLIENT_SECRET", None)
    def test_rejects_without_secret(self, client):
        resp = client.get("/auth/google/authorize", follow_redirects=False)
        assert resp.status_code == 500
        assert "not fully configured" in resp.json()["detail"]


class TestMicrosoftAuthorize:
    """Tests for GET /auth/microsoft/authorize (PKCE)."""

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.MICROSOFT_CLIENT_ID", "ms-test-id")
    @patch("app.routers.auth.OIDC_DISCOVERY_URL", "https://login.microsoftonline.com/test-tenant/v2.0/.well-known/openid-configuration")
    def test_redirects_to_microsoft(self, client):
        resp = client.get("/auth/microsoft/authorize", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "login.microsoftonline.com/test-tenant/oauth2/v2.0/authorize" in location
        assert "ms-test-id" in location

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.MICROSOFT_CLIENT_ID", "ms-test-id")
    @patch("app.routers.auth.OIDC_DISCOVERY_URL", "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration")
    def test_includes_pkce_challenge(self, client):
        resp = client.get("/auth/microsoft/authorize", follow_redirects=False)
        location = resp.headers["location"]
        assert "code_challenge=" in location
        assert "code_challenge_method=S256" in location

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.MICROSOFT_CLIENT_ID", "ms-test-id")
    @patch("app.routers.auth.OIDC_DISCOVERY_URL", "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration")
    def test_sets_state_and_verifier_cookies(self, client):
        resp = client.get("/auth/microsoft/authorize", follow_redirects=False)
        assert "oauth_state" in resp.cookies
        assert "oauth_verifier" in resp.cookies

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.MICROSOFT_CLIENT_ID", None)
    def test_rejects_without_client_id(self, client):
        resp = client.get("/auth/microsoft/authorize", follow_redirects=False)
        assert resp.status_code == 500
        assert "missing client ID" in resp.json()["detail"]

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.MICROSOFT_CLIENT_ID", "ms-test-id")
    @patch("app.routers.auth.OIDC_DISCOVERY_URL", "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration")
    def test_works_without_client_secret(self, client):
        """PKCE flow should work even without MICROSOFT_CLIENT_SECRET."""
        with patch("app.routers.auth.MICROSOFT_CLIENT_SECRET", None):
            resp = client.get("/auth/microsoft/authorize", follow_redirects=False)
            assert resp.status_code == 302


class TestGoogleCallback:
    """Tests for GET /auth/google/callback state validation."""

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    def test_rejects_invalid_state(self, client):
        client.cookies.set("oauth_state", "valid-state")
        resp = client.get(
            "/auth/google/callback?code=test-code&state=wrong-state",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "Invalid OAuth state" in resp.json()["detail"]

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    def test_rejects_missing_state_cookie(self, client):
        resp = client.get(
            "/auth/google/callback?code=test-code&state=some-state",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "Invalid OAuth state" in resp.json()["detail"]


class TestMicrosoftCallback:
    """Tests for GET /auth/microsoft/callback state and PKCE validation."""

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    def test_rejects_invalid_state(self, client):
        client.cookies.set("oauth_state", "valid-state")
        client.cookies.set("oauth_verifier", "test-verifier")
        resp = client.get(
            "/auth/microsoft/callback?code=test-code&state=wrong-state",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "Invalid OAuth state" in resp.json()["detail"]

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    def test_rejects_missing_verifier(self, client):
        client.cookies.set("oauth_state", "valid-state")
        resp = client.get(
            "/auth/microsoft/callback?code=test-code&state=valid-state",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "Missing PKCE verifier" in resp.json()["detail"]

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.MICROSOFT_CLIENT_ID", "ms-test-id")
    @patch("app.routers.auth.MICROSOFT_CLIENT_SECRET", None)
    @patch("app.routers.auth.OIDC_DISCOVERY_URL", "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration")
    def test_token_exchange_sends_verifier_without_secret(self, client):
        """When client_secret is None, the token exchange should include
        code_verifier but NOT client_secret."""
        client.cookies.set("oauth_state", "valid-state")
        client.cookies.set("oauth_verifier", "test-verifier-value")

        with patch("app.routers.auth.http_requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"id_token": "fake-jwt"}
            mock_post.return_value = mock_resp

            with patch("app.routers.auth.verify_microsoft_token") as mock_verify:
                mock_verify.return_value = {
                    "email": "user@test.com",
                    "name": "Test User",
                    "microsoft_id": "ms-123",
                    "email_verified": True,
                }
                with patch("app.routers.auth.get_or_create_oauth_user") as mock_create:
                    mock_user = MagicMock()
                    mock_user.is_active = True
                    mock_user.id = 1
                    mock_create.return_value = mock_user

                    with patch("app.routers.auth.get_site_url", return_value="http://localhost:5173"):
                        resp = client.get(
                            "/auth/microsoft/callback?code=test-code&state=valid-state",
                            follow_redirects=False,
                        )

            # Verify the token exchange request
            call_kwargs = mock_post.call_args
            posted_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
            assert posted_data["code_verifier"] == "test-verifier-value"
            assert "client_secret" not in posted_data

        assert resp.status_code == 302
        assert "token=" in resp.headers["location"]

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.MICROSOFT_CLIENT_ID", "ms-test-id")
    @patch("app.routers.auth.MICROSOFT_CLIENT_SECRET", "ms-secret")
    @patch("app.routers.auth.OIDC_DISCOVERY_URL", "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration")
    def test_token_exchange_includes_secret_when_available(self, client):
        """When client_secret IS set, both code_verifier and client_secret are sent."""
        client.cookies.set("oauth_state", "valid-state")
        client.cookies.set("oauth_verifier", "test-verifier-value")

        with patch("app.routers.auth.http_requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"id_token": "fake-jwt"}
            mock_post.return_value = mock_resp

            with patch("app.routers.auth.verify_microsoft_token") as mock_verify:
                mock_verify.return_value = {
                    "email": "user@test.com",
                    "name": "Test User",
                    "microsoft_id": "ms-123",
                    "email_verified": True,
                }
                with patch("app.routers.auth.get_or_create_oauth_user") as mock_create:
                    mock_user = MagicMock()
                    mock_user.is_active = True
                    mock_user.id = 1
                    mock_create.return_value = mock_user

                    with patch("app.routers.auth.get_site_url", return_value="http://localhost:5173"):
                        resp = client.get(
                            "/auth/microsoft/callback?code=test-code&state=valid-state",
                            follow_redirects=False,
                        )

            call_kwargs = mock_post.call_args
            posted_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
            assert posted_data["code_verifier"] == "test-verifier-value"
            assert posted_data["client_secret"] == "ms-secret"

        assert resp.status_code == 302


class TestGoogleCallbackFullFlow:
    """End-to-end test for Google callback with mocked token exchange."""

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.GOOGLE_CLIENT_ID", "google-test-id")
    @patch("app.routers.auth.GOOGLE_CLIENT_SECRET", "google-secret")
    def test_successful_google_callback(self, client):
        client.cookies.set("oauth_state", "valid-state")

        with patch("app.routers.auth.http_requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"id_token": "fake-google-jwt"}
            mock_post.return_value = mock_resp

            with patch("app.routers.auth.verify_google_token") as mock_verify:
                mock_verify.return_value = {
                    "email": "user@gmail.com",
                    "name": "Test User",
                    "google_id": "g-123",
                    "email_verified": True,
                    "picture": None,
                }
                with patch("app.routers.auth.get_or_create_oauth_user") as mock_create:
                    mock_user = MagicMock()
                    mock_user.is_active = True
                    mock_user.id = 42
                    mock_create.return_value = mock_user

                    with patch("app.routers.auth.get_site_url", return_value="http://localhost:5173"):
                        resp = client.get(
                            "/auth/google/callback?code=google-code&state=valid-state",
                            follow_redirects=False,
                        )

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith("http://localhost:5173/login/callback?token=")

    @patch("app.routers.auth.AUTH_FLOW_TYPE", "redirect")
    @patch("app.routers.auth.GOOGLE_CLIENT_ID", "google-test-id")
    @patch("app.routers.auth.GOOGLE_CLIENT_SECRET", "google-secret")
    def test_inactive_user_redirects_with_error(self, client):
        client.cookies.set("oauth_state", "valid-state")

        with patch("app.routers.auth.http_requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"id_token": "fake-google-jwt"}
            mock_post.return_value = mock_resp

            with patch("app.routers.auth.verify_google_token") as mock_verify:
                mock_verify.return_value = {
                    "email": "user@gmail.com",
                    "name": "Test User",
                    "google_id": "g-123",
                    "email_verified": True,
                    "picture": None,
                }
                with patch("app.routers.auth.get_or_create_oauth_user") as mock_create:
                    mock_user = MagicMock()
                    mock_user.is_active = False
                    mock_create.return_value = mock_user

                    with patch("app.routers.auth.get_site_url", return_value="http://localhost:5173"):
                        resp = client.get(
                            "/auth/google/callback?code=google-code&state=valid-state",
                            follow_redirects=False,
                        )

        assert resp.status_code == 307  # RedirectResponse default for non-explicit status
        location = resp.headers["location"]
        assert "error=account_inactive" in location
