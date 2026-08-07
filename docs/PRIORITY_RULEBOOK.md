# TicketSphere — Priority Rulebook

**Version:** `1.0.0` · **Status:** normative · **Owner:** platform governance
**Applies to:** every ticket entering the triage graph, from any source

> This file is **injected verbatim into the assessment prompt**, not retrieved by RAG.
> That is deliberate — see §2. Changing this file changes how every subsequent decision
> is scored, so it is versioned and its hash is stamped onto every `triage_runs` row.

---

## 1. Why this file exists

The first version of TicketSphere asked a language model to emit
`priority_score: 0–100` directly. Nobody — not a reviewer, not an engineer, not the
model itself on a second run — could explain why a ticket scored 72 rather than 65.
An unfalsifiable number is not a decision; it is an opinion wearing a decision's clothes.

This rulebook replaces that with a **scoring schema**:

| The model does | The code does |
|---|---|
| Reads the ticket and retrieved context | — |
| Rates **15 named metrics** on a 0–4 anchored scale | — |
| Quotes the evidence for each rating, or marks it `not_stated` | — |
| — | Computes Impact, Urgency, band, and score **arithmetically** |
| — | Applies hard override rules |
| — | Computes confidence from coverage, margin and precedent |

The model contributes **judgement about evidence**. It never contributes arithmetic.
This is the same principle already applied to `ticket_stats` ("the LLM never counts") —
this file extends it to the highest-stakes decision in the product, where it was
previously being violated.

**The property this buys:** given the same 15 ratings, the score is reproducible by hand.
A reviewer can disagree with a *rating* (and point at the quoted evidence), which is a
productive argument. Nobody can disagree with a number that came from nowhere, which is
not an argument at all.

---

## 2. Injected, never retrieved

This rulebook is loaded from disk and placed in the prompt in full, for every assessment.

It is **not** chunked into Chroma and retrieved by similarity, even though the rest of the
knowledge corpus is. The reason is decisive: retrieval returns *some* of a document. Two
identical tickets could retrieve different rulebook fragments and be scored against
different criteria — the scoring would be non-deterministic in a way no one could see.
A rubric must be applied whole or it is not a rubric.

The SLA policy, runbooks and precedent tickets **are** retrieved normally. Those are
evidence; this is the measuring instrument. Evidence varies per ticket; the instrument
must not.

---

## 3. Two input axes, one output band

"Severity" and "priority" were used interchangeably in review, and that ambiguity is the
root of the "how do you segregate P1/P2/P3" question. The product now has **one** scale —
`P1`–`P4` — and it is computed from **two** measured axes:

- **Impact** — *how bad is it?* Blast radius, business criticality, data, security.
  Independent of who is watching or how fast the clock is running.
- **Urgency** — *how fast must we act?* Trend, burn rate, workarounds, deadlines.
- **Priority** — the output. `Priority = matrix(Impact, Urgency)`, then override rules.

There is no separate severity scale to reconcile any more. Keeping one meant three
vocabularies for one concept (`S1–S4` in storage, `Highest/High/Medium/Low` in the UI,
`P1/P2/P3` in conversation) — which is how a dashboard ends up rendering blank tiles
because two layers disagreed about what a row was called. That happened here, and it is
why the rename was worth the churn.

A single flat weighted sum cannot express this. A cosmetic bug on a revenue page during a
sale window and a total outage of an internal dev tool can produce the same sum while
demanding completely different responses. Two axes, then a matrix, is the standard ITIL
treatment and it is readable — a reviewer can point at a cell.

### Canonical vocabulary

`P1`–`P4` is the **internal** vocabulary — this rulebook, the `tickets.severity` column,
the scoring code and the graph all reason in bands. **Users and Jira see the Priority
names** (`Highest/High/Medium/Low`), because that is the language the board already speaks
and the console was built in.

