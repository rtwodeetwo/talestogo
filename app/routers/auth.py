"""
Authentication Router
Handles user registration, login (email/password, Google, Microsoft OAuth), and profile management
"""
import os
import secrets
import hashlib
import base64
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from typing import List
import requests as http_requests

from .. import crud, models, schemas
from ..database import get_db
from ..auth import (
    get_current_user,
    authenticate_user,
    create_access_token,
    get_password_hash,
    verify_google_token,
    verify_microsoft_token,
    get_or_create_oauth_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ENABLE_LOCAL_AUTH,
    ENABLE_MICROSOFT_AUTH,
    ENABLE_GOOGLE_AUTH,
    MICROSOFT_CLIENT_ID,
    MICROSOFT_CLIENT_SECRET,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    OIDC_DISCOVERY_URL,
    AUTH_FLOW_TYPE,
    AUTO_LOGIN_MICROSOFT,
)
from ..services.site_config import get_site_url

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


def _is_local_dev(request: Request) -> bool:
    """True when running on localhost (no TLS expected)."""
    base = str(request.base_url)
    return "localhost" in base or "127.0.0.1" in base


def _get_redirect_uri(request: Request, path: str) -> str:
    """Build an absolute redirect URI, forcing HTTPS in production.

    Reverse proxies (Azure Container Apps, AWS ALB, nginx) terminate TLS and
    forward requests over plain HTTP. The request.base_url therefore appears as
    http://, but OAuth providers require the registered redirect URI to match
    the public HTTPS origin exactly.
    """
    base = str(request.base_url).rstrip("/")
    if base.startswith("http://") and not _is_local_dev(request):
        base = "https://" + base[len("http://"):]
    return f"{base}{path}"


@router.get("/config", response_model=schemas.AuthConfig)
def get_auth_config():
    """
    Return enabled authentication methods for the frontend.
    This endpoint is public (no authentication required).
    Labs can configure which auth methods are available via environment variables.
    """
    # Derive MSAL authority from OIDC discovery URL
    # e.g. "https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration"
    #   -> "https://login.microsoftonline.com/<tenant>"
    microsoft_authority = None
    if ENABLE_MICROSOFT_AUTH and OIDC_DISCOVERY_URL:
        # Strip /v2.0/.well-known/openid-configuration (or similar suffixes)
        authority = OIDC_DISCOVERY_URL.split("/v2.0/")[0]
        if authority != OIDC_DISCOVERY_URL:
            microsoft_authority = authority

    ms_enabled = ENABLE_MICROSOFT_AUTH and bool(MICROSOFT_CLIENT_ID)
    google_enabled = ENABLE_GOOGLE_AUTH and bool(GOOGLE_CLIENT_ID)

    # auto_login: skip login page and redirect straight to Microsoft
    auto_login = (
        AUTO_LOGIN_MICROSOFT
        and AUTH_FLOW_TYPE == "redirect"
        and ms_enabled
        and not ENABLE_LOCAL_AUTH
        and not google_enabled
    )

    return schemas.AuthConfig(
        local_auth_enabled=ENABLE_LOCAL_AUTH,
        microsoft_auth_enabled=ms_enabled,
        google_auth_enabled=google_enabled,
        microsoft_client_id=MICROSOFT_CLIENT_ID if ENABLE_MICROSOFT_AUTH else None,
        microsoft_authority=microsoft_authority,
        google_client_id=GOOGLE_CLIENT_ID if ENABLE_GOOGLE_AUTH else None,
        auth_flow_type=AUTH_FLOW_TYPE,
        auto_login=auto_login,
    )


