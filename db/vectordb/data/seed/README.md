# TicketSphere seed corpus

Synthetic ITSM knowledge for hybrid retrieval demos.

## Contents (after `--generate`)

| Path | What |
|---|---|
| `tickets/INC*.json` | 400 indexable precedent tickets (team ACL, error codes, INC ids) |
| SQLite `tickets` | All 500 rows; 100 `held_out=true` with `true_category/severity/team` gold labels (never embedded) |
| `runbooks/*.md` | Per-service runbooks (`## Symptom / Diagnosis / Fix / Escalate`) |
| `service_catalog.md` | Service → owning team |
| `sla_policy.md` | S1–S4 respond/resolve minutes |
| `escalation_matrix.md` | Human-gate rules (restricted) |

## Commands

```bash
# Write corpus + gold labels (works without chromadb)
python db/vectordb/seed_vector_db.py --generate

# Full reseed (needs embeddings / chromadb / backend venv)
python db/vectordb/seed_vector_db.py --reset --generate
```

Indexed through the same pipeline as an API upload: load → anonymise → chunk → embed →
upsert. Ticket docs use `rag_indexer.index_ticket` with `doc_type=ticket_history`.

Why hybrid: corpus carries exact identifiers (`INC…`, `ORA-01555`, `HTTP 502`, `KB5034441`,
service names) that dense embeddings blur — BM25 recovers them.