| Band *(internal)* | Shown to users & written to Jira | Means | Also accepted on input | Response target |
|---|---|---|---|---|
| **P1** | `Highest` | critical — act now | `S1` | 15 min ack · 60 min resolve |
| **P2** | `High` | high | `S2` | 30 min ack · 4 h resolve |
| **P3** | `Medium` | medium | `S3` | 4 h ack · 24 h resolve |
| **P4** | `Low` | low | `S4` | next business day · 5 d |

The translation happens at exactly three boundaries, all calling the same table in
`rag/schemas.py`:

| Boundary | Function | Direction |
|---|---|---|
| API responses (`Ticket.to_dict()`) | `to_jira_priority()` | P1–P4 → `Highest` |
| Analytics payload (`triage_analytics()`) | `to_jira_priority()` | P1–P4 → `Highest` |
| Jira write-back (`priority_group()`) | `to_jira_priority()` | P1–P4 → `Highest` |
| Anything inbound — filters, overrides, old rows | `to_priority()` | any form → P1–P4 |

`to_priority()` accepts all three vocabularies, so a bookmarked URL, an un-migrated row or
an older client still resolves instead of silently matching nothing — which is exactly the
failure that blanked the Control Tower tiles before this was centralised.

SLA targets above are the default set — the indexed SLA policy document overrides them per
customer tier where one applies, and the retrieved value always wins over this table.

---

## 4. The 15 metrics

Each is rated **0–4** against its anchors. `weight` is the metric's contribution to its
axis. A metric with no supporting evidence is rated `not_stated` and **excluded from the
denominator** — not scored 0. Scoring unknowns as zero systematically under-severities
thinly-written tickets, which is the exact failure mode that gets a triage system
distrusted. Exclusion instead lowers `evidence_coverage`, which lowers confidence, which
routes the ticket to a human. Unknowns become *questions*, not silent downgrades.

### 4.1 Impact axis — "how bad is it" (8 metrics)

| # | Metric | Weight | 0 | 2 | 4 |
|---|---|---|---|---|---|
| **I1** | **User / tenant blast radius** | 3 | single user | one team or tenant | all users, or >25% of tenants |
| **I2** | **Business function criticality** | 3 | internal convenience | internal operations | revenue path, payments, regulated, or customer-facing SLA'd |
| **I3** | **Financial exposure rate** | 2 | none quantified | measurable but bounded | continuous revenue loss, or SLA credits accruing |
| **I4** | **Availability degradation shape** | 3 | cosmetic / informational | partial or intermittent failure | complete outage of the service |
| **I5** | **Data loss or corruption** | 3 | none, all recoverable | at risk, not yet lost | confirmed loss or corruption of customer data |
| **I6** | **Security & secret exposure** | 3 | none | hardening gap, no exposure | credential/secret exposed, or unauthorised access observed |
| **I7** | **Regulatory & contractual exposure** | 2 | none | contractual attention likely | notification clock started (DPDP/GDPR), or a hard SLA breached |
| **I8** | **Dependency criticality** | 2 | leaf service, no dependants | one dependent service | shared platform / control-plane — failure cascades |

### 4.2 Urgency axis — "how fast must we act" (7 metrics)

| # | Metric | Weight | 0 | 2 | 4 |
|---|---|---|---|---|---|
| **U1** | **SLO / error-budget burn rate** | 3 | within budget | elevated, budget consumed in days | fast burn — budget exhausted in hours |
| **U2** | **Trend direction** | 3 | recovered / self-healed | stable | actively worsening |
| **U3** | **Workaround availability** | 3 | automatic, transparent to users | manual but effective | none available |
| **U4** | **Time & window sensitivity** | 2 | off-peak, no deadline | business hours | peak window, batch cutoff, or contractual deadline imminent |
| **U5** | **Change correlation & rollback window** | 2 | no recent change | change suspected, rollback available | rollback window closing, or change already propagating |
| **U6** | **Recovery complexity (est. MTTR)** | 2 | minutes, well-documented runbook | hours, known procedure | unknown path, or precedent MTTR exceeds the SLA target |
| **U7** | **Escalation clock already running** | 1 | just raised | ageing within target | response target already missed, or customer has escalated |

