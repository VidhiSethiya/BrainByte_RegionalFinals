# Enhancement catalogue

Source material for Phase 1 of `guide-me`. **Select and adapt — never dump this list.**
Six to nine options, chosen because they fit *this* problem statement, beats twenty
generic ones.

Effort assumes the scaffold already exists. `S` <1h, `M` 1–3h, `L` 3–6h.

---

## A. Domain capability

Options that make the build read as a product rather than a demo.

| Option | What | Effort | Touches |
|---|---|---|---|
| **Action/tool layer** | 3–4 real tools the agent plans over — query, draft, notify, ticket — with a verify step after each call. Optionally exposed over MCP. | L | `ai/agents.py`, new `ai/tools.py` |
| **Structured artifact generation** | The system outputs a typed domain document (report, summary, assessment) with citations, downloadable as PDF/DOCX, not just chat text. | M | `rag/schemas.py`, `api.py`, new page |
| **Comparison / diff mode** | Answer across two documents or two time points — "what changed between these versions". Very strong in legal, policy, compliance. | M | `ai/agents.py` node, `rag_retriever.py` |
| **Batch / triage queue** | Process a folder of records and rank them by a domain score, so the demo shows throughput not one query. | M | `api.py`, new page |
| **Approval workflow** | Draft → human review → approve/reject → audit. Turns HITL from a feature into a story. | M | `db.py`, `api.py`, new page |
| **Structured extraction** | Pull a fixed schema out of unstructured documents with per-field confidence and provenance. | M | `rag/schemas.py`, `ai/prompts.py` |

---

## B. Retrieval and AI depth

Pick based on where *this corpus* will actually break.

**Always propose this one first**, because it is already built and costs an env change:

| Option | What | Effort | When it matters |
|---|---|---|---|
| **Switch to hybrid retrieval** | `RETRIEVAL_MODE=hybrid` turns on BM25 + RRF fusion alongside vector search. The code exists; the work is running the eval set both ways and keeping the winner. Recommend it **only** if the corpus carries exact identifiers (contract/policy/part/error codes) — say so explicitly either way, with the reason. | S | Identifier-heavy corpora; pointless on pure prose |
| **Enable the cross-encoder reranker** | `RERANK_ENABLED=true`. Best accuracy gain per line of code, but pulls torch (~2GB) — check the machine first. | S | Long candidate lists, ordering matters |
| **Metadata-aware query routing** | Parse filters out of the question ("2024 policies only") into the Chroma `where` clause. | M | Corpus has strong temporal/categorical structure |
| **Parent-document retrieval** | Retrieve small chunks for precision, expand to the parent section for context before generation. | M | Long structured documents where a chunk lacks context |
| **Table-aware extraction** | Extract tables from PDFs as structured text so numeric questions work at all. | M | Financial, clinical, or reporting corpora |
| **Graph index over entities** | Extract entities and relations, retrieve over the graph for multi-hop questions. | L | "Which suppliers are affected by X?" style questions |
| **Query classification → strategy** | Route factual / comparative / aggregate questions to different retrieval strategies. | M | Genuinely mixed query workload |
| **Semantic caching** | Cache answers by query embedding similarity. Cuts demo latency dramatically on repeats. | S | Always worth it if latency is the demo risk |
| **Self-consistency for critical answers** | Generate 3 answers, keep only claims that agree. Expensive; reserve for high-stakes paths. | M | Clinical or financial decisions |
| **Confidence-banded answers** | Map groundedness to an explicit HIGH/MEDIUM/LOW band shown in the UI. | S | Any regulated domain — cheap and visible |

---

## C. Governance and trust

Weight these by how regulated the domain is.

