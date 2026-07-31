"""
Authentication Router
Handles user registration, login (email/password, Google, Microsoft OAuth), and profile management
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from typing import List

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
    GOOGLE_CLIENT_ID,
    OIDC_DISCOVERY_URL,
    AUTH_FLOW_TYPE,
    AUTO_LOGIN_MICROSOFT,
)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


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

    # OAuth2 token_type value, not a credential
    return {"access_token": access_token, "token_type": "bearer"}  # nosec B105


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

    # OAuth2 token_type value, not a credential
    return {"access_token": access_token, "token_type": "bearer"}  # nosec B105


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

    # OAuth2 token_type value, not a credential
    return {"access_token": access_token, "token_type": "bearer"}  # nosec B105


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
