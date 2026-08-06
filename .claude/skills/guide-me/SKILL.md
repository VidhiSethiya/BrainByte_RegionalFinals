---
name: guide-me
description: Analyzes a problem statement and generates a project blueprint. Use when the user supplies a hackathon or enterprise problem statement and wants domain-specific enhancement options followed by a phased implementation roadmap for this repo.
context: fork
---

# guide-me

Turn a problem statement into a build plan for **this** repo — a pre-built enterprise
multimodal RAG + agentic platform whose architecture is already fixed.

Run in two phases. **Phase 1 ends with a question to the user. Do not continue to
Phase 2 in the same turn.**

---

## Before either phase

Read, in this order:

1. `CLAUDE.md` — the fixed stack, layer boundaries, and golden rules
2. `docs/FLOW.md` — what already exists at each pipeline step
3. `.claude/skills/guide-me/references/template.md` — the blueprint structure you fill
4. `.claude/skills/guide-me/references/enhancements.md` — the add-on catalogue to draw from
5. `.claude/skills/guide-me/references/design-system.md` — the locked visual language

Then skim `backend/rag/schemas.py`, `backend/api.py` and `backend/ai/prompts.py` so
recommendations name real files and real placeholders.

**Never propose rebuilding what exists.** Retrieval (both vector and hybrid),
guardrails, ACL, audit log, evals, telemetry, chatbot memory and the multimodal loaders
are already scaffolded. Your job is to say what to *fill in* and what to *add* — not
what to replace.

**Retrieval mode ** Create a multi-agent Retrieval-Augmented Generation (RAG) application utilizing LangChain and LangGraph for stateful orchestration. The data retrieval layer must implement a hybrid search architecture, combining sparse keyword retrieval (BM25) with dense semantic search to ensure both precise term matching and conceptual understanding. Based on the specific problem statement, the system should dynamically route queries using either Corrective RAG (CRAG) to externally validate retrieved documents and trigger web-search fallbacks, or Self-RAG to utilize internal reflection tokens for self-correcting factual generation.

**The visual language is not up for discussion.** `references/design-system.md` is
locked: warm off-white ground, muted clay/teal/ochre accents, 4px geometry, Ant Design
theme tokens, light mode only. Do not propose a redesign, a different UI library, a dark
theme, or a colour change — those are not enhancements, they are scope. You may propose
*new screens or widgets*, which must then be specified in that language.

---

## Phase 1 — Analyse and propose

### 1. Extract the problem statement's shape

State back, in under 150 words:

- **Domain** and its regulatory regime (healthcare/HIPAA, banking/RBI-PCI, legal, etc.)
- **Primary user** and the decision they make with this system
- **Data**: what documents/records, what modalities, roughly what volume
- **Core job to be done** in one sentence
- **What a wrong answer costs** in this domain — this drives guardrail strictness

If the statement is ambiguous on any of these, say which and assume the most defensible
reading; do not stall.

### 2. Map to what exists

A short table: for each pipeline step in `docs/FLOW.md`, what the problem statement
needs there and whether the scaffold already covers it (`covered` / `fill placeholder` /
`needs new work`).

### 3. Propose enhancements — the core output

Draw from `references/enhancements.md`, but **select and adapt for this domain** — do
not dump the catalogue. Propose **6–9 options**, grouped:

- **A. Domain capability** — what makes this look like a real product in this industry
- **B. Retrieval / AI depth** — where this corpus specifically will break naive retrieval
- **C. Governance & trust** — what this domain's regulator would demand
- **D. Demo impact** — what wins the 3-minute pitch. Screens and widgets only; the
  visual language is already fixed, so "restyle it" is never an option here.

For each option give exactly:

| Field | Content |
|---|---|
| **What** | One sentence |
| **Why it wins here** | Tie to *this* domain and *this* judging panel — not generic |
| **Effort** | S (<1h) / M (1–3h) / L (3–6h) |
| **Touches** | The actual files it modifies |
| **Risk** | What could go wrong in a timed build |

Rank by **impact ÷ effort**. Mark your top 3 as `RECOMMENDED`. Flag anything that
would push past the 20-hour budget as `STRETCH`.

Be opinionated. If an option sounds impressive but is a trap in a timed build, say so
and say why.

