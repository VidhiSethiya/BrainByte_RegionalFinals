# httpslb-recommendations-api runbook (gcp)

## Symptom
HTTPS Load Balancer returning 502 with timeouts to recommendations-api.

## Diagnosis
backend_connection_closed_before_data_sent_to_client in the LB logs means the backend closed early, usually because the backend timeout is below the LB default of 30s. Check the backend service timeout and health-check config. A NEG with no healthy endpoints returns 502 immediately.

## Fix
Raise the backend timeout above the LB timeout, or restore healthy NEG endpoints.

## Escalate
Medium - recommendations degrade the experience but do not block purchase, and the page renders without them. High only when the failure cascades into the product page itself.
