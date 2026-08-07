# cloudsql-reporting runbook (gcp)

## Symptom
Elevated errors or latency on cloudsql-reporting.

## Diagnosis
Check dashboards, recent deploys, and error codes (ORA-01555, HTTP 502, KB5034441).

## Fix
Mitigate with rollback or scale-out; capture INC id.

## Escalate
If S1 for >15m, page gcp on-call.
