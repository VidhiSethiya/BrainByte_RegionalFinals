# kafka-payments-fraud runbook (ops)

## Symptom
Consumer group lag growing on the payments.fraud topic; fraud checks falling behind live transactions.

## Diagnosis
kafka-consumer-groups --describe gives per-partition LAG. Lag on one partition means a stuck consumer or a skewed key; lag across all partitions means the group is under-provisioned or stuck rebalancing. Look for a rebalance storm in the consumer log and confirm slow processing is not exceeding max.poll.interval.ms.

## Fix
Add consumers up to the partition count; beyond that, repartition. A rebalance loop usually needs max.poll.records lowered, not more consumers.

## Escalate
Highest - fraud scoring lagging means transactions clear unchecked, which is financial exposure and a compliance issue, not just latency. Page ops on-call regardless of lag size.
