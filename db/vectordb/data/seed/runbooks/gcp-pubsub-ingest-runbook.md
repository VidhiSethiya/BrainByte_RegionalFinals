# pubsub-ingest runbook (gcp)

## Symptom
Elevated errors or latency on pubsub-ingest.

## Diagnosis
Check dashboards, recent deploys, and error codes (ORA-01555, HTTP 502, KB5034441).

## Fix
Mitigate with rollback or scale-out; capture INC id.

## Escalate
If Highest for >15m, page gcp on-call.
