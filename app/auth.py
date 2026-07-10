"""
Authentication utilities for TALES multi-user system.
Handles JWT tokens, password hashing, and user verification.
Supports both traditional email/password and Google OAuth authentication.
"""

from dotenv import load_dotenv
load_dotenv(override=True)  # Load environment variables FIRST, override existing ones

import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from . import models, schemas
from .database import get_db
from cryptography.fernet import Fernet
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import requests
import jwt as pyjwt

# JWT Configuration
# Supports PPPL naming (APP_SECRET) with fallback to legacy (JWT_SECRET_KEY)
SECRET_KEY = os.getenv("APP_SECRET") or os.getenv("JWT_SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

# Authentication Enable/Disable Flags
# Each lab can enable/disable authentication methods via environment variables
ENABLE_LOCAL_AUTH = os.getenv("ENABLE_LOCAL_AUTH", "true").lower() == "true"
ENABLE_MICROSOFT_AUTH = os.getenv("ENABLE_MICROSOFT_AUTH", "true").lower() == "true"
ENABLE_GOOGLE_AUTH = os.getenv("ENABLE_GOOGLE_AUTH", "false").lower() == "true"

# OAuth Flow Type: "popup" (default) or "redirect" (MSAL loginRedirect with client-side PKCE)
# Use "redirect" for compatibility with security scanners (e.g., Rapid7 InsightAppSec)
# Auto-detects: if OIDC_CLIENT_ID is set without a client secret, uses redirect+PKCE automatically.
def _resolve_auth_flow_type() -> str:
    import logging
    logger = logging.getLogger(__name__)

    explicit = os.getenv("AUTH_FLOW_TYPE")
    if explicit:
        normalized = explicit.strip().lower()
        if normalized not in ("popup", "redirect"):
            logger.warning(
                f"AUTH_FLOW_TYPE={explicit!r} is not valid (must be 'popup' or 'redirect'), defaulting to 'popup'"
            )
            return "popup"
        return normalized
    # Auto-detect: client ID present without a secret → use redirect (PKCE)
    has_ms_id = bool(
        os.getenv("OIDC_CLIENT_ID") or os.getenv("ENTRA_CLIENT_ID") or os.getenv("MICROSOFT_CLIENT_ID")
    )
    has_ms_secret = bool(
        os.getenv("OIDC_CLIENT_SECRET") or os.getenv("ENTRA_SECRET_KEY") or os.getenv("MICROSOFT_CLIENT_SECRET")
    )
    if has_ms_secret:
        logger.warning(
            "OIDC_CLIENT_SECRET / ENTRA_SECRET_KEY / MICROSOFT_CLIENT_SECRET is set but no longer used. "
            "OAuth now uses client-side PKCE (no secret needed). Remove the secret from your .env. "
            "To use redirect mode, set AUTH_FLOW_TYPE=redirect explicitly."
        )
    if has_ms_id and not has_ms_secret:
        return "redirect"
    return "popup"

AUTH_FLOW_TYPE = _resolve_auth_flow_type()

# Auto-login: when true and redirect+Microsoft is the sole auth method, skip the login page
AUTO_LOGIN_MICROSOFT = os.getenv("AUTO_LOGIN_MICROSOFT", "false").lower() == "true"

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

# Microsoft/Entra OIDC Configuration
# Priority: OIDC_* (PPPL standard) > ENTRA_* > MICROSOFT_* (legacy)
MICROSOFT_CLIENT_ID = (
    os.getenv("OIDC_CLIENT_ID") or
    os.getenv("ENTRA_CLIENT_ID") or
    os.getenv("MICROSOFT_CLIENT_ID")
)

# OIDC Discovery URL for lab-specific Entra tenants
# Default to common endpoint, but labs can override for tenant-specific auth
OIDC_DISCOVERY_URL = os.getenv(
    "OIDC_DISCOVERY_URL",
    "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
)

# Admin Configuration
# NOTE: ADMIN_EMAIL is ONLY used for initial bootstrap (first-time admin OAuth login).
# After a user is created, all admin checks use the database is_admin flag.
# To promote/demote admins, update the is_admin field in the database directly.
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

# Encryption key for API keys (must be stored securely in production)
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
cipher_suite = Fernet(ENCRYPTION_KEY.encode())

# HTTP Bearer token security
security = HTTPBearer()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def get_password_hash(password: str) -> str:
    """Hash a password for storage."""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key for secure storage."""
    if not api_key:
        return None
    return cipher_suite.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt an API key for use."""
    if not encrypted_key:
        return None
    return cipher_suite.decrypt(encrypted_key.encode()).decode()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_invitation_token(email: str, full_name: str, expires_days: int = 7) -> tuple[str, datetime]:
    """Create a JWT invitation token that expires in N days."""
    expire = datetime.utcnow() + timedelta(days=expires_days)
    to_encode = {
        "email": email,
        "full_name": full_name,
        "exp": expire,
        "type": "invitation"
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt, expire


def verify_invitation_token(token: str) -> dict:
    """Verify and decode an invitation token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "invitation":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invitation token"
            )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invitation token"
        )


def verify_token(token: str) -> dict:
    """Verify and decode a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> models.User:
    """
    Get the current authenticated user from JWT token.
    This dependency should be used on all protected routes.
    """
    token = credentials.credentials
    payload = verify_token(token)

    user_id: int = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not active. Please contact admin for approval.",
        )

    return user


def get_current_admin_user(
    current_user: models.User = Depends(get_current_user)
) -> models.User:
    """
    Verify that the current user is an admin.
    Use this dependency for admin-only routes.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can perform this action",
        )
    return current_user


def authenticate_user(db: Session, email: str, password: str) -> Optional[models.User]:
    """Authenticate a user by email and password."""
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        return None
    if not user.hashed_password:
        # OAuth user trying to login with password
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def verify_google_token(token: str) -> dict:
    """
    Verify Google OAuth ID token and return user info.
    Returns dict with: email, name, picture, sub (google_id)
    """
    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID
        )

        # Verify issuer
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError('Wrong issuer.')

        return {
            'email': idinfo['email'],
            'name': idinfo.get('name'),
            'picture': idinfo.get('picture'),
            'google_id': idinfo['sub'],
            'email_verified': idinfo.get('email_verified', False)
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Google token: {str(e)}"
        )


def verify_microsoft_token(token: str) -> dict:
    """
    Verify Microsoft OAuth ID token and return user info.
    Returns dict with: email, name, microsoft_id

    Uses OIDC_DISCOVERY_URL to support lab-specific Entra tenants.
    """
    try:
        # Decode the token without verification first to get the key ID
        unverified_header = pyjwt.get_unverified_header(token)
        kid = unverified_header['kid']

        # Get JWKS URL from OIDC discovery document, or use default
        # This supports lab-specific Entra tenant configurations
        try:
            discovery_response = requests.get(OIDC_DISCOVERY_URL, timeout=10)
            discovery_doc = discovery_response.json()
            jwks_url = discovery_doc.get('jwks_uri', "https://login.microsoftonline.com/common/discovery/v2.0/keys")
        except Exception:
            # Fallback to default Microsoft JWKS URL
            jwks_url = "https://login.microsoftonline.com/common/discovery/v2.0/keys"

        jwks_response = requests.get(jwks_url, timeout=10)
        jwks = jwks_response.json()

        # Find the correct key
        public_key = None
        for key in jwks['keys']:
            if key['kid'] == kid:
                public_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(key)
                break

        if not public_key:
            raise ValueError('Public key not found')

        # Verify and decode the token
        decoded = pyjwt.decode(
            token,
            public_key,
            algorithms=['RS256'],
            audience=MICROSOFT_CLIENT_ID,
            options={"verify_exp": True}
        )

        return {
            'email': decoded.get('email') or decoded.get('preferred_username'),
            'name': decoded.get('name'),
            'microsoft_id': decoded['sub'],
            'email_verified': True  # Microsoft tokens are already verified
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Microsoft token: {str(e)}"
        )


def get_oauth_provider_for_email(email: str) -> Optional[str]:
    """
    Determine the default OAuth provider based on email domain.
    Returns 'google', 'microsoft', or None.

    Add lab-specific domain mappings here if you want users from a particular
    domain to default to a specific OAuth provider.
    """
    email_domain = email.split('@')[-1].lower()

    # Map email domains to OAuth providers
    domain_to_oauth = {
        'gmail.com': 'google',
        # Add more domain mappings here as needed (e.g., 'mylab.gov': 'microsoft')
    }

    return domain_to_oauth.get(email_domain)


def get_tenant_id_for_email(db: Session, email: str) -> Optional[int]:
    """
    Determine which tenant a user should belong to based on their email domain.
    Returns tenant_id or None if no match found (will use default tenant).
    Creates a "Default" tenant if it doesn't exist.

    Admins can map specific email domains to tenants by adding entries to
    `domain_to_tenant` below. Tenants are auto-created on first use.
    """
    email_domain = email.split('@')[-1].lower()

    # Map email domains to tenant names (customize for your deployment).
    # Example:
    #   domain_to_tenant = {'mylab.gov': 'My Lab'}
    domain_to_tenant: dict = {}

    tenant_name = domain_to_tenant.get(email_domain)
    if not tenant_name:
        # Fall back to the default tenant - create if doesn't exist
        tenant = db.query(models.Tenant).filter(models.Tenant.tenant_name == 'Default').first()
        if not tenant:
            tenant = models.Tenant(
                tenant_name='Default',
                primary_color='#003e60',
                secondary_color='#75c9c8'
            )
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
        return tenant.id

    # Find the tenant by name - create if doesn't exist
    tenant = db.query(models.Tenant).filter(models.Tenant.tenant_name == tenant_name).first()
    if not tenant:
        tenant = models.Tenant(
            tenant_name=tenant_name,
            primary_color='#003e60',
            secondary_color='#75c9c8'
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
    return tenant.id


def get_or_create_oauth_user(db: Session, oauth_info: dict, provider: str = 'google') -> models.User:
    """
    Get existing OAuth user or create a new one.
    Supports both Google and Microsoft OAuth.
    New OAuth users are automatically activated.
    """
    # Get provider-specific ID field
    if provider == 'google':
        provider_id = oauth_info.get('google_id')
        id_field = models.User.google_id
    elif provider == 'microsoft':
        provider_id = oauth_info.get('microsoft_id')
        id_field = models.User.microsoft_id
    else:
        raise ValueError(f"Unsupported OAuth provider: {provider}")

    # Check if user exists by provider ID
    user = db.query(models.User).filter(id_field == provider_id).first()

    if user:
        # Update user info if needed
        if provider == 'google' and user.picture_url != oauth_info.get('picture'):
            user.picture_url = oauth_info.get('picture')
        if user.full_name != oauth_info.get('name'):
            user.full_name = oauth_info.get('name')
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user

    # Check if user exists by email (maybe they registered with password or different provider before)
    user = db.query(models.User).filter(models.User.email == oauth_info['email']).first()

    if user:
        # Link OAuth account to existing user
        if provider == 'google':
            user.google_id = oauth_info['google_id']
            user.picture_url = oauth_info.get('picture')
        elif provider == 'microsoft':
            user.microsoft_id = oauth_info['microsoft_id']

        # Set OAuth provider - use the one based on email domain if not already set
        if not user.oauth_provider:
            user.oauth_provider = get_oauth_provider_for_email(oauth_info['email']) or provider
        else:
            user.oauth_provider = provider

        if not user.full_name:
            user.full_name = oauth_info.get('name')

        # Bootstrap: Only auto-grant admin on first OAuth link if not already set
        # After this, admin status is managed via database only
        if oauth_info['email'].lower() == ADMIN_EMAIL.lower() and not user.is_admin:
            print(f"INFO: Bootstrap - granting admin privileges to {oauth_info['email']} (first OAuth login)")
            user.is_active = True
            user.is_admin = True

        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user

    # Create new user
    # Bootstrap: Check if this is the first-time admin email login
    # After this initial creation, all admin management is done via database
    is_admin_user = (oauth_info['email'].lower() == ADMIN_EMAIL.lower())

    if is_admin_user:
        print(f"INFO: Bootstrap - creating new admin user for {oauth_info['email']}")

    # Get tenant_id based on email domain
    tenant_id = get_tenant_id_for_email(db, oauth_info['email'])

    # Get OAuth provider based on email domain, fallback to provided provider
    oauth_provider = get_oauth_provider_for_email(oauth_info['email']) or provider

    new_user = models.User(
        email=oauth_info['email'],
        google_id=oauth_info.get('google_id') if provider == 'google' else None,
        microsoft_id=oauth_info.get('microsoft_id') if provider == 'microsoft' else None,
        oauth_provider=oauth_provider,  # Use domain-based provider
        full_name=oauth_info.get('name'),
        picture_url=oauth_info.get('picture') if provider == 'google' else None,
        tenant_id=tenant_id,  # Auto-assign tenant based on email domain
        is_active=is_admin_user,  # Bootstrap: Only auto-activate admin email, others need approval
        is_admin=is_admin_user,  # Bootstrap: Grant admin only if ADMIN_EMAIL on first creation
        is_invited=False,  # Require admin approval for all new users
        hashed_password=None  # No password for OAuth users
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user
