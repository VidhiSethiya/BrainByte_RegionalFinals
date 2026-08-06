# [PRODUCT_NAME] — Implementation Blueprint

> Fill every placeholder. Delete any you cannot fill, along with its heading if the
> section ends up empty. A finished blueprint contains no bracketed tokens.

**Domain:** [DOMAIN]
**Generated:** [DATE]
**Budget:** 20 coding hours
**Selected options:** [SELECTED_OPTION_LIST]

---

## 1. Problem

**Statement.** [PROBLEM_STATEMENT — verbatim or tightly summarised]

**Who uses it.** [PRIMARY_USER] — [WHAT_DECISION_THEY_MAKE]

**Job to be done.** [ONE_SENTENCE_CORE_JOB]

**Cost of a wrong answer.** [CONSEQUENCE — drives guardrail strictness]

**Regulatory frame.** [REGULATION_OR_STANDARD, or "none stated"]

**Success looks like.** [DEMO_MOMENT — the single thing that must work on stage]

---

## 2. Data

| Aspect | Detail |
|---|---|
| Sources | [DOCUMENT_TYPES] |
| Modalities | [TEXT / PDF / IMAGE — and which dominate] |
| Volume | [APPROX_COUNT_AND_SIZE] |
| Sensitive fields | [PII_FIELDS_PRESENT] |
| Exact identifiers | [IDS_THAT_MUST_MATCH_LITERALLY — drives BM25 value] |
| Structure | [SECTIONS/CLAUSES/TABLES — drives chunker separators] |
| Access model | [WHO_MAY_SEE_WHAT] |

**Seed corpus plan.** [WHERE_THE_DEMO_DATA_COMES_FROM — real, synthetic, or generated]

---

## 3. Domain model

Replace the placeholder entities in `backend/rag/schemas.py`:

| Scaffold name | Becomes | Fields |
|---|---|---|
| `AnonymizedRecord` | [DOMAIN_INPUT_ENTITY] | [FIELDS] |
| `GeneratedReport` | [DOMAIN_OUTPUT_ENTITY] | [FIELDS] |

**Roles and sensitivity.**

| Role | May read up to | Notes |
|---|---|---|
| [ROLE_1] | [SENSITIVITY] | [WHO_THIS_IS] |
| [ROLE_2] | [SENSITIVITY] | [WHO_THIS_IS] |
| [ROLE_3] | [SENSITIVITY] | [WHO_THIS_IS] |

**Document attributes** (become Chroma metadata, filterable at query time):
[ATTRIBUTE_LIST]

---

## 4. What we are building on top of the scaffold

For each pipeline step: what the problem statement demands and what changes.

| Step | Need | Status | Work |
|---|---|---|---|
| Ingest | [NEED] | [covered / fill / new] | [WHAT] |
| Index | [NEED] | [covered / fill / new] | [WHAT] |
| Retrieval | [NEED] | [covered / fill / new] | [WHAT] |
| AI layer | [NEED] | [covered / fill / new] | [WHAT] |
| Guardrails | [NEED] | [covered / fill / new] | [WHAT] |
| Governance | [NEED] | [covered / fill / new] | [WHAT] |
| Frontend | [NEED] | [covered / fill / new] | [WHAT] |

---

## 5. Selected enhancements

Only what the user picked.

### [OPTION_NAME]
- **What:** [ONE_SENTENCE]
- **Why it wins here:** [DOMAIN_SPECIFIC_JUSTIFICATION]
- **Files:** [FILE_LIST]
- **Effort:** [S/M/L] — [HOURS]
- **Done when:** [OBSERVABLE_CHECK]

[Repeat per selected option. Delete this whole section if nothing was selected.]

---

## 6. Roadmap

Sequential. Do not start a phase before the previous one demos.

### Phase 0 — Boot (0–1h)
| # | Task | Files | Done when |
|---|---|---|---|
| 0.1 | [TASK] | [FILES] | [CHECK] |

### Phase 1 — Vertical slice (1–5h)
> One real question answered correctly, with citations, end to end.

| # | Task | Files | Done when |
|---|---|---|---|
| 1.1 | [TASK] | [FILES] | [CHECK] |

### Phase 2 — Depth (5–11h)
| # | Task | Files | Done when |
|---|---|---|---|
| 2.1 | [TASK] | [FILES] | [CHECK] |

### Phase 3 — Governance & safety (11–15h)
| # | Task | Files | Done when |
|---|---|---|---|
| 3.1 | [TASK] | [FILES] | [CHECK] |

### Phase 4 — Surface & polish (15–18h)
| # | Task | Files | Done when |
|---|---|---|---|
| 4.1 | [TASK] | [FILES] | [CHECK] |

### Phase 5 — Dry run & buffer (18–20h)
| # | Task | Files | Done when |
|---|---|---|---|
| 5.1 | Run the eval set, paste real numbers into `docs/JUDGES_QA.md` | docs/ | No `[PLACEHOLDER]` left in the Q&A |
| 5.2 | Full demo rehearsal against a cold start | — | Runs twice without intervention |

**Total estimated:** [HOURS] of 20.

---

## 7. Mandatory safety checklist

Scaffolded, but placeholder-filled. Each needs a domain-specific pass.

| Item | File | What to fill | Phase |
|---|---|---|---|
| PII patterns | `guardrails/pii.py` | [DOMAIN_IDENTIFIERS] | [N] |
| Policy rules | `ai/prompts.py` | [DOMAIN_POLICIES] | [N] |
| Injection patterns | `guardrails/input_guard.py` | [DOMAIN_ATTACK_SHAPES] | [N] |
| Groundedness thresholds | `guardrails/output_guard.py` | [FLOOR / REFUSE values + rationale] | [N] |
| Response validation | `guardrails/validators.py` | [BANNED_PHRASINGS] | [N] |
| Sensitivity matrix | `governance/access_control.py` | [ROLE→CEILING] | [N] |
| Eval set | `observability/evals.py` | [8–12 questions, ≥2 refusals] | [N] |
| Chunk separators | `rag/chunker.py` | [STRUCTURAL_MARKERS] | [N] |

---

## 8. Demo script

Three minutes. Each beat names the screen and the thing being proved.

| # | Beat | Screen | Proves |
|---|---|---|---|
| 1 | [ACTION] | [PAGE] | [POINT] |
| 2 | [ACTION] | [PAGE] | [POINT] |
| 3 | [ACTION] | [PAGE] | [POINT] |
| 4 | [ACTION] | [PAGE] | [POINT] |
| 5 | [ACTION] | [PAGE] | [POINT] |

**The refusal beat.** [WHICH_QUESTION_GETS_BLOCKED_AND_WHY — show the system declining;
it lands harder than another correct answer.]

**Fallback if the model is slow on stage.** [PRE-WARMED_SESSION / CACHED_RUN / SCREENSHOT]

---

## 9. Risks

| Risk | Likelihood | Mitigation | Trigger to abandon |
|---|---|---|---|
| [RISK] | [H/M/L] | [MITIGATION] | [WHEN_TO_CUT] |

---

## 10. Explicitly not doing

Naming the cuts is what keeps the build inside 20 hours.

- [CUT] — [WHY]
- [CUT] — [WHY]
