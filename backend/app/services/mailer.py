"""Outgoing e-mail over SMTP (e.g. Gmail with an App Password). Credentials come only from backend/.env.

Port 465 uses implicit TLS (SMTP_SSL); other ports use STARTTLS when SMTP_USE_TLS is true. Errors are returned,
never raised, and never include the password.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import Settings

log = logging.getLogger(__name__)


def email_configured(s: Settings) -> bool:
    return bool(s.smtp_host and s.smtp_from)


def send_email(s: Settings, to: str, subject: str, body: str) -> tuple[str, str | None]:
    """Returns (status, error): ("sent", None) / ("not_configured", why) / ("failed", error type)."""
    if not email_configured(s):
        return "not_configured", "E-mail is not set up on the server (SMTP_HOST / SMTP_FROM in backend/.env)."
    msg = EmailMessage()
    msg["Subject"] = subject[:200]
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg.set_content(body)
    try:
        ctx = ssl.create_default_context()
        if s.smtp_port == 465:
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=ctx) as smtp:
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password or "")
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
                if s.smtp_use_tls:
                    smtp.starttls(context=ctx)
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password or "")
                smtp.send_message(msg)
        return "sent", None
    except smtplib.SMTPAuthenticationError:
        log.warning("e-mail login failed (check SMTP_USERNAME / SMTP_PASSWORD – Gmail needs an App Password)")
        return "failed", "Login to the mail server failed – check SMTP_USERNAME and SMTP_PASSWORD (Gmail needs an App Password)."
    except Exception as exc:  # noqa: BLE001
        log.warning("e-mail failed: %s", type(exc).__name__)
        return "failed", type(exc).__name__
