# alb-payments-api runbook (aws)

## Symptom
Elevated HTTP 502 from the ALB fronting payments-api.

## Diagnosis
A 502 from an ALB means the target closed the connection, not that the ALB failed. Compare HTTPCode_ELB_5XX_Count against HTTPCode_Target_5XX_Count: if only the ELB count is up, targets are dropping connections. The classic cause is a target keep-alive timeout shorter than the ALB idle timeout. Also check UnHealthyHostCount and recent deploys.

## Fix
Set the target keep-alive above the ALB idle timeout (60s default), or restore healthy targets.

## Escalate
Highest when the payment path is affected and error rate exceeds 5%. High between 1% and 5%. Payments is revenue-path, so treat it a band above the same failure elsewhere.
