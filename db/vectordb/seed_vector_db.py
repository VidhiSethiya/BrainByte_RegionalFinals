"""Load seed documents into Chroma + generate the TicketSphere corpus.

    python db/vectordb/seed_vector_db.py                 # index seed/*
    python db/vectordb/seed_vector_db.py --reset         # drop collection first
    python db/vectordb/seed_vector_db.py --generate      # write synthetic corpus
    python db/vectordb/seed_vector_db.py --reset --generate

Uses the same `index_document` / `index_ticket` paths as the upload API.
Gold labels for held-out tickets live only in SQLite `tickets.true_*`.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "backend"))

from config import settings  # noqa: E402
from db.sqlite.models import SessionLocal, Ticket, init_db  # noqa: E402
from observability.telemetry import log  # noqa: E402

SUPPORTED = {".txt", ".md", ".log", ".csv", ".json", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".pdf"}

TEAMS = ["ops", "azure", "aws", "gcp"]
SEVERITIES = ["S1", "S2", "S3", "S4"]
CATEGORIES = [
    "availability",
    "performance",
    "security",
    "networking",
    "storage",
    "identity",
    "database",
    "deployment",
]
SERVICES = {
    "ops": ["payments-api", "checkout-svc", "edge-proxy"],
    "azure": ["aks-prod-01", "azure-sql-01", "func-billing"],
    "aws": ["rds-prod-01", "eks-payments", "lambda-notify"],
    "gcp": ["gke-analytics", "cloudsql-reporting", "pubsub-ingest"],
}
ERROR_CODES = ["ORA-01555", "HTTP 502", "KB5034441", "ECONNRESET", "OOMKilled"]
SYMPTOMS = [
    "intermittent timeouts under load",
    "sudden spike in 5xx responses",
    "failover completed but replicas lag",
    "auth tokens rejected after rotate",
    "disk pressure on data volume",
    "DNS resolution flapping",
    "queue depth climbing past SLO",
    "it's broken",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the vector database")
    parser.add_argument("--path", default=None, help="directory of documents")
    parser.add_argument("--reset", action="store_true", help="drop the collection first")
    parser.add_argument("--generate", action="store_true", help="write TicketSphere seed corpus")
    parser.add_argument(
        "--roles",
        default="admin,manager",
        help="default roles for non-ticket seed docs",
    )
    parser.add_argument("--sensitivity", default="internal")
    parser.add_argument("--tickets", type=int, default=500, help="tickets to generate")
    parser.add_argument("--held-out", type=int, default=100, help="held-out (not indexed)")
    args = parser.parse_args()

    init_db()
    if args.reset:
        from db.sqlite.models import Document, SessionLocal as _Session
        from db.vectordb import vector_store

        vector_store.reset()
        with _Session() as s:
            s.query(Document).delete()
            s.commit()
        log.info("collection reset (chroma + documents mirror cleared)")

    directory = Path(args.path) if args.path else settings.SEED_DIR
    directory.mkdir(parents=True, exist_ok=True)

    if args.generate:
        _generate_corpus(directory, total=args.tickets, held_out=args.held_out)

    try:
        return _index_seed(directory, roles=args.roles, sensitivity=args.sensitivity)
    except ModuleNotFoundError as exc:
        if args.generate:
            log.error("index skipped — missing dependency %s (corpus files + gold labels written)", exc)
            return 0
        raise


def _generate_corpus(directory: Path, total: int = 500, held_out: int = 100) -> None:
    rng = random.Random(42)
    tickets_dir = directory / "tickets"
    runbooks_dir = directory / "runbooks"
    tickets_dir.mkdir(parents=True, exist_ok=True)
    runbooks_dir.mkdir(parents=True, exist_ok=True)

    # Clear prior generated ticket JSON so re-generate is clean.
    for old in tickets_dir.glob("*.json"):
        old.unlink()

    indexed_n = max(0, total - held_out)
    rows: list[dict] = []
    for i in range(1, total + 1):
        team = TEAMS[(i - 1) % len(TEAMS)]
        category = CATEGORIES[(i - 1) % len(CATEGORIES)]
        severity = SEVERITIES[(i - 1) % len(SEVERITIES)]
        service = rng.choice(SERVICES[team])
        err = rng.choice(ERROR_CODES)
        symptom = rng.choice(SYMPTOMS)
        external_id = f"INC{i:07d}"
        plant_secret = i % 40 == 0
        body_parts = [
            f"Summary\n{service} — {symptom}",
            f"\nDescription\nSeeing {err} on {service} in prod. {symptom}.",
            f"\nEnvironment\nprod",
            f"\nLogs\n[{external_id}] {err} stack near handler; correlation 8837462910",
        ]
        if plant_secret:
            body_parts.append(
                "\nNotes\nReporter pasted key AKIAIOSFODNN7EXAMPLE by mistake; "
                "email ops.oncall@example.com EMP-10442"
            )
        if i % 17 == 0:
            body_parts.append("\nResolution\nRolled back bad deploy; MTTR 42 mins.")

        title = f"{service}: {symptom}"
        body = "".join(body_parts)
        is_held = i > indexed_n
        record = {
            "external_id": external_id,
            "source": "synthetic",
            "title": title,
            "body": body,
            "application": service,
            "environment": "prod",
            "channel": "synthetic",
            "team": team,
            "category": category,
            "severity": severity,
            "resolved": i % 17 == 0,
            "resolution_minutes": 42 if i % 17 == 0 else None,
            "true_category": category,
            "true_severity": severity,
            "true_team": team,
            "held_out": is_held,
        }
        rows.append(record)
        if not is_held:
            (tickets_dir / f"{external_id}.json").write_text(
                json.dumps({k: v for k, v in record.items() if k != "held_out"}, indent=2),
                encoding="utf-8",
            )

    _write_policy_docs(directory, runbooks_dir)
    _upsert_ticket_rows(rows)
    log.info(
        "generated %d tickets (%d index / %d held-out) + runbooks/policies under %s",
        total,
        indexed_n,
        held_out,
        directory,
    )


def _write_policy_docs(directory: Path, runbooks_dir: Path) -> None:
    for team, services in SERVICES.items():
        for svc in services:
            path = runbooks_dir / f"{team}-{svc}-runbook.md"
            path.write_text(
                f"# {svc} runbook ({team})\n\n"
                f"## Symptom\nElevated errors or latency on {svc}.\n\n"
                f"## Diagnosis\nCheck dashboards, recent deploys, and error codes "
                f"(ORA-01555, HTTP 502, KB5034441).\n\n"
                f"## Fix\nMitigate with rollback or scale-out; capture INC id.\n\n"
                f"## Escalate\nIf S1 for >15m, page {team} on-call.\n",
                encoding="utf-8",
            )

    (directory / "service_catalog.md").write_text(
        "# Service catalogue\n\n"
        + "\n".join(
            f"- `{svc}` owned by **{team}**"
            for team, svcs in SERVICES.items()
            for svc in svcs
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "sla_policy.md").write_text(
        "# SLA matrix\n\n"
        "| Severity | Respond (mins) | Resolve (mins) |\n"
        "|---|---|---|\n"
        "| S1 | 15 | 240 |\n"
        "| S2 | 30 | 480 |\n"
        "| S3 | 120 | 1440 |\n"
        "| S4 | 480 | 4320 |\n",
        encoding="utf-8",
    )
    (directory / "escalation_matrix.md").write_text(
        "# Escalation matrix\n\n"
        "- S1 always requires human approval before sync.\n"
        "- Confidence < 0.70 → awaiting_approval.\n"
        "- Injection / secret findings → park for manager review.\n",
        encoding="utf-8",
    )


def _upsert_ticket_rows(rows: list[dict]) -> None:
    keep_ids = {(row["source"], row["external_id"]) for row in rows}
    with SessionLocal() as s:
        # Drop stale synthetic rows so a 10-ticket generate does not leave 500 leftovers.
        for old in s.query(Ticket).filter_by(source="synthetic").all():
            if (old.source, old.external_id) not in keep_ids:
                s.delete(old)
        for row in rows:
            existing = (
                s.query(Ticket)
                .filter_by(source=row["source"], external_id=row["external_id"])
                .first()
            )
            fields = {
                "title": row["title"],
                "body_masked": row["body"],  # masked at index time; raw kept for seed only
                "application": row["application"],
                "environment": row["environment"],
                "channel": row["channel"],
                "category": row["category"],
                "severity": row["severity"],
                "assigned_team": row["team"],
                "status": "new",
                "true_category": row["true_category"],
                "true_severity": row["true_severity"],
                "true_team": row["true_team"],
                "held_out": row["held_out"],
            }
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
            else:
                s.add(
                    Ticket(
                        external_id=row["external_id"],
                        source=row["source"],
                        **fields,
                    )
                )
        s.commit()


def _index_seed(directory: Path, roles: str, sensitivity: str) -> int:
    from db.vectordb import vector_store
    from rag import rag_indexer

    default_roles = [r.strip() for r in roles.split(",") if r.strip()]
    total_chunks = 0
    failed = 0
    indexed_files = 0

    # Ticket JSON first — team ACL on each.
    for path in sorted((directory / "tickets").glob("*.json")) if (directory / "tickets").exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            team = data.get("team") or "ops"
            result = rag_indexer.index_ticket(
                {
                    "external_id": data["external_id"],
                    "source": data.get("source", "synthetic"),
                    "title": data["title"],
                    "body": data["body"],
                    "application": data.get("application", ""),
                    "environment": data.get("environment", "prod"),
                    "channel": data.get("channel", "synthetic"),
                    "raw": {"team": team},
                },
                allowed_roles=[team, "manager", "admin"],
                sensitivity="confidential",
                resolved=bool(data.get("resolved")),
                resolution_minutes=data.get("resolution_minutes"),
                category=data.get("category", ""),
                severity=data.get("severity", ""),
                team=team,
                service=data.get("application", ""),
                anonymize=True,
            )
            total_chunks += result.get("chunks", 0)
            indexed_files += 1
            log.info("  %-40s %3d chunks (ticket/%s)", path.name, result.get("chunks", 0), team)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            log.error("  %-40s FAILED: %s", path.name, exc)

    # Policy / runbook docs — manager+admin; shared runbooks also tagged per team in path.
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if "tickets" in path.parts and path.suffix.lower() == ".json":
            continue
        if path.suffix.lower() not in (SUPPORTED - {".json"}):
            continue
        try:
            doc_roles = list(default_roles)
            doc_type = "runbook"
            name = path.name.lower()
            if "sla" in name:
                doc_type = "sla_policy"
            elif "escalat" in name:
                doc_type = "escalation_matrix"
            elif "catalog" in name or "catalogue" in name:
                doc_type = "service_catalog"
            team_tag = next((t for t in TEAMS if t in path.name.lower()), None)
            if team_tag:
                doc_roles = list({*doc_roles, team_tag})

            result = rag_indexer.index_file(
                path,
                id=path.stem.lower().replace(" ", "-"),
                allowed_roles=doc_roles,
                sensitivity=sensitivity if doc_type != "escalation_matrix" else "restricted",
                attributes={"doc_type": doc_type, **({"team": team_tag} if team_tag else {})},
            )
            total_chunks += result["chunks"]
            indexed_files += 1
            log.info("  %-40s %3d chunks", path.name, result["chunks"])
        except Exception as exc:  # noqa: BLE001
            failed += 1
            log.error("  %-40s FAILED: %s", path.name, exc)

    if indexed_files == 0:
        log.error("no supported files in %s — run with --generate first", directory)
        return 1

    log.info(
        "seeded %d files, %d chunks, collection now holds %d",
        indexed_files - failed,
        total_chunks,
        vector_store.count(),
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