@router.post("/register", response_model=schemas.User, status_code=201)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user (invite-only).
    User account will be inactive until admin approves.
    """
    # Check if user already exists
    db_user = crud.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Hash password and create user
    hashed_password = get_password_hash(user.password)
    new_user = crud.create_user(db=db, user=user, hashed_password=hashed_password, is_invited=False)
    return new_user


@router.post("/login", response_model=schemas.Token)
def login(user_credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    """
    Login with email and password.
    Returns JWT access token.
    """
    user = authenticate_user(db, email=user_credentials.email, password=user_credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active. Please contact admin for approval."
        )

    # Update last_login timestamp
    user.last_login = datetime.utcnow()
    db.commit()

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/google", response_model=schemas.Token)
def google_login(google_token: schemas.GoogleLogin, db: Session = Depends(get_db)):
    """
    Login with Google OAuth.
    Accepts Google ID token and returns JWT access token.
    Creates new user if doesn't exist (auto-activated).
    """
    # Verify Google token and get user info
    google_info = verify_google_token(google_token.token)

    # Ensure email is verified
    if not google_info.get('email_verified'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email not verified with Google"
        )

    # Get or create user
    user = get_or_create_oauth_user(db, google_info)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active. Please contact admin for approval."
        )

    # Update last_login timestamp
    user.last_login = datetime.utcnow()
    db.commit()

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/microsoft", response_model=schemas.Token)
def microsoft_login(microsoft_token: schemas.MicrosoftLogin, db: Session = Depends(get_db)):
    """
    Login with Microsoft OAuth.
    Accepts Microsoft ID token and returns JWT access token.
    Creates new user if doesn't exist (auto-activated for admin).
    """
    # Verify Microsoft token and get user info
    microsoft_info = verify_microsoft_token(microsoft_token.token)

    # Ensure email is verified
    if not microsoft_info.get('email_verified'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email not verified with Microsoft"
        )

    # Get or create user
    user = get_or_create_oauth_user(db, microsoft_info, provider='microsoft')

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active. Please contact admin for approval."
        )

    # Update last_login timestamp
    user.last_login = datetime.utcnow()
    db.commit()

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


# --- Redirect-based OAuth Flow (Authorization Code) ---
# These endpoints are only active when AUTH_FLOW_TYPE=redirect.
# They implement a server-side code exchange so the browser never opens a popup.


@router.get("/google/authorize")
def google_authorize(request: Request):
    """Redirect user to Google's OAuth consent page."""
    if AUTH_FLOW_TYPE != "redirect":
        raise HTTPException(status_code=400, detail="Redirect flow not enabled")
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth not fully configured for redirect flow")

    state = secrets.token_urlsafe(32)
    redirect_uri = _get_redirect_uri(request, "/auth/google/callback")

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }

    google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    response = RedirectResponse(url=google_auth_url, status_code=302)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        secure=not _is_local_dev(request),
        samesite="lax",
        max_age=600,
    )
    return response


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Handle Google OAuth callback — exchange code for tokens and redirect to frontend."""
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    redirect_uri = _get_redirect_uri(request, "/auth/google/callback")

    token_response = http_requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )

    if token_response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

    token_data = token_response.json()
    id_token_str = token_data.get("id_token")
    if not id_token_str:
        raise HTTPException(status_code=400, detail="No ID token in response")

    google_info = verify_google_token(id_token_str)

    if not google_info.get('email_verified'):
        frontend_url = get_site_url(db)
        return RedirectResponse(url=f"{frontend_url}/login?error=email_not_verified")

    user = get_or_create_oauth_user(db, google_info)

    if not user.is_active:
        frontend_url = get_site_url(db)
        return RedirectResponse(url=f"{frontend_url}/login?error=account_inactive")

    user.last_login = datetime.utcnow()
    db.commit()

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires,
    )

    frontend_url = get_site_url(db)
    response = RedirectResponse(url=f"{frontend_url}/login/callback?token={access_token}", status_code=302)
    response.delete_cookie("oauth_state")
    return response


@router.get("/microsoft/authorize")
def microsoft_authorize(request: Request):
    """Redirect user to Microsoft's OAuth consent page (with PKCE)."""
    if AUTH_FLOW_TYPE != "redirect":
        raise HTTPException(status_code=400, detail="Redirect flow not enabled")
    if not MICROSOFT_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Microsoft OAuth not configured (missing client ID)")

    state = secrets.token_urlsafe(32)
    redirect_uri = _get_redirect_uri(request, "/auth/microsoft/callback")

    # PKCE: generate code_verifier and code_challenge
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")

    authority = OIDC_DISCOVERY_URL.split("/v2.0/")[0] if "/v2.0/" in OIDC_DISCOVERY_URL else "https://login.microsoftonline.com/common"

    params = {
        "client_id": MICROSOFT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "response_mode": "query",
        "prompt": "select_account",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    ms_auth_url = f"{authority}/oauth2/v2.0/authorize?{urlencode(params)}"

    response = RedirectResponse(url=ms_auth_url, status_code=302)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        secure=not _is_local_dev(request),
        samesite="lax",
        max_age=600,
    )
    response.set_cookie(
        key="oauth_verifier",
        value=code_verifier,
        httponly=True,
        secure=not _is_local_dev(request),
        samesite="lax",
        max_age=600,
    )
    return response


@router.get("/microsoft/callback")
def microsoft_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Handle Microsoft OAuth callback — exchange code for tokens and redirect to frontend."""
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    code_verifier = request.cookies.get("oauth_verifier")
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Missing PKCE verifier")

    redirect_uri = _get_redirect_uri(request, "/auth/microsoft/callback")
    authority = OIDC_DISCOVERY_URL.split("/v2.0/")[0] if "/v2.0/" in OIDC_DISCOVERY_URL else "https://login.microsoftonline.com/common"

    token_data_payload = {
        "code": code,
        "client_id": MICROSOFT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "scope": "openid email profile",
        "code_verifier": code_verifier,
    }
    # Include client_secret when available (confidential client); omit for public client PKCE-only
    if MICROSOFT_CLIENT_SECRET:
        token_data_payload["client_secret"] = MICROSOFT_CLIENT_SECRET

    token_response = http_requests.post(
        f"{authority}/oauth2/v2.0/token",
        data=token_data_payload,
        timeout=10,
    )

    if token_response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

    token_data = token_response.json()
    id_token_str = token_data.get("id_token")
    if not id_token_str:
        raise HTTPException(status_code=400, detail="No ID token in response")

    microsoft_info = verify_microsoft_token(id_token_str)

    if not microsoft_info.get('email_verified'):
        frontend_url = get_site_url(db)
        return RedirectResponse(url=f"{frontend_url}/login?error=email_not_verified")

    user = get_or_create_oauth_user(db, microsoft_info, provider='microsoft')

    if not user.is_active:
        frontend_url = get_site_url(db)
        return RedirectResponse(url=f"{frontend_url}/login?error=account_inactive")

    user.last_login = datetime.utcnow()
    db.commit()

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires,
    )

    frontend_url = get_site_url(db)
    response = RedirectResponse(url=f"{frontend_url}/login/callback?token={access_token}", status_code=302)
    response.delete_cookie("oauth_state")
    response.delete_cookie("oauth_verifier")
    return response


@router.get("/me", response_model=schemas.User)
def get_current_user_info(current_user: models.User = Depends(get_current_user)):
    """Get current logged-in user information."""
    return current_user


@router.put("/me", response_model=schemas.User)
def update_current_user_profile(
    user_update: schemas.UserUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update current user's profile."""
    updated_user = crud.update_user(
        db,
        user_id=current_user.id,
        user_update=user_update
    )
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return updated_user