| Option | What | Effort |
|---|---|---|
| **Consent / purpose-of-use gating** | Every query declares a purpose; retrieval scope changes with it and the purpose is audited. Strong in healthcare. | M |
| **Right-to-erasure flow** | Delete a subject's data from both stores and prove it via the audit chain. Directly GDPR/DPDP. | M |
| **Reversible de-identification** | Re-identify masked tokens for authorised roles only, fully audited. | M |
| **Policy-as-config** | Move the policy rules out of the prompt into a rules file the compliance team could edit. | M |
| **Red-team panel** | A UI tab firing a fixed set of injection/PII/jailbreak probes and showing what got blocked. Live proof, not claims. | M |
| **Model card / decision provenance** | Per answer: model, prompt version, chunks used, guardrails fired, thresholds applied — exportable. | S |
| **Bias / fairness spot check** | Run the eval set across demographic variants and compare. Matters in hiring, lending, clinical triage. | M |

---

## D. Demo impact

Cheap, visible, disproportionately effective.

| Option | What | Effort |
|---|---|---|
| **Retrieval-visibility panel** | Show the per-chunk scores for a live query. `/api/search` already returns `vector_rank`, `keyword_rank` and `rerank_score`. | S |
| **Retrieval mode A/B** | Run the eval set under `vector` and `hybrid`, show both score sets, and state which was shipped and why. Turns "we chose vector search" from a limitation into a measured decision — the single strongest retrieval answer available to this build. | S |
| **Guardrail theatre** | A deliberately unanswerable and a deliberately injected question in the demo script, so refusal is shown not asserted. | S |
| **Live cost/latency ticker** | Per-answer tokens, latency and cost in the header. Reads as production-mindedness. | S |
| **Citation click-through** | Click a citation, see the source chunk highlighted with its page. Makes verifiability tangible. | M |
| **Cold-start seed script** | One command rebuilds the whole demo state. Insurance against a broken laptop. | S |
| **Offline banner** | Explicit "running fully local, no data leaves this machine" indicator. Lands hard in regulated domains. | S |

---

## Domain quick-reference

Starting points only — the problem statement overrides these.

**Healthcare** — HIPAA framing; PHI beyond names (MRN, dates of service, device IDs);
clinician vs administrator roles; must refuse to give clinical advice; provenance to the
source document is non-negotiable; purpose-of-use gating is the standout add-on.

**Banking / financial services** — exact-identifier retrieval is critical (account,
policy, transaction IDs) so BM25 earns its place; numeric accuracy matters more than
fluency, so table extraction is high value; audit trail and four-eyes approval are
expected, not impressive.

**Legal / contracts** — clause-level chunking with structural separators; comparison/diff
mode is the killer feature; citations must reach clause level; hallucinated case or
clause references are the catastrophic failure to guard against.

**Insurance** — claims triage as a batch queue demos throughput; structured extraction
with confidence; policy-vs-claim comparison; fraud signals need explainability.

**Manufacturing / operations** — multimodal matters most here (diagrams, schematics,
scanned manuals); exact part numbers demand keyword search; time-series or telemetry
context may need its own retrieval path.

**HR / internal ops** — access control is the whole story (who can see whose record);
bias checking is expected; PII masking must be visibly demonstrated.

**Public sector / compliance** — auditability and right-to-erasure dominate; offline
operation is often a hard requirement, which the local-Ollama default already satisfies.

---

## Traps in a timed build

Say so plainly when one of these is proposed:

- **Fine-tuning anything** — hours of GPU time for something retrieval already solves,
  and it makes deletion unimplementable.
- **A new vector database** — migration cost with no demo-visible benefit.
- **Streaming responses** — pleasant, but it complicates the guardrail path, which must
  see the complete answer before releasing any of it.
- **Real-time collaboration / websockets** — high effort, near-zero judging weight.
- **Auth beyond JWT** — OAuth, SSO and RBAC UIs consume hours judges never see.
- **Docker/Kubernetes deployment** — unless deployment is explicitly judged.
- **A second frontend framework or design system** — the AntD scaffold is already there.
- **Voice input** — demos badly in a noisy hall.