Weights are deliberately coarse (1 / 2 / 3). Finer weights would be false precision — the
ratings themselves are 5-point judgements, and no amount of decimal places in a weight
makes a "2 vs 3" judgement more accurate. **What matters is which band the ticket lands
in, not whether it scored 71 or 74.**

---

## 5. Cloud-specific evidence signals

The rulebook is cloud-agnostic; the *evidence* is not. These are the observable signals a
rater should look for in ticket bodies, log excerpts and monitoring output. Presence of a
named signal is what turns a rating from `not_stated` into an evidenced score.

### 5.1 AWS

| Metric | Signals |
|---|---|
| I1, I4 | ALB `HTTPCode_ELB_5XX_Count`, `UnHealthyHostCount`, `TargetResponseTime`; API Gateway `5XXError`, `Count`; CloudFront error rate |
| I4, I8 | EKS nodes `NotReady`, pods `CrashLoopBackOff`, `ingress-nginx` upstream errors; Route 53 health-check failures |
| I5 | RDS `ReplicaLag`, failed snapshot/PITR, DynamoDB conditional-write failures, S3 versioning/replication errors |
| I6 | GuardDuty findings, CloudTrail anomalous `ConsoleLogin` / `AssumeRole`, exposed `AKIA…` key, Secrets Manager rotation failure |
| I8 | AWS Health / Personal Health Dashboard event, control-plane API throttling (`RequestLimitExceeded`) |
| U1 | CloudWatch composite alarm state, SLO burn via CloudWatch Metric Math |
| U2, U6 | RDS `CPUUtilization`, `DatabaseConnections` vs `max_connections`; Lambda `Throttles`, `Duration`, `ConcurrentExecutions` vs reserved |
| U5 | CodeDeploy / CloudFormation stack event immediately preceding onset |

### 5.2 Azure

| Metric | Signals |
|---|---|
| I1, I4 | Application Gateway / Front Door backend health, 5xx rate; App Service HTTP `Http5xx`; Traffic Manager endpoint status |
| I4, I8 | AKS nodes `NotReady`, kubelet `node status update failed`, pods `CrashLoopBackOff`; Azure Service Health advisory |
| I5 | Cosmos DB `429` RU throttling with write loss, SQL DB geo-replication lag, Storage soft-delete/versioning failure |
| I6 | Key Vault `403 Forbidden` after rotation, managed-identity token failures, Defender for Cloud alert, Entra ID risky sign-in |
| I8 | Azure Resource Manager throttling, subscription-level quota exhaustion, regional Service Health incident |
| U1 | Azure Monitor SLO / burn-rate alert, Application Insights failure rate |
| U2, U6 | Blob `SuccessE2ELatency` / `Availability`, Cosmos `NormalizedRUConsumption`, AKS node pool scale events |
| U5 | Deployment slot swap, ARM/Bicep deployment, or secret rotation immediately preceding onset |

### 5.3 GCP

| Metric | Signals |
|---|---|
| I1, I4 | Cloud Load Balancing 5xx, Cloud Run request error rate, Apigee/API Gateway failures |
| I4, I8 | GKE pods `Pending` (`Insufficient cpu`), `cluster-autoscaler` scale-up duration, node pool quota exhaustion |
| I5 | Cloud SQL `replication_lag_seconds`, WAL receiver reconnect loops, Spanner commit failures, GCS object-versioning errors |
| I6 | Security Command Center finding, exposed service-account key, IAM policy change granting broad access |
| I8 | Google Cloud Service Health incident, project/org-level quota exhaustion, shared VPC control-plane failure |
| U1 | Cloud Monitoring SLO burn-rate alert, uptime-check failures |
| U2, U6 | Pub/Sub `oldest_unacked_message_age`, `num_undelivered_messages`; Cloud Run revision `Ready=false`, startup-probe failures |
| U5 | Cloud Deploy / Cloud Build rollout, revision traffic split, config change preceding onset |

