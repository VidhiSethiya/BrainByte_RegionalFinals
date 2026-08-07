# aurora-orders runbook (aws)

## Symptom
Connection pool thrashing on the Aurora orders database after a traffic spike.

## Diagnosis
DatabaseConnections at max_connections with only moderate CPUUtilization means a pool problem, not a query problem - the opposite pattern (CPU pinned, connections normal) is a slow-query issue. Check AbortedClients and the application pool config, since pools sized per-instance multiply by replica count. Deadlocks and BufferCacheHitRatio separate contention from cache pressure.

## Fix
Right-size the application pool, add a reader endpoint, or fail over. Raising max_connections alone usually moves the bottleneck to memory.

## Escalate
Highest when order placement fails outright, because that is the revenue path down. High when latency is elevated but orders still complete.
