# appgw-catalog-api runbook (azure)

## Symptom
Application Gateway returning 502 Bad Gateway for catalog-api.

## Diagnosis
Check backend health in the Application Gateway blade first - it names the exact failure. Common causes are a probe path returning non-200, an expired backend certificate when end-to-end TLS is enabled, or an NSG blocking the gateway subnet. BackendConnectTime spiking with healthy probes points at backend saturation instead.

## Fix
Correct the probe path, renew the backend certificate, or open the NSG rule.

## Escalate
High when catalogue browsing degrades but customers can still transact. Highest if checkout depends on it and is failing too.