### 5.4 Cloud-neutral enterprise signals

Applies regardless of provider: change-advisory records (CAB/CR id), customer escalation
emails, contractual SLA clock in the MSA, on-call page history, dependent-team incident
bridges, and status-page commitments already published.

---

## 6. Scoring algorithm

Deterministic. Implemented in Python, not in the prompt.

```
For each axis A ∈ {Impact, Urgency}:
    applicable = metrics on A where rating ≠ not_stated
    if applicable is empty:
        A_score = None                       → forces needs_human
    else:
        A_score = 100 × Σ(rating_i × weight_i) / (4 × Σ weight_i)   for i ∈ applicable

Impact band:   Extensive ≥75 · Significant 50–74 · Moderate 25–49 · Minor <25
Urgency band:  Critical  ≥75 · High        50–74 · Medium   25–49 · Low   <25
```

### 6.1 The priority matrix

Read the band off the cell. This is the answer to "how do you segregate P1 from P2".

| Impact ↓ / Urgency → | **Critical** | **High** | **Medium** | **Low** |
|---|---|---|---|---|
| **Extensive** | **P1** | **P1** | **P2** | **P3** |
| **Significant** | **P1** | **P2** | **P2** | **P3** |
| **Moderate** | **P2** | **P3** | **P3** | **P4** |
| **Minor** | **P3** | **P3** | **P4** | **P4** |

### 6.2 priority_score — ordering, not banding

```
priority_score = round(0.6 × Impact_score + 0.4 × Urgency_score)      # 0–100
```

This number **does not decide the band.** The matrix decides the band. `priority_score`
exists only to order the queue *within* a band, so an engineer looking at nine P2s knows
which to open first. Impact is weighted above Urgency because a queue sorted by damage is
more useful than one sorted by haste.

Separating these two jobs is what makes the number explainable. Previously one number was
being asked to both decide the band and order the queue, and it did neither legibly.

---

## 7. Override rules

A weighted average dilutes a single catastrophic fact — confirmed data loss averaged
against twelve benign metrics can land in P3. These rules run **after** the matrix and
are absolute.

**Escalators** — each requires cited evidence, or it does not fire:

| id | Condition | Effect |
|---|---|---|
| `E1` | Confirmed loss or corruption of customer data (`I5 = 4`) | → **P1** |
| `E2` | Credential/secret exposed, or unauthorised access observed (`I6 = 4`) | → **P1** |
| `E3` | Multi-region outage, or control-plane failure of a shared platform service | → **P1** |
| `E4` | Complete outage (`I4 = 4`) of a revenue-path service (`I2 = 4`) | → **P1** |
| `E5` | Regulatory notification clock started (`I7 = 4`) | → at least **P2** |

**Dampeners** — cap the band; never raise it:

| id | Condition | Effect |
|---|---|---|
| `D1` | Confirmed self-healed *and* no residual customer impact | cap at **P3** |
| `D2` | Non-production only, no prod-bound release blocked | cap at **P3** |
| `D3` | Cosmetic or single-user, with an effective workaround | cap at **P4** |
| `D4` | Duplicate of an open incident | inherit the parent's band |

**Escalators beat dampeners.** If both fire, the escalator wins and the conflict is
recorded on the decision — a ticket that is both "self-healed" and "leaked a credential"
is a P1 with a note, never a P3.

Every fired rule is written onto the decision by id, so "why is this a P1 when it scored
41?" has a one-line answer: `E2 — credential exposure, evidence: "KeyVaultClient
get_secret … status=403"`.

---

## 8. Confidence

This section was rewritten after review. The first version was wrong in an instructive
way, and the correction is worth stating because a reviewer will find the same flaw.

### 8.1 What was wrong the first time

