"""Background job: warn admin/manager users before a ticket breaches its SLA.

Runs on the same shape as integrations/poller.py — a daemon thread on a fixed
interval (SLA_CHECK_SECONDS), started once from run.py, safe to also trigger
manually. Every SLA_TARGET_MINS figure it uses is the same deterministic
lookup table triage reads (rag/schemas.py) — the "70% elapsed" fraction is
arithmetic on that number and Ticket.created_at, never something an LLM
decides.

One email per ticket, ever: Ticket.sla_warning_sent_at is stamped the first
time a ticket crosses the threshold, so a ticket sitting at 95% elapsed does
not get re-notified on every 15-minute check. Reopening a ticket after that
does not currently reset the flag — acceptable for now, see the module's
CLAUDE.md-scale: this is a build-day addition, not the whole lifecycle.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from config import settings
from observability.telemetry import log

# Tickets past this point in their lifecycle are done, one way or another —
# no SLA clock is still running against them.
_CLOSED_STATUSES = {"resolved", "synced", "failed"}

_stop = threading.Event()
_thread: threading.Thread | None = None


def _format_due(due_at: datetime) -> str:
    return due_at.strftime("%Y-%m-%d %H:%M UTC")


def _format_remaining(due_at: datetime, now: datetime) -> str:
    delta = due_at - now
    if delta.total_seconds() <= 0:
        overdue = -delta
        hours = int(overdue.total_seconds() // 3600)
        return f"overdue by {hours}h" if hours else "overdue"
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    return f"{hours}h {minutes}m remaining" if hours else f"{minutes}m remaining"


# Priority -> accent color for the email's left-border/badge. Same four bands
# as everywhere else (rag/schemas.py); a fifth, unmatched value falls back to
# the Low/neutral color rather than raising on an unexpected string.
_SEVERITY_COLOR = {
    "Highest": "#dc2626",
    "High": "#ea580c",
    "Medium": "#d97706",
    "Low": "#64748b",
}


def _breach_email(ticket, due_at: datetime, now: datetime) -> tuple[str, str, str]:
    """Deterministic template, not LLM-generated — same principle as the SLA
    figures themselves (rag/schemas.py::SLA_TARGET_MINS): a notification about
    a lookup number should not itself be a place for the model to improvise.

    Returns (subject, plain_text_body, html_body) — the HTML version is what
    every modern mail client actually renders; the plain-text one is the
    multipart/alternative fallback (see integrations/notifications.py).
    """
    incident = ticket.external_id or ticket.id
    pct = int(settings.SLA_WARNING_THRESHOLD * 100)
    due_str = _format_due(due_at)
    remaining_str = _format_remaining(due_at, now)
    color = _SEVERITY_COLOR.get(ticket.severity, _SEVERITY_COLOR["Low"])
    team = ticket.assigned_team or "unassigned"

    subject = f"SLA Alert: {incident} nearing resolution deadline"

    text_body = (
        f"Hello,\n\n"
        f"This is an automated notice that incident {incident} "
        f"has reached {pct}% of its {ticket.severity} priority SLA resolution window.\n\n"
        f"Incident: {incident}\n"
        f"Title: {ticket.title}\n"
        f"Priority: {ticket.severity}\n"
        f"Team: {team}\n"
        f"SLA resolution due: {due_str} ({remaining_str})\n\n"
        f"If work on this incident is already in progress, no action is required - "
        f"please disregard this notice.\n"
        f"If it has already been resolved, kindly close the incident in the system.\n\n"
        f"This is an automated message from TicketSphere."
    )

    # Table-based layout, every rule inline — the only markup that renders
    # consistently across Gmail, Outlook desktop and mobile clients, none of
    # which reliably support a <style> block or modern CSS.
    def _row(label: str, value: str) -> str:
        return (
            '<tr>'
            '<td style="padding:6px 0;color:#64748b;font-size:13px;'
            'font-family:Segoe UI,Arial,sans-serif;white-space:nowrap;'
            'vertical-align:top;">' + label + '</td>'
            '<td style="padding:6px 0 6px 16px;color:#0f172a;font-size:13px;'
            'font-family:Segoe UI,Arial,sans-serif;font-weight:600;'
            'vertical-align:top;">' + value + '</td>'
            '</tr>'
        )

    html_body = f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 16px;">
  <tr><td align="center">
    <table role="presentation" width="560" cellpadding="0" cellspacing="0"
           style="background:#ffffff;border-radius:8px;overflow:hidden;
                  border:1px solid #e2e8f0;max-width:560px;width:100%;">
      <tr>
        <td style="background:{color};padding:20px 28px;">
          <span style="color:#ffffff;font-family:Segoe UI,Arial,sans-serif;
                       font-size:12px;font-weight:700;letter-spacing:.06em;
                       text-transform:uppercase;">SLA Alert &middot; {ticket.severity} Priority</span>
          <div style="color:#ffffff;font-family:Segoe UI,Arial,sans-serif;
                      font-size:19px;font-weight:700;margin-top:4px;">{incident} at {pct}% of SLA window</div>
        </td>
      </tr>
      <tr>
        <td style="padding:24px 28px 8px 28px;font-family:Segoe UI,Arial,sans-serif;
                   color:#334155;font-size:14px;line-height:1.5;">
          This is an automated notice that the incident below has reached <b>{pct}%</b>
          of its resolution SLA window.
        </td>
      </tr>
      <tr>
        <td style="padding:12px 28px 4px 28px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
            {_row("Incident", incident)}
            {_row("Title", ticket.title or "(untitled)")}
            {_row("Priority", ticket.severity)}
            {_row("Team", team)}
          </table>
        </td>
      </tr>
      <tr>
        <td style="padding:16px 28px 8px 28px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="background:#fef2f2;border:1px solid #fecaca;border-radius:6px;">
            <tr>
              <td style="padding:14px 16px;font-family:Segoe UI,Arial,sans-serif;">
                <span style="color:#7f1d1d;font-size:11px;font-weight:700;
                             letter-spacing:.04em;text-transform:uppercase;">SLA resolution due</span>
                <div style="color:#0f172a;font-size:16px;font-weight:700;margin-top:2px;">{due_str}</div>
                <div style="color:#b91c1c;font-size:13px;font-weight:600;margin-top:2px;">{remaining_str}</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td style="padding:16px 28px 24px 28px;font-family:Segoe UI,Arial,sans-serif;
                   color:#475569;font-size:13px;line-height:1.6;">
          If work on this incident is already in progress, no action is required &mdash;
          please disregard this notice.<br/>
          If it has already been resolved, kindly close the incident in the system.
        </td>
      </tr>
      <tr>
        <td style="padding:14px 28px;background:#f8fafc;border-top:1px solid #e2e8f0;
                   font-family:Segoe UI,Arial,sans-serif;color:#94a3b8;font-size:11px;">
          This is an automated message from TicketSphere.
        </td>
      </tr>
    </table>
  </td></tr>
</table>"""

    return subject, text_body, html_body


