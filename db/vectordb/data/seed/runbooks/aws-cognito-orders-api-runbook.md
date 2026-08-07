# cognito-orders-api runbook (aws)

## Symptom
JWT validation failures spiking on orders-api; users rejected with 401.

## Diagnosis
A rejection storm after a quiet period is almost always key rotation - the JWKS endpoint published a new kid the API is not refreshing. Check the JWKS cache TTL, confirm iss and aud still match the user-pool config, and check clock skew on the validating host, since tokens fail exp/nbf once drift exceeds a few minutes.

## Fix
Force a JWKS refresh, correct iss/aud, or fix NTP drift. Do not disable validation to restore service.

## Escalate
Highest - an auth failure storm locks every user out of a customer-facing API, and disabling validation to mitigate would itself be a security incident.
