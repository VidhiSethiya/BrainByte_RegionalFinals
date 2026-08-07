# sqs-payments-settlement runbook (aws)

## Symptom
Queue depth on the payments-settlement SQS queue growing faster than consumers drain it.

## Diagnosis
ApproximateNumberOfMessagesVisible rising while NumberOfMessagesDeleted is flat means consumers are down or erroring. ApproximateAgeOfOldestMessage matters more than depth on a settlement queue, because it measures how long money has been delayed. Inspect the DLQ for a poison message, and confirm consumer task health before scaling.

## Fix
Scale consumers, or fix and redrive the DLQ. Never purge a settlement queue - every message is a financial event.

## Escalate
Highest when oldest-message age exceeds 15m on a settlement or payment queue. High when depth is growing but age is under 15m. Medium when the backlog is already draining.