The original design was a single float the model reported about itself. That is
uninterpretable — a model's stated certainty is not calibrated against anything, and no
one can audit it.

The first fix decomposed it into three named components and **blended them**:

```
confidence = 0.45 × evidence_coverage + 0.30 × band_margin + 0.25 × precedent_agreement
```

That is better, but it still fails on two counts:

1. **The weights are as arbitrary as the number they replaced.** Where does `0.45` come
   from? Nowhere. A reviewer who rejected "72" should reject "0.45" for exactly the same
   reason. The arbitrariness moved down a level; it did not go away.
2. **Averaging hides the one thing that matters.** A ticket with perfect evidence
   (`coverage = 1.0`) sitting one point from a band boundary (`margin = 0.02`) blends to
   roughly `0.75` — which reads as *confident*. It is not confident. It is a coin flip
   wearing a good score. The blend actively conceals the risk it was built to expose.

Point 2 is the same mistake this rulebook already refuses to make in §7: an average
cannot express a veto. It was applied to the metrics and not, at first, to the confidence
built on top of them.

### 8.2 Scale — shown out of 10, stored as a probability

Confidence is **displayed on a 0–10 scale** and **stored as a probability in 0–1**.

They are the same number, converted once at the display boundary
(`toConfidenceOutOf10()` in `components/SeverityTag.tsx`). Storage has to remain a
probability for two reasons: §8.5 defines confidence as *the chance a human upholds this
decision*, and a probability is the only form you can check against an actual outcome
rate; and the backend's thresholds — `AUTO_APPROVE_CONFIDENCE = 0.85`,
`CONFIDENCE_HUMAN_FLOOR = 0.70` — are expressed on that scale. A reader, meanwhile, takes
`7.2 / 10` faster than `0.72`.

Same rule as P1–P4 versus Jira's Priority names in §3: one canonical internal form, one
readable form, translated in exactly one place.

| Shown | Stored | Means |
|---|---|---|
| `8.5 – 10` | `0.85 – 1.00` | inside the auto-approve band (with P3/P4 only) |
| `7.0 – 8.5` | `0.70 – 0.85` | moderate — routed normally |
| `< 7.0` | `< 0.70` | below the human floor — goes to a manager |

### 8.3 What it is now

**Confidence is the weakest gate, not the average of the gates.**

| Gate | Definition | The doubt it captures |
|---|---|---|
| `evidence_coverage` | evidenced metrics ÷ applicable metrics | how much was read versus assumed |
| `band_margin` | normalised distance to the nearest matrix boundary | how close this was to a different answer |
| `precedent_agreement` | share of retrieved resolved precedents in the same band | whether this shape has been seen and settled before |

```
confidence = min(gates that apply)
```

`precedent_agreement` is **omitted when no precedent was retrieved** — the same rule as a
`not_stated` metric. Scoring "no precedent found" as zero would collapse confidence on
every genuinely novel incident, which is precisely when a confident-but-wrong answer is
least likely and a *low* score is least informative.

Why `min`:

- **There are no weights to defend.** The entire "where did 0.45 come from" objection
  disappears, because nothing is weighted.
- **It is already this system's stated principle.** `ai/agents.py::_combined_confidence()`
  takes `min` across classify / assess / route with the comment *"a decision chain is only
  as confident as its weakest link."* Confidence over the gates now obeys the same rule
  the chain does — one idea, applied consistently, instead of two rules that disagree.
- **It behaves correctly at the boundary.** A coin flip stays a coin flip no matter how
  clean the rest of the evidence looks.

### 8.4 The number is never shown alone

A bare `0.34` is not an explanation. Every decision records **which gate bound it**, and
that is what the UI renders:

> **Confidence 0.34** — limited by evidence coverage: 6 of 15 applicable metrics were not
> stated in the ticket.

> **Confidence 0.08** — limited by band margin: Impact 49.4 sits against the
> Moderate/Significant boundary at 50. P2 and P3 are both defensible.

