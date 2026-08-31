"""
Users Router
Handles admin user management and invitation endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import timedelta
import datetime
import logging
import secrets
import string

logger = logging.getLogger(__name__)

from .. import crud, models, schemas
from ..database import get_db
from ..auth import (
    get_current_admin_user,
    get_password_hash,
    create_invitation_token,
    verify_invitation_token,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ENABLE_LOCAL_AUTH,
    ENABLE_MICROSOFT_AUTH,
    ENABLE_GOOGLE_AUTH,
    MICROSOFT_CLIENT_ID,
    GOOGLE_CLIENT_ID,
)
from ..services.site_config import get_site_url, get_site_name, get_admin_email

# Create separate routers for admin and invitation endpoints
admin_router = APIRouter(
    prefix="/admin/users",
    tags=["Admin"]
)

invitation_router = APIRouter(
    tags=["Invitations"]
)


# --- Admin User Management Endpoints ---

@admin_router.get("", response_model=List[schemas.User])
def list_all_users(
    skip: int = 0,
    limit: int = 100,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """List all users (admin only)."""
    return crud.get_users(db, skip=skip, limit=limit)


@admin_router.post("/invite", response_model=schemas.User, status_code=201)
def invite_user(
    user_invite: schemas.UserInvite,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Create an invited user (admin only).
    Invited users are pre-approved (is_active=True).
    """
    # Check if user already exists
    db_user = crud.get_user_by_email(db, email=user_invite.email)
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Generate a secure random temporary password (user should change on first login)
    alphabet = string.ascii_letters + string.digits + string.punctuation
    temp_password = ''.join(secrets.choice(alphabet) for _ in range(24))
    hashed_password = get_password_hash(temp_password)

    # Create user object
    user_create = schemas.UserCreate(
        email=user_invite.email,
        password=temp_password,
        full_name=user_invite.full_name,
        organization=user_invite.organization
    )

    new_user = crud.create_user(db=db, user=user_create, hashed_password=hashed_password, is_invited=True)

    # Activate invited user immediately
    admin_update = schemas.UserAdminUpdate(is_active=True)
    crud.admin_update_user(db, user_id=new_user.id, user_update=admin_update)

    return new_user


@admin_router.put("/{user_id}", response_model=schemas.User)
def admin_update_user_status(
    user_id: int,
    user_update: schemas.UserAdminUpdate,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Update user status (activate/deactivate, make admin) - admin only."""
    updated_user = crud.admin_update_user(db, user_id=user_id, user_update=user_update)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return updated_user


@admin_router.delete("/{user_id}", response_model=schemas.User)
def admin_delete_user(
    user_id: int,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Delete a user (admin only). Cannot delete yourself."""
    # Prevent admin from deleting themselves
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account"
        )

    # Get the user
    user_to_delete = db.query(models.User).filter(models.User.id == user_id).first()
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete the user (will cascade delete all related data)
    db.delete(user_to_delete)
    db.commit()

    return user_to_delete


