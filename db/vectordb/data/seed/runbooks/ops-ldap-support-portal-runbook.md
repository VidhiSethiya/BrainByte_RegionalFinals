# ldap-support-portal runbook (ops)

## Symptom
LDAP bind failures cascading into support-portal login failures.

## Diagnosis
Bind failures come from directory replication lag, an exhausted connection pool, or an expired service-account password. Compare nsslapd-currentconnections against nsslapd-maxdescriptors and check replication agreement status. A cascade into dependent apps means their pools are exhausted downstream, not that each app broke independently.

## Fix
Restore the directory, then restart dependent pools - they will not recover connections on their own.

## Escalate
Highest when staff cannot authenticate to a customer-support tool during business hours, because support cannot then serve customers. High outside business hours.