The second example is the honest output. It does not say "P3 with 8% confidence" and stop;
it says *which* two answers were in play and *why* it could not separate them. That turns
a number into a question a human can actually settle.

### 8.5 Hard floors — the number is not the only control

Confidence feeds the gate, but two conditions force human review on their own, whatever
the composite says:

| Condition | Why |
|---|---|
| `band_margin < 0.10` | a coin flip between two bands is a human's decision, not a model's |
| `evidence_coverage < 0.60` | more than 40% of the rubric was assumed rather than read |

Plus the existing rules from §7 and the graph: any P1, any fired escalator, any guardrail
hit, and any **downgrade** of a human-reported priority (§9).

### 8.6 Calibration — the part that makes it a claim rather than a vibe

Decomposition explains the number. It does not prove the number is *right*. Confidence
should mean something testable:

> **the probability this decision survives human review.**

That is measurable with data this system already stores. `tickets.overridden_by` records
every human correction, and the held-out set carries gold labels. So bucket decisions by
predicted confidence and plot the actual agreement rate per bucket:

| Predicted confidence | Decisions | Actually upheld | Calibrated? |
|---|---|---|---|
| 0.9 – 1.0 | *n* | *x*% | should be ≈ 95% |
| 0.7 – 0.9 | *n* | *x*% | should be ≈ 80% |
| 0.5 – 0.7 | *n* | *x*% | should be ≈ 60% |
| < 0.5 | *n* | *x*% | should be low — and these should all have reached a human |

If the 0.9 bucket is only 60% upheld, the confidence score is lying, and the table says so
in public. Surfaced on the Evals page next to the confusion matrix, computed by
`observability/evals.py` from `tickets` + `triage_runs`.

This is the strongest available answer to *"how do you know your confidence means
anything?"* — not "we decomposed it", but **"we measured it against what humans actually
did, and here is the curve."** A gap that is measured and shown beats a claim of accuracy
every time.

---

## 9. Reclassification of an incorrect reported priority

The reporter's priority is **an input signal, never the answer.** It is already captured
(`raw["priority"]` from the Jira Priority field) and is deliberately **excluded from
scoring** — feeding it into the metrics would anchor the model to the very judgement we
are auditing, and the system would agree with the reporter by construction.

The comparison happens after the band is computed:

```
reported_band  = priority_group⁻¹(raw["priority"])     # Highest→P1, High→P2, …
computed_band  = matrix(Impact, Urgency) ∘ overrides
reclassified   = reported_band ≠ computed_band
delta          = reported_band − computed_band          # +ve = we lowered it
```

### 9.1 The escalation / de-escalation asymmetry

Reclassification is **not symmetric**, because the two errors do not cost the same.

| Direction | Example | Treatment |
|---|---|---|
| **Upgrade** (P2 → P1) | payments Lambda timing out at 7.4% | **applies automatically**, audited, on-call notified. Under-escalating is the costlier error. |
| **Downgrade** (P1 → P2) | "P1" that is an intermittent 5xx with a workaround | **requires human approval.** `needs_human = true`, never auto-synced to Jira. |

An AI that silently downgrades a human's P1 is the single fastest way to lose the trust of
an on-call team, and once lost the system gets ignored. So the asymmetry is a product
decision, not a technical limitation: **the machine may raise an alarm on its own; only a
human may lower one.** Both paths write the full metric table and the rule ids to the
audit log.

Downgrades surface in the manager approval queue as a diff — reported band, computed band,
the metrics that drove the difference, and the evidence quoted for each. Approving it
writes the new Priority back to Jira with the rationale as a comment; rejecting it keeps
the reporter's band and records the disagreement as a `feedback` row, which feeds the
accuracy eval.

---

## 10. Worked examples — real tickets from the board

### 10.1 `SCRUM-14` — escalation, applied automatically

*"P2 AWS Lambda timeout spike in payment workflow"* · reported **High (P2)**

