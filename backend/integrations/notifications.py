"""Outbound email — the one place this repo talks to a mail provider.

Resend's HTTPS API (port 443) only — no SMTP. Raw SMTP (25/465/587) is
commonly blocked outbound on hosted/corporate networks that otherwise allow
HTTPS fine; confirmed on this deployment specifically: smtp.gmail.com:587 and
:465 both time out at the TCP level, api.resend.com:443 does not. Every other
outbound call in this repo (LLM, Jira) is already HTTPS for the same reason,
so this follows the same shape rather than fighting the network with a
second transport as a fallback.

Mirrors the rest of `integrations/`: a single entrypoint (`send_email`) that
never raises and degrades gracefully with no RESEND_API_KEY configured (same
pattern as `TICKET_SOURCE=jira` with no API token — logged once, skipped,
never a 500).

Currently has exactly one caller: integrations/sla_monitor.py. If a second
notification channel shows up (Slack, PagerDuty), it belongs here too — this
stays the only module that knows how to actually send something, the same way
ai/llm.py is the only place that talks to a model.
"""

from __future__ import annotations

import httpx

from config import settings
from observability.telemetry import log

RESEND_API_URL = "https://api.resend.com/emails"


def send_email(to: list[str], subject: str, text_body: str, html_body: str | None = None) -> bool:
    """Best-effort send via Resend. Returns False (and logs why) on any
    failure or on a missing RESEND_API_KEY — never raises, so a notification
    failure can never take down the caller's larger check loop.

    `text_body` is always sent; `html_body`, if given, rides alongside it as
    an alternative representation — every mail client renders the HTML
    version if it can and falls back to plain text otherwise (spam filters,
    screen readers, anyone with images/HTML disabled)."""
    recipients = [addr.strip() for addr in (to or []) if addr and addr.strip()]
    if not recipients:
        log.warning("send_email: no recipients, skipping (%r)", subject)
        return False
    if not settings.RESEND_API_KEY:
        log.warning(
            "send_email: RESEND_API_KEY not set — skipping %r to %s. "
            "Sign up free at resend.com, generate an API key, and set it in "
            "backend/.env.",
            subject,
            recipients,
        )
        return False

    payload: dict[str, object] = {
        "from": settings.NOTIFY_FROM_EMAIL,
        "to": recipients,
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        payload["html"] = html_body

    try:
        with httpx.Client(timeout=15, verify=not settings.DISABLE_SSL_VERIFY) as client:
            response = client.post(
                RESEND_API_URL,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json=payload,
            )
        if response.status_code >= 400:
            log.error(
                "send_email: failed to send %r to %s: %s %s",
                subject,
                recipients,
                response.status_code,
                response.text[:500],
            )
            return False
        log.info("send_email: sent %r to %s", subject, recipients)
        return True
    except Exception as exc:  # noqa: BLE001 - a bad send must not break the caller
        log.error("send_email: failed to send %r to %s: %s", subject, recipients, exc)
        return False
