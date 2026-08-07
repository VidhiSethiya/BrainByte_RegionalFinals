# entra-customer-api runbook (azure)

## Symptom
Entra ID token validation failing on customer-api; sign-ins rejected.

## Diagnosis
Check whether a Conditional Access policy changed recently - a new policy applies immediately and silently to service principals. AADSTS codes are precise: AADSTS700027 is a certificate mismatch, AADSTS50131 a CA policy block, AADSTS7000215 a bad client secret. An expired client secret or app-registration certificate is the usual root cause.

## Fix
Roll the client secret, exclude the service principal from the offending CA policy, or renew the certificate.

## Escalate
Highest when a customer-facing sign-in path is fully blocked. High when only one app registration fails. Always check whether a CA policy change was the trigger.
