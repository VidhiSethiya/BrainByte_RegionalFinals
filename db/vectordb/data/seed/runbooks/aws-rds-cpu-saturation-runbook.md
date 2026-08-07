# AWS RDS CPU saturation — High (P2) database latency

Team: aws  
Applies to: Incidents where AWS RDS CPU is saturated and dependent apps see database latency  
Jira Priority: High (legacy P2)  
Service examples: Payments API, checkout, any workload on rds-prod / rds-prod-01

## Symptom
- Application or API latency rises (p95/p99); timeouts or connection pool exhaustion.
- CloudWatch (or RDS Performance Insights) shows **CPUUtilization** sustained high (often >80–90%).
- Database-facing errors: slow queries, lock waits, `too many connections`, HTTP 504/502 from APIs that depend on RDS.
- Ticket language often includes: "RDS CPU", "database latency", "DB slow", "saturation", "High / P2".

## Diagnosis
1. Confirm instance: note RDS identifier, engine (MySQL/Postgres/Aurora), region, and environment (prod/uat).
2. CloudWatch (last 1–3 hours):
   - CPUUtilization, FreeableMemory, DatabaseConnections, ReadLatency / WriteLatency, DiskQueueDepth.
3. Performance Insights / Top SQL:
   - Identify top CPU consumers (missing indexes, full scans, sudden query volume).
4. Correlate with change:
   - Recent deploys, schema migrations, batch jobs, traffic spikes, failover events.
5. Check replicas / Multi-AZ:
   - Failover in progress or replica lag can look like primary CPU pressure on the app.
6. Rule out noisy neighbour / undersized class before blaming a single query.

## Fix
Do **not** reboot production RDS as a first step.

1. **Stabilize traffic (if prod is failing hard)**  
   - Shed non-critical read traffic to replicas if available.  
   - Pause known heavy batch / reporting jobs that hit the primary.

2. **Kill or throttle the offender**  
   - From Performance Insights / `pg_stat_activity` / MySQL processlist, identify long-running or high-CPU sessions.  
   - Terminate runaway sessions only with change approval if they are clearly non-critical.

3. **Query / index mitigation**  
   - Add or confirm index for the hot query path when safe.  
   - Roll back the last deploy if latency started immediately after release.

4. **Scale only if capacity is the root cause**  
   - Vertical: move to a larger instance class (planned change).  
   - Horizontal: add/use read replicas for read-heavy paths.  
   - Record the incident id in the change record.

5. **Verify**  
   - CPUUtilization trend down; app p95 latency recovering; connection pool healthy.  
   - Leave a comment on the ticket with graphs + Top SQL summary.

## Escalate
- **Highest**: primary unresponsive, data risk, or no improvement within the High SLA respond window → page **aws** on-call and notify the support manager.
- **High (P2)** sustained >30 minutes with CPU still saturated after kill/throttle → escalate to aws on-call; keep TicketSphere decision on **aws** team.
- If Multi-AZ failover loops or storage full — treat as Highest and follow the RDS failover runbook (`aws-rds-prod-01-runbook`).

## Notes for TicketSphere
- Route to **aws**. Typical Priority **High** when prod is degraded but not fully down; **Highest** if writes fail or blast radius is payments checkout down with no workaround.
- Suggested first action: open Performance Insights → Top SQL for the saturated instance, then throttle or kill the top CPU session if approved.
