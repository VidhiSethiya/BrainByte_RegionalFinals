# servicebus-shipping-events runbook (azure)

## Symptom
Active message count rising on the shipping-events Service Bus subscription.

## Diagnosis
Compare ActiveMessages against OutgoingMessages on the subscription. A growing DeadLetteredMessages count means messages are exceeding MaxDeliveryCount, usually a schema change the consumer cannot deserialise. ServerBusy throttling instead indicates the namespace tier is undersized.

## Fix
Fix the consumer and resubmit from the DLQ. Raise the namespace tier only when ServerBusy is the actual cause.

## Escalate
High when shipping notifications are delayed beyond 30m, which is customer-visible. Medium when the backlog is bounded and draining. Highest only if order fulfilment stops.
