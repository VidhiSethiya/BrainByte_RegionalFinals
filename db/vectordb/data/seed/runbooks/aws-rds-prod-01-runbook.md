# rds-prod-01 runbook (aws)

## Symptom
Elevated errors or latency on rds-prod-01.

## Diagnosis
Check dashboards, recent deploys, and error codes (ORA-01555, HTTP 502, KB5034441).

## Fix
Mitigate with rollback or scale-out; capture INC id.

## Escalate
If S1 for >15m, page aws on-call.