| Metric | Rating | Evidence |
|---|---|---|
| I2 business criticality | 4 | "payment workflow", "downstream payment callbacks delayed" |
| I3 financial exposure | 3 | payment completions failing at 7.4% |
| I4 availability shape | 2 | elevated failure, not total outage |
| U1 burn rate | 4 | `timeout_rate=0.074 threshold=0.01` — 7× over |
| U2 trend | 3 | "retry volume increased significantly" |
| U3 workaround | 3 | retries only partially recovering |

Impact ≈ **Significant** · Urgency ≈ **Critical** → matrix cell → **P1**.
Reported P2, computed P1 → **upgrade, applied automatically.** Payments on the revenue
path with a 7× SLO breach is not a P2.

### 10.2 `SCRUM-3` — downgrade, held for approval

*"P1 Production Incident: API Gateway returning 504"* · reported **Highest (P1)**

| Metric | Rating | Evidence |
|---|---|---|
| I1 blast radius | `not_stated` | no user or tenant count given |
| I4 availability shape | 2 | "intermittently returning HTTP 5xx", not a full outage |
| I5 data loss | 0 | none reported |
| I6 security | 0 | none reported |
| U2 trend | `not_stated` | status is "Investigating"; no direction given |
| U3 workaround | `not_stated` | not mentioned |

Impact ≈ **Moderate** · Urgency ≈ **Medium** → **P3**, and `evidence_coverage ≈ 0.5`
drags confidence down hard.

Computed P3 vs reported P1 is a **two-band downgrade on thin evidence** — precisely the
case that must not be automatic. Result: `needs_human = true`, escalation reason
*"two-band downgrade with evidence coverage 0.5 — six metrics not stated."* The drawer
shows the manager exactly which six facts are missing, which turns triage into a
question the reporter can answer rather than an argument about a number.

This is the demo beat: the honest output is not "P3", it is **"probably not a P1, and
here are the six things nobody wrote down."**

### 10.3 `SCRUM-12` — override rule fires

*"P2 Azure Key Vault authentication failures after secret rotation"*

Matrix alone gives ≈ **P2** (12% request failure, workaround unclear). But `I6 = 4` —
`authorization_failed principal=app-prod identity=managed`, an unauthorised-access
condition against a secret store — fires **`E2` → P1**, recorded as
`overrides_fired: ["E2"]`.

Without an override rule, weighted averaging would have buried a credential-boundary
failure in the middle of the queue.

---

## 11. Governance

- **Versioned.** `RULEBOOK_VERSION = 1.0.0`; the file's SHA-256 is stamped on every
  `triage_runs` row. "Which rules produced this decision?" is answerable a month later,
  which matters the moment the rulebook changes and past decisions look inconsistent.
- **Change control.** Weight or threshold changes require re-running the held-out
  labelled set (`POST /api/evals/run-triage`) and recording before/after accuracy. A
  rubric change that improves nothing measurable is reverted.
- **Not self-modifying.** No agent edits this file. It is human-authored policy; the
  system's job is to apply it consistently and to surface where it fits badly.
- **Bias surface.** Per-team and per-customer-tier band distributions are reported in the
  evals bias check. If the rubric systematically over-severities one team's tickets, that
  shows up as a number rather than as a complaint.

---

## 12. What this rulebook deliberately does not do

- **It does not make the model more confident.** It makes the model's uncertainty
  legible. A ticket with six unstated metrics should score low-confidence and reach a
  human — that is the system working.
- **It does not replace judgement.** The matrix decides the default; overrides encode the
  cases the matrix handles badly; the human gate covers the rest.
- **It does not chase precision.** 0–4 ratings and 1/2/3 weights are intentionally coarse.
  Anything finer is a decimal place pretending to be knowledge.
- **It does not auto-resolve or auto-remediate anything.** Nothing in this file grants an
  action. It ranks work; humans and runbooks do it.
