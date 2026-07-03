"""
Email Service — single module for all outbound email in TALES.

Supports two backends (checked in order):
1. SMTP — set SMTP_HOST (and optionally SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_USE_TLS,
   SMTP_FROM_EMAIL, SMTP_FROM_NAME). Authentication is optional — relay servers like
   emailgw.pnl.gov on port 25 work without credentials.
2. Resend API — set RESEND_API_KEY and FROM_EMAIL.

If neither is configured, sending raises ValueError.

Public API:
  send_email(to, subject, body, html=False)       — async
  send_email_sync(to, subject, body, html=False)  — sync
  send_task_completion_email(db, ...)              — sync, composes HTML and sends
"""
import os
import ssl
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from .. import models
from .site_config import get_site_url, get_site_name, get_admin_contact_text

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv('RESEND_API_KEY')
FROM_EMAIL = os.getenv('FROM_EMAIL', '')


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_smtp_config():
    """Return SMTP config dict or None if SMTP_HOST is not set."""
    host = os.getenv('SMTP_HOST')
    if not host:
        return None
    user = os.getenv('SMTP_USER')
    password = os.getenv('SMTP_PASSWORD')
    has_credentials = bool(user and password)
    # Default TLS to on when credentials are configured (protects passwords in transit).
    # For unauthenticated relays, TLS defaults to off (internal relay servers often don't support it).
    tls_default = 'true' if has_credentials else 'false'
    return {
        'host': host,
        'port': int(os.getenv('SMTP_PORT', '587' if has_credentials else '25')),
        'user': user,
        'password': password,
        'use_tls': os.getenv('SMTP_USE_TLS', tls_default).lower() in ('true', '1', 'yes'),
        'from_email': os.getenv('SMTP_FROM_EMAIL', FROM_EMAIL or user or ''),
        'from_name': os.getenv('SMTP_FROM_NAME', 'TALES'),
    }


def _smtp_send(to_email: str, subject: str, body: str, html: bool = False):
    """Low-level synchronous SMTP send. Raises on failure."""
    cfg = _get_smtp_config()
    if not cfg:
        raise ValueError("SMTP_HOST is required for SMTP email sending")

    if not cfg['from_email']:
        raise ValueError(
            "No from address configured. Set SMTP_FROM_EMAIL, FROM_EMAIL, or SMTP_USER."
        )

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{cfg['from_name']} <{cfg['from_email']}>"
    msg['To'] = to_email

    content_type = 'html' if html else 'plain'
    msg.attach(MIMEText(body, content_type))

    server = smtplib.SMTP(cfg['host'], cfg['port'], timeout=30)
    try:
        server.ehlo()
        if cfg['use_tls']:
            context = ssl.create_default_context()
            server.starttls(context=context)
            server.ehlo()
        if cfg['user'] and cfg['password']:
            server.login(cfg['user'], cfg['password'])
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            server.close()

    logger.info(f"Email sent via SMTP to {to_email}")


async def _send_via_resend(to_email: str, subject: str, body: str, html: bool = False):
    """Send email via Resend API (async)."""
    payload = {
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
    }
    if html:
        payload["html"] = body
    else:
        payload["text"] = body

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code == 200:
            logger.info(f"Email sent via Resend to {to_email}")
        else:
            logger.error(f"Resend API error: {response.status_code} - {response.text}")
            raise Exception(f"Resend API error: {response.status_code}")


def _send_via_resend_sync(to_email: str, subject: str, body: str, html: bool = False):
    """Send email via Resend API (sync)."""
    payload = {
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
    }
    if html:
        payload["html"] = body
    else:
        payload["text"] = body

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code == 200:
            logger.info(f"Email sent via Resend to {to_email}")
        else:
            logger.error(f"Resend API error: {response.status_code} - {response.text}")
            raise Exception(f"Resend API error: {response.status_code}")


# ---------------------------------------------------------------------------
# Public API — generic send
# ---------------------------------------------------------------------------

async def send_email(to_email: str, subject: str, body: str, html: bool = False):
    """Async send — tries SMTP first, falls back to Resend."""
    import asyncio
    cfg = _get_smtp_config()
    if cfg:
        await asyncio.to_thread(_smtp_send, to_email, subject, body, html)
        return

    if RESEND_API_KEY:
        await _send_via_resend(to_email, subject, body, html=html)
        return

    error_msg = "No email backend configured. Set SMTP_HOST or RESEND_API_KEY."
    logger.error(error_msg)
    raise ValueError(error_msg)