### 4. Stop and ask

End Phase 1 with:

> **Which options should go into the blueprint?** Reply with the option letters/numbers.
> Everything not selected is dropped — I will not carry it into the plan.

**Produce no blueprint, write no files, and do not begin Phase 2 until the user answers.**

---

## Phase 2 — Generate the blueprint

Triggered only by the user's selection.

1. Copy `references/template.md` verbatim as your structure.
2. Fill **every** `[PLACEHOLDER: ...]` and `[BRACKETED]` token with real content from
   the problem statement and the selected options.
3. **Delete any placeholder you cannot fill**, along with its heading if the whole
   section is empty. A blueprint containing the word PLACEHOLDER has failed.
4. Include only the selected options. Do not smuggle rejected ones back in.
5. Write the result to `.claude/plans/BLUEPRINT.md`.

### Phasing rules

Order work so a demoable system exists as early as possible:

- **Phase 0 (0–1h)** — env, models pulled, seed corpus indexed, app boots end to end
- **Phase 1 (1–5h)** — the domain vertical slice: real schemas, real prompts, one
  question answered correctly with citations
- **Phase 2 (5–11h)** — selected retrieval/AI depth, domain workflows, the pages needed
- **Phase 3 (11–15h)** — governance, guardrail tuning, eval set populated with real cases
- **Phase 4 (15–18h)** — dashboard, polish, demo script
- **Phase 5 (18–20h)** — buffer, dry run, `docs/JUDGES_QA.md` numbers filled in

Every task must name its file(s) and a one-line "done when" check. Total estimates must
land under 20 hours with the buffer intact — if they don't, cut and say what you cut.

### Mandatory completion checklist

These are scaffolded but placeholder-filled. The blueprint **must** contain a task for
each, sized to the domain:

- [ ] **Domain PII patterns** → `guardrails/pii.py` `PATTERNS` (the identifiers this
      domain actually carries: MRN, NHS number, IBAN, policy number, employee ID…)
- [ ] **Domain policy rules** → `ai/prompts.py` `POLICY_CHECK_PROMPT` and
      `SYSTEM_PERSONA` compliance rule
- [ ] **Input guardrail tuning** → `guardrails/input_guard.py` domain injection patterns
- [ ] **Output thresholds** → `guardrails/output_guard.py` `GROUNDEDNESS_FLOOR` /
      `GROUNDEDNESS_REFUSE`, set by what a wrong answer costs
- [ ] **Response validation** → `guardrails/validators.py` banned phrasings
- [ ] **Real schemas** → `rag/schemas.py` — rename `AnonymizedRecord` /
      `GeneratedReport` to the domain's actual entities and give them real fields
- [ ] **Role & sensitivity model** → `governance/access_control.py` `MAX_SENSITIVITY`,
      `config.py` `ROLES`, `db.py` clearances
- [ ] **Eval set** → `observability/evals.py` `EVAL_SET` — 8–12 real questions including
      at least 2 that *should* be refused
- [ ] **Domain separators** → `rag/chunker.py` `_SEPARATORS` if documents are structured
- [ ] **Retrieval mode decided** → run the eval set under `RETRIEVAL_MODE=vector` and
      `=hybrid`, record both score sets in `docs/JUDGES_QA.md`, set the winner in `.env`
- [ ] **Design system applied** → the AntD theme object from `references/design-system.md`
      §7 into `frontend/src/main.tsx` (replacing the placeholder `#1668dc`), the CSS
      variables from §8 into `frontend/src/index.css`, then the §9 screen pass. Schedule
      this **early in Phase 2, not in polish** — retro-fitting a theme over screens built
      against AntD defaults costs more than doing it once up front.
- [ ] **Docs refreshed** → `docs/FLOW.md` and `docs/JUDGES_QA.md` domain sections,
      and `.cursor/plan.md` kept in sync for the Cursor teammate

Never mark one "skip to save time" — shallow beats absent for all of them.

---

## Output style

- Concrete over comprehensive. Name files, functions and constants.
- No restating what `CLAUDE.md` already says.
- No motivational filler, no "this will impress the judges" without a mechanism.
- Numbers where numbers exist; `[measure this]` where they don't.
