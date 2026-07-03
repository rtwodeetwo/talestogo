"""
Help/Contact form endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import logging

from ..database import get_db
from ..models import User
from ..auth import get_current_user
from ..services.email_notifications import send_email
from ..services.site_config import get_site_name, get_admin_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/help", tags=["help"])


class ContactRequest(BaseModel):
    subject: str
    message: str


@router.post("/contact")
async def send_contact_message(
    request: ContactRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send a help/contact message to admin"""

    # Get site configuration
    site_name = get_site_name(db)
    admin_email = get_admin_email(db)

    if not admin_email:
        logger.error("Admin email not configured - cannot send help request")
        raise HTTPException(
            status_code=500,
            detail="Support email is not configured. Please contact your system administrator."
        )

    try:
        # Email content
        subject = f"{site_name} Support Request: {request.subject}"
        body = f"""Support request from {site_name} user:

From: {current_user.email}
User ID: {current_user.id}
Subject: {request.subject}

Message:
{request.message}

---
Sent via {site_name} Help & Support form
"""

        # Send email to admin
        await send_email(admin_email, subject, body)

        logger.info(f"Help request sent from user {current_user.id} ({current_user.email})")

        return {
            "message": "Your message has been sent successfully. We'll get back to you soon!",
            "status": "success"
        }

    except Exception as e:
        logger.error(f"Failed to send help email: {str(e)}")
        contact_info = f" Please try again or contact {admin_email} directly." if admin_email else ""
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send message.{contact_info}"
        )