def send_email_sync(to_email: str, subject: str, body: str, html: bool = False):
    """Sync send — tries SMTP first, falls back to Resend (sync httpx)."""
    cfg = _get_smtp_config()
    if cfg:
        _smtp_send(to_email, subject, body, html=html)
        return

    if RESEND_API_KEY:
        _send_via_resend_sync(to_email, subject, body, html=html)
        return

    error_msg = "No email backend configured. Set SMTP_HOST or RESEND_API_KEY."
    logger.error(error_msg)
    raise ValueError(error_msg)


# ---------------------------------------------------------------------------
# Public API — task completion notifications
# ---------------------------------------------------------------------------

def send_task_completion_email(
    db: Session,
    user_id: int,
    task_type: str,
    task_id: int,
    status: str,
    brand_id: Optional[int] = None,
    error_message: Optional[str] = None
):
    """
    Send an email notification when a task completes or fails.
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.email:
        logger.warning(f"No email found for user {user_id}")
        return

    brand_name = "Your Brand"
    if brand_id:
        brand = db.query(models.BrandInfo).filter(models.BrandInfo.id == brand_id).first()
        if brand:
            brand_name = brand.brand_name

    task_type_names = {
        'collection': 'Data Collection',
        'analysis': 'Data Analysis',
        'report_generation': 'Report Generation'
    }
    task_name = task_type_names.get(task_type, task_type.title())

    site_url = get_site_url(db)
    site_name = get_site_name(db)
    contact_text = get_admin_contact_text(db)

    if status == 'completed':
        subject = f"{site_name}: {task_name} Complete - {brand_name}"
        logo_url = f"{site_url}/tales_logo.png"
        body = f"""
<html>
<body style="font-family: Arial, sans-serif; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background-color: #003e60; padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
            <img src="{logo_url}" alt="{site_name}" style="max-width: 200px; height: auto; margin-bottom: 20px;" />
            <h1 style="color: white; margin: 0;">Task Complete!</h1>
        </div>
        <div style="background-color: #f9f9f9; padding: 30px; border: 1px solid #e0e0e0; border-radius: 0 0 8px 8px;">
            <p style="font-size: 16px; line-height: 1.6;">
                Your <strong>{task_name}</strong> for <strong>{brand_name}</strong> has completed successfully.
            </p>
            <p style="font-size: 16px; line-height: 1.6;">
                Log in to {site_name} to view your results:
            </p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="{site_url}"
                   style="background-color: #f04b25; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                    View Results
                </a>
            </div>
            <p style="font-size: 14px; color: #666; margin-top: 30px;">
                {contact_text}
            </p>
        </div>
    </div>
</body>
</html>
"""
    else:
        subject = f"{site_name}: {task_name} Failed - {brand_name}"
        error_details = error_message if error_message else "An unknown error occurred."
        logo_url = f"{site_url}/tales_logo.png"
        body = f"""
<html>
<body style="font-family: Arial, sans-serif; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background-color: #003e60; padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
            <img src="{logo_url}" alt="{site_name}" style="max-width: 200px; height: auto; margin-bottom: 20px;" />
            <h1 style="color: white; margin: 0;">Task Failed</h1>
        </div>
        <div style="background-color: #f9f9f9; padding: 30px; border: 1px solid #e0e0e0; border-radius: 0 0 8px 8px;">
            <p style="font-size: 16px; line-height: 1.6;">
                Your <strong>{task_name}</strong> for <strong>{brand_name}</strong> encountered an error and could not complete.
            </p>
            <div style="background-color: #fff; border-left: 4px solid #EA4A4A; padding: 15px; margin: 20px 0;">
                <p style="margin: 0; font-family: monospace; font-size: 14px;">
                    {error_details}
                </p>
            </div>
            <p style="font-size: 16px; line-height: 1.6;">
                Please try again or contact support if the problem persists.
            </p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="{site_url}"
                   style="background-color: #f04b25; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                    Return to {site_name}
                </a>
            </div>
            <p style="font-size: 14px; color: #666; margin-top: 30px;">
                {contact_text}
            </p>
        </div>
    </div>
</body>
</html>
"""

    try:
        send_email_sync(user.email, subject, body, html=True)
        logger.info(f"Task completion email sent to {user.email} for task {task_id}")
    except Exception as e:
        logger.error(f"Failed to send task completion email: {e}")