@admin_router.post("/create-invite", response_model=schemas.InvitationResponse, status_code=201)
def create_invitation(
    invitation: schemas.InvitationCreate,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Create a pre-approved user (admin only).

    When local (email/password) auth is enabled, this also mints an invitation
    token so the new user can set their initial password at /invite/accept.
    With OAuth-only auth, no token is needed: the user just signs in with their
    identity provider and the pre-approved account is matched by email.
    """
    # Check if user already exists
    existing_user = crud.get_user_by_email(db, email=invitation.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )

    # With local auth enabled, mint a set-your-password invitation token
    invitation_token = None
    invitation_expires_at = None
    if ENABLE_LOCAL_AUTH:
        invitation_token, invitation_expires_at = create_invitation_token(
            email=invitation.email,
            full_name=invitation.full_name,
        )

    # Create pre-approved user (active and ready for OAuth login)
    # Use specified tenant_id or default to admin's tenant
    tenant_id = invitation.tenant_id if invitation.tenant_id is not None else current_user.tenant_id

    new_user = models.User(
        email=invitation.email,
        full_name=invitation.full_name,
        organization=invitation.organization,
        is_invited=True,
        is_active=True,  # Pre-approved for OAuth login; local auth needs /invite/accept
        invitation_token=invitation_token,
        invitation_expires_at=invitation_expires_at,
        tenant_id=tenant_id,  # Use specified tenant or admin's tenant
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Site URL comes from Site Settings DB > FRONTEND_URL env > localhost fallback
    site_url = get_site_url(db)
    return schemas.InvitationResponse(
        email=invitation.email,
        full_name=invitation.full_name,
        # Empty placeholder when OAuth-only: that flow issues no token
        invitation_token=invitation_token or "",  # nosec B106
        expires_at=invitation_expires_at,
        invitation_url=(
            f"{site_url}/invite/accept?token={invitation_token}"
            if invitation_token else site_url
        )
    )


@admin_router.post("/{user_id}/send-invitation", status_code=200)
async def send_invitation_email(
    user_id: int,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Send invitation email to a user (admin only).
    Generates domain-specific email content.
    """
    from ..services.email_notifications import send_email

    # Get the user
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get site configuration
    site_url = get_site_url(db)
    site_name = get_site_name(db)
    admin_email = get_admin_email(db)

    # Build login instructions from the auth methods this deployment has enabled
    google_enabled = ENABLE_GOOGLE_AUTH and bool(GOOGLE_CLIENT_ID)
    ms_enabled = ENABLE_MICROSOFT_AUTH and bool(MICROSOFT_CLIENT_ID)

    instructions = []
    if ENABLE_LOCAL_AUTH and not user.hashed_password:
        # Mint a fresh set-your-password token on every send, so resending an
        # invitation also revives one that has expired.
        token, expires_at = create_invitation_token(
            email=user.email,
            full_name=user.full_name or user.email,
        )
        user.invitation_token = token
        user.invitation_expires_at = expires_at
        db.commit()
        instructions.append(
            f"- Set your password here (link valid for 7 days):\n"
            f"  {site_url}/invite/accept?token={token}"
        )
    elif ENABLE_LOCAL_AUTH:
        instructions.append(f"- Sign in with your email ({user.email}) and password.")
    if google_enabled or ms_enabled:
        providers = " or ".join(
            name for name, enabled in (("Google", google_enabled), ("Microsoft", ms_enabled)) if enabled
        )
        prefix = "- Or sign" if instructions else "- Sign"
        instructions.append(f"{prefix} in with {user.email} using the {providers} login button.")
    if not instructions:
        instructions.append(f"- Sign in with {user.email}.")
    login_instruction = "\n".join(instructions)

    # Build contact line only if admin email is configured
    contact_line = f"Questions? Contact {admin_email}." if admin_email else ""

    subject = 'Welcome to Tales - Shape Your AI Story'
    body = f"""Hi {user.full_name or user.email},

You've been invited to Tales, where AI meets brand intelligence. Now you have the power to track what the AIs are saying about your Lab!

Your story starts at {site_url}.
{login_instruction}
- Click on Customize and start adding information about your brands!

Best regards,
The Tales Team"""

    # Send email
    try:
        await send_email(user.email, subject, body)
        return {"message": f"Invitation email sent to {user.email}"}
    except ValueError as e:
        logger.warning(f"Email not configured, skipping invitation email: {e}")
        raise HTTPException(
            status_code=503,
            detail="Email service is not configured. User was created but no invitation email was sent."
        )
    except Exception as e:
        logger.error(f"Failed to send invitation email to {user.email}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send email: {str(e)}"
        )


# --- Invitation Endpoints ---

@invitation_router.get("/invite/validate", response_model=schemas.InvitationValidate)
def validate_invitation(token: str, db: Session = Depends(get_db)):
    """
    Validate an invitation token.
    Returns user info if token is valid, otherwise raises error.
    """
    # Verify token
    payload = verify_invitation_token(token)

    # Check if user exists and invitation is still valid
    user = crud.get_user_by_email(db, email=payload["email"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found"
        )

    # Invited users are pre-activated so OAuth login works immediately, so
    # "already used" means a local password has been set, not is_active.
    if user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has already been used"
        )

    if user.invitation_token != token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invitation token"
        )

    if user.invitation_expires_at and user.invitation_expires_at < datetime.datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has expired"
        )

    return schemas.InvitationValidate(
        email=payload["email"],
        full_name=payload["full_name"],
        expires_at=user.invitation_expires_at
    )


@invitation_router.post("/invite/accept", response_model=schemas.Token)
def accept_invitation(
    invitation_accept: schemas.InvitationAccept,
    db: Session = Depends(get_db)
):
    """
    Accept an invitation by setting password and activating account.
    Returns access token for immediate login.
    """
    # Verify token
    payload = verify_invitation_token(invitation_accept.token)

    # Get user
    user = crud.get_user_by_email(db, email=payload["email"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found"
        )

    # Invited users are pre-activated so OAuth login works immediately, so
    # "already used" means a local password has been set, not is_active.
    if user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has already been used"
        )

    if user.invitation_token != invitation_accept.token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invitation token"
        )

    if user.invitation_expires_at and user.invitation_expires_at < datetime.datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has expired"
        )

    # Set password and activate user
    user.hashed_password = get_password_hash(invitation_accept.password)
    user.is_active = True
    user.invitation_token = None  # Clear token after use
    db.commit()
    db.refresh(user)

    # Create access token for immediate login
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires
    )

    # OAuth2 token_type value, not a credential
    return {"access_token": access_token, "token_type": "bearer"}  # nosec B105
