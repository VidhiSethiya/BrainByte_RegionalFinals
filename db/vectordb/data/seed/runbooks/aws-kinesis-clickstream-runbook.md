# kinesis-clickstream runbook (aws)

## Symptom
Iterator age climbing on the clickstream Kinesis stream; processors falling behind.

## Diagnosis
GetRecords.IteratorAgeMilliseconds is the signal - it measures how stale the oldest unread record is. ProvisionedThroughputExceededException points at a hot shard from a skewed partition key; WriteProvisionedThroughputExceeded points at producers instead. A single malformed record can stall one shard while the others stay healthy.

## Fix
Reshard on a hot partition key, or scale processor concurrency. A poison record needs a checkpoint skip, not a stream reset.

## Escalate
High when iterator age exceeds 1 hour, or on any revenue-attribution stream. Medium for analytics-only streams under 1 hour. Clickstream is analytics, not customer-facing, so it rarely warrants Highest.
