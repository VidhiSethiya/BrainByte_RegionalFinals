# iap-admin-api runbook (gcp)

## Symptom
Identity-Aware Proxy rejecting requests to admin-api.

## Diagnosis
Check the IAP-signed JWT assertion header and whether the backend still trusts the IAP audience. A recent IAM change removing roles/iap.httpsResourceAccessor is the most common cause. Confirm the OAuth consent-screen config is intact and the backend health check is passing, because IAP fails closed on an unhealthy backend.

## Fix
Restore the IAM binding or fix the backend health check. Do not bypass IAP to restore access.

## Escalate
High - admin-api is internal-facing, so the blast radius is staff rather than customers. Highest only when it blocks incident-response tooling during an active incident.
