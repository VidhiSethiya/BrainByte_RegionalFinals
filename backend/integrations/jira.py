"""Jira Cloud REST API v3 adapter. Basic auth (account email + API token) against
`https://<site>.atlassian.net` — see the AI Fridays handbook §13.5 and
`.claude/plans/BLUEPRINT.md` §7 for the setup steps.

Poll-based sync is primary. `POST /api/integrations/webhook` exists and this
module's shape supports it, but the AI Lab's laptops sit outside the TCS network
with outbound-only internet — there is no public URL for Jira to call back to.
Polling needs nothing inbound, so it is what actually runs; the webhook path is
demoed with a local `curl` rather than a live Jira Automation rule. See
docs/JUDGES_QA.md.

Custom field IDs (Triage Severity, Priority Score, Routed Team, AI Confidence) are
per-site (`customfield_10xxx`) and cannot be guessed from documentation — they are
read from config with empty-string defaults, so an unconfigured field is silently
*not written* rather than written to the wrong place. Confirm the real IDs against
the board (Project settings -> Fields, or `GET /rest/api/3/issue/<key>?expand=names`
on any existing issue) and set them in `.env` once you have access.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from config import settings
from integrations.ticket_source import TicketSource
from observability.telemetry import log

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.5

# TicketSphere status -> Jira workflow transition *name*. Workflow names are a
# per-project-template choice in Jira and cannot be guessed reliably — these are
# the common Jira Software defaults. Confirm against the real board's workflow
# (Project settings -> Workflow) and adjust; a transition that doesn't exist by
# this name is skipped with a warning, never a crash.
STATUS_TO_TRANSITION_NAME: dict[str, str] = {
    "triaged": "In Progress",
    "routed": "In Progress",
    "synced": "In Progress",
    "resolved": "Done",
}


class JiraError(RuntimeError):
    pass


class JiraSource(TicketSource):
    name = "jira"

    def __init__(self) -> None:
        missing = [
            k
            for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY")
            if not getattr(settings, k)
        ]
        if missing:
            raise JiraError(
                f"TICKET_SOURCE=jira but {', '.join(missing)} not set in .env — "
                "see .claude/plans/BLUEPRINT.md §7 for how to get an API token"
            )
        token = base64.b64encode(f"{settings.JIRA_EMAIL}:{settings.JIRA_API_TOKEN}".encode()).decode()
        self._client = httpx.Client(
            base_url=settings.JIRA_BASE_URL,
            headers={
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=20,
            # Same TLS posture as ai/llm.py — off by default because corporate
            # TLS-inspecting proxies otherwise break the demo mid-build.
            verify=not settings.DISABLE_SSL_VERIFY,
        )

    # --- low-level request, with retry/backoff ---------------------------------

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            wait = BACKOFF_BASE_SECONDS * (2**attempt)
            try:
                resp = self._client.request(method, path, **kwargs)
                if resp.status_code == 429:
                    wait = self._retry_after_seconds(resp, attempt)
                    raise JiraError(f"{method} {path} -> 429 rate limited")
                if resp.status_code >= 500:
                    raise JiraError(f"{method} {path} -> {resp.status_code}: {resp.text[:200]}")
                return resp
            except Exception as exc:  # noqa: BLE001 - any transport/429/5xx failure retries
                last_exc = exc
                log.warning(
                    "Jira %s %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    method, path, attempt + 1, MAX_RETRIES, exc, wait,
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(wait)
        raise JiraError(f"{method} {path} failed after {MAX_RETRIES} attempts: {last_exc}")

    @staticmethod
    def _retry_after_seconds(resp: httpx.Response, attempt: int) -> float:
        """Honor Retry-After (seconds) when present; else exponential backoff."""
        header = (resp.headers.get("Retry-After") or "").strip()
        if header:
            try:
                return max(0.0, float(header))
            except ValueError:
                pass
        return BACKOFF_BASE_SECONDS * (2**attempt)

    # --- fetch -------------------------------------------------------------------

    def fetch_since(self, watermark: str | None, limit: int = 50) -> list[dict[str, Any]]:
        jql = f"project = {settings.JIRA_PROJECT_KEY}"
        if watermark:
            # JQL datetime literals want "yyyy-MM-dd HH:mm" (no seconds, quoted).
            jira_ts = watermark.replace("T", " ")[:16]
            jql += f' AND updated >= "{jira_ts}"'
        jql += " ORDER BY updated ASC"

        try:
            resp = self._request(
                "POST",
                "/rest/api/3/search/jql",
                json={
                    "jql": jql,
                    "maxResults": limit,
                    "fields": [
                        "summary", "description", "status", "priority", "reporter",
                        "assignee", "labels", "components", "updated", "created",
                        "issuetype",
                    ],
                },
            )
        except JiraError as exc:
            log.error("Jira search failed, returning no tickets this cycle: %s", exc)
            return []

        if resp.status_code != 200:
            log.error("Jira search -> %s: %s", resp.status_code, resp.text[:300])
            return []

        issues = resp.json().get("issues", [])
        return [issue_to_ticket_dict(issue) for issue in issues]

    # --- write-back ----------------------------------------------------------
    #
    # Verified against the real board (project SCRUM, "TicketSphere", team-managed
    # Software project — checked via the Atlassian connector, not assumed): the
    # only fields on the "Task"/"Request"/"Epic" issue types are Jira's stock set
    # — Summary, Description, Priority (Highest/High/Medium/Low/Lowest), Labels,
    # Assignee, a native Team picker, Sprint, Story points, Due date. None of
    # "Triage Severity" / "Priority Score" / "Routed Team" / "AI Confidence"
    # exist as custom fields — they were a BLUEPRINT.md §7 suggestion, never
    # actually created in Jira admin.
    #
    # Rather than block write-back on someone creating four custom fields, this
    # writes onto what the board already has, today, with zero admin setup:
    #   severity        -> native Priority field (S1->Highest .. S4->Low)
    #   team/severity   -> labels (ticketsphere-team-<x>, ticketsphere-severity-<x>)
    #   everything      -> the rationale comment (see add_comment / approve route)
    # JIRA_FIELD_* stay honoured *additionally* if a team later adds real custom
    # fields — set is set, but nothing here depends on them existing.

    _SEVERITY_TO_PRIORITY_ID = {"S1": "1", "S2": "2", "S3": "3", "S4": "4"}  # id "5"=Lowest unused

    def update(self, external_id: str, fields: dict[str, Any]) -> None:
        set_fields: dict[str, Any] = {}
        label_adds: list[str] = []

        severity = fields.get("severity")
        if severity:
            priority_id = self._SEVERITY_TO_PRIORITY_ID.get(severity)
            if priority_id:
                set_fields["priority"] = {"id": priority_id}
            label_adds.append(f"ticketsphere-severity-{severity}")

        if fields.get("assigned_team"):
            label_adds.append(f"ticketsphere-team-{fields['assigned_team']}")

        # Optional custom fields, only written if a team has actually created them.
        if "severity" in fields and settings.JIRA_FIELD_SEVERITY:
            set_fields[settings.JIRA_FIELD_SEVERITY] = {"value": fields["severity"]}
        if "priority_score" in fields and settings.JIRA_FIELD_PRIORITY_SCORE:
            set_fields[settings.JIRA_FIELD_PRIORITY_SCORE] = fields["priority_score"]
        if "assigned_team" in fields and settings.JIRA_FIELD_ROUTED_TEAM:
            set_fields[settings.JIRA_FIELD_ROUTED_TEAM] = {"value": fields["assigned_team"]}
        if "confidence" in fields and settings.JIRA_FIELD_AI_CONFIDENCE:
            set_fields[settings.JIRA_FIELD_AI_CONFIDENCE] = fields["confidence"]

        if not set_fields and not label_adds:
            log.warning("Jira update(%s, %s) — nothing mappable, nothing written",
                        external_id, list(fields.keys()))
            return

        body: dict[str, Any] = {}
        if set_fields:
            body["fields"] = set_fields
        if label_adds:
            body["update"] = {"labels": [{"add": label} for label in label_adds]}

        resp = self._request("PUT", f"/rest/api/3/issue/{external_id}", json=body)
        if resp.status_code not in (200, 204):
            raise JiraError(f"update {external_id} -> {resp.status_code}: {resp.text[:300]}")

    def add_comment(self, external_id: str, text: str) -> None:
        resp = self._request(
            "POST",
            f"/rest/api/3/issue/{external_id}/comment",
            json={"body": text_to_adf(text)},
        )
        if resp.status_code not in (200, 201):
            raise JiraError(f"comment {external_id} -> {resp.status_code}: {resp.text[:300]}")

    def transition(self, external_id: str, status: str) -> None:
        target = STATUS_TO_TRANSITION_NAME.get(status)
        if not target:
            return  # no Jira-side equivalent for this TicketSphere status

        resp = self._request("GET", f"/rest/api/3/issue/{external_id}/transitions")
        if resp.status_code != 200:
            log.warning("could not list transitions for %s: %s", external_id, resp.status_code)
            return

        transitions = resp.json().get("transitions", [])
        match = next((t for t in transitions if t.get("name", "").lower() == target.lower()), None)
        if not match:
            log.warning(
                "no Jira transition named %r on %s (available: %s) — confirm the "
                "workflow's real transition names in STATUS_TO_TRANSITION_NAME",
                target, external_id, [t.get("name") for t in transitions],
            )
            return

        resp = self._request(
            "POST",
            f"/rest/api/3/issue/{external_id}/transitions",
            json={"transition": {"id": match["id"]}},
        )
        if resp.status_code not in (200, 204):
            raise JiraError(f"transition {external_id} -> {resp.status_code}: {resp.text[:300]}")


# --- Atlassian Document Format (ADF) helpers ---------------------------------
# Jira Cloud's v3 API speaks ADF, not plain text, for description/comment bodies.
# These are deliberately minimal — enough to read a prose ticket description and
# post a prose rationale as a comment. Not a general ADF renderer; tables, code
# blocks and mentions in a real ticket description will lose their formatting
# (still get their text extracted, just flattened).


def who(user_obj: dict | None) -> str:
    """Best available identifier for a Jira user object (reporter/assignee/etc).

    Jira Cloud withholds `emailAddress` from most API responses by default (a
    GDPR-driven privacy setting, on regardless of plan) — verified against the
    real board: reporter/assignee came back with displayName + accountId only,
    no email. displayName is the identifier that is actually present.

    Module-level, not a method, so both JiraSource._to_ticket_dict() (the poller
    path) and api.py's webhook route (a second, independent ingestion path) call
    the same extraction logic rather than two copies that can drift apart — which
    is exactly what happened the first time: the webhook route built its raw
    ticket dict by hand and simply had no reporter/assignee keys at all.
    """
    if not user_obj:
        return ""
    return user_obj.get("emailAddress") or user_obj.get("displayName") or ""


def issue_to_ticket_dict(issue: dict) -> dict[str, Any]:
    """The one place a raw Jira issue payload becomes our raw-ticket dict shape.

    Called from two independent places — JiraSource.fetch_since() (the poller
    path) and api.py's POST /integrations/webhook (Jira Automation's push path).
    Module-level and stateless on purpose: those two call sites previously built
    this dict by hand, separately, and drifted — the webhook route was missing
    reporter/assignee entirely and hardcoded application="" instead of reading
    components. One function, both paths, can't drift apart again.
    """
    fields = issue.get("fields", {}) or {}
    components = [c.get("name", "") for c in (fields.get("components") or [])]
    return {
        "external_id": issue.get("key", ""),
        "source": "jira",
        "title": fields.get("summary") or "",
        "body": adf_to_text(fields.get("description")),
        "application": components[0] if components else "",
        "environment": "prod",
        "channel": "jira",
        "reporter": who(fields.get("reporter")),
        "assignee": who(fields.get("assignee")),
        "attachments": [],
        "raw": {
            "status": (fields.get("status") or {}).get("name", ""),
            "priority": (fields.get("priority") or {}).get("name", ""),
            "labels": fields.get("labels") or [],
            "issuetype": (fields.get("issuetype") or {}).get("name", ""),
        },
        "updated_at": fields.get("updated") or "",
    }


def adf_to_text(adf: dict | str | None) -> str:
    if not adf:
        return ""
    if isinstance(adf, str):  # some Jira configurations still return plain text
        return adf

    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text":
                parts.append(str(node.get("text", "")))
            for child in node.get("content") or []:
                walk(child)
            if node.get("type") in ("paragraph", "heading"):
                parts.append("\n")
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(adf)
    return "".join(parts).strip()


def text_to_adf(text: str) -> dict:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()] or [""]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}] if p else []}
            for p in paragraphs
        ],
    }