def _notify_recipients() -> list[str]:
    from db.sqlite.models import SessionLocal, User

    with SessionLocal() as s:
        rows = s.query(User).filter(User.role.in_(["admin", "manager"])).all()
    return [u.email for u in rows if u.email and u.email.strip()]


def check_sla_breaches() -> dict[str, Any]:
    """One pass over open tickets. Safe to call concurrently with the
    background loop or a manual trigger — each ticket's stamp write is its own
    short transaction, so overlapping calls can at worst double-email a
    ticket in the same few seconds, never corrupt state."""
    from rag.schemas import sla_elapsed_fraction, sla_target_mins
    from guardrails.governance import audit
    from db.sqlite.models import SessionLocal, Ticket as TicketRow
    from integrations.notifications import send_email

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    recipients = _notify_recipients()

    with SessionLocal() as s:
        rows = (
            s.query(TicketRow)
            .filter(TicketRow.status.notin_(_CLOSED_STATUSES))
            .filter(TicketRow.sla_warning_sent_at.is_(None))
            .filter(TicketRow.severity.isnot(None))
            .filter(TicketRow.severity != "")
            .all()
        )

        checked = 0
        warned = 0
        for row in rows:
            frac = sla_elapsed_fraction(row.created_at, row.severity)
            if frac is None:
                continue
            checked += 1
            if frac < settings.SLA_WARNING_THRESHOLD:
                continue

            resolve_mins = sla_target_mins(row.severity, "resolve")
            due_at = row.created_at + timedelta(minutes=resolve_mins)
            subject, text_body, html_body = _breach_email(row, due_at, now)
            sent = send_email(recipients, subject, text_body, html_body) if recipients else False

            row.sla_warning_sent_at = now
            s.commit()
            warned += 1
            audit.record(
                "sla.warning_sent",
                resource=row.id,
                external_id=row.external_id,
                severity=row.severity,
                elapsed_pct=round(frac, 3),
                recipients=recipients,
                email_sent=sent,
            )
            if not recipients:
                log.warning(
                    "sla_monitor: %s crossed %.0f%% of SLA but no admin/manager "
                    "email is on file — nothing sent (flag still stamped so this "
                    "does not re-check every cycle)",
                    row.external_id or row.id,
                    settings.SLA_WARNING_THRESHOLD * 100,
                )

    log.info("sla_monitor: checked=%d warned=%d", checked, warned)
    return {"checked": checked, "warned": warned}


def _loop() -> None:
    while not _stop.is_set():
        try:
            check_sla_breaches()
        except Exception as exc:  # noqa: BLE001 - the loop must survive one bad cycle
            log.error("sla_monitor loop error: %s", exc)
        _stop.wait(settings.SLA_CHECK_SECONDS)


def start_sla_monitor() -> None:
    """Called once from run.py::create_app(). No-op if already running."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="sla-monitor", daemon=True)
    _thread.start()
    log.info(
        "SLA monitor started (threshold=%.0f%%, every %ds)",
        settings.SLA_WARNING_THRESHOLD * 100,
        settings.SLA_CHECK_SECONDS,
    )


def stop_sla_monitor() -> None:
    _stop.set()
