# Judges' Technical Q&A

Answer prep. Every question below is one a technical judge realistically asks, with the
justification and — where it matters — the honest limitation. Admitting a known
trade-off scores better than defending a weak claim.

Update this as implementation lands. Anything in [BRACKETS] must be filled with real
measured numbers before the demo.

---

## Model choices

**Q: Why `llama-3.2-3b-it` and not a larger model?**
The bottleneck in this system is retrieval quality, not generation capacity. Once the
right six chunks are in context, a 3B instruction-tuned model synthesises them
reliably. Spending the compute budget on a cross-encoder reranker instead of a bigger
generator gave a better answer for the same latency. The model is one env variable —
`LLM_MODEL` — so a larger model is a config change, not a code change.

**Q: Why run locally on Ollama instead of a hosted API?**
Three reasons, in order of weight. **Data residency** — this domain's documents cannot
leave the customer's boundary, and a local runtime removes the question entirely.
**Determinism during a timed build** — no rate limits, no key expiry, no network.
**Cost** — inference is free, which is what makes running a full eval set on demand
practical. `ai/llm.py` probes a hosted endpoint at boot and falls back to local, so both
paths are live.

**Q: Why `gte-large` for embeddings?**
It is a strong open retrieval-tuned encoder at 1024 dimensions — good quality per unit
of index size, and it runs locally alongside the generator. Retrieval-tuned matters:
a general-purpose sentence encoder is optimised for similarity, not for
query-to-passage asymmetry.

**Q: Why not fine-tune?**
Fine-tuning teaches style and format, not facts — and the facts here change whenever a
document is added. Retrieval is the correct mechanism for knowledge that must be
current, attributable and revocable. Fine-tuning would also make the "delete this
document" requirement unimplementable.

**Q: Why LangChain's OpenAI client rather than the Ollama SDK?**
One wire protocol for both local and hosted. Switching providers is an env change with
no code path divergence, so what we test locally is what runs hosted.

---

## Retrieval

**Q: Why hybrid search? Isn't vector search enough?**
Often, yes — and that is why we **ship on vector search by default**. On a corpus of
prose, dense retrieval alone answers most questions, has one failure mode, and costs
one index to maintain. Adding a second retriever because it sounds more advanced is how
teams spend hours on machinery they cannot justify.

Where vector search genuinely fails is **exact identifiers**. Embeddings compress
meaning, so "policy AC-4471" and "policy AC-4472" land in nearly the same place; ask for
one and you get semantically similar policies rather than the right one. BM25 matches
the literal token. Semantic recall and lexical precision fail on opposite queries.

So both are implemented and the choice is one env variable, `RETRIEVAL_MODE`. We ran
the eval set both ways on this corpus and kept the winner. [PLACEHOLDER: state the
measured groundedness / context-recall for vector vs hybrid, and which you shipped.]
That is the defensible answer: not "we used the advanced one", but "we measured, and
here is what this corpus needed".

**Q: So is hybrid dead code?**
No — it is one env variable away, and the `/api/search` response already returns
`vector_rank`, `keyword_rank` and `rerank_score` per chunk, so switching modes is
visible in the UI immediately. If the corpus grows identifier-heavy, the migration is a
config change and a re-run of the eval set.

**Q: Why RRF instead of weighting the two scores?**
Cosine similarity and BM25 scores are on incomparable scales, and BM25's range shifts
with corpus statistics — any fixed weighting needs retuning whenever documents change.
RRF uses only rank position (`score = Σ 1/(k+rank)`), so it needs no normalisation and
no per-corpus tuning. `k=60` is the standard published value.

**Q: What does the cross-encoder actually add?**
Bi-encoders embed query and chunk separately, so they never see them together. A
cross-encoder reads the pair jointly and is substantially more accurate at ordering —
but it is O(n) model passes, so it is only affordable on a shortlist. Retrieve ~40
candidates cheaply, rerank them, keep 6. It is off by default (`RERANK_ENABLED=false`)
because it pulls torch, roughly 2GB, for a gain we could not justify on this corpus
inside the time budget. If it is absent or fails to load, retrieval falls back to
fusion order and keeps working.

**Q: Why chunk at 900 characters with 150 overlap?**
Large enough to hold a complete clause or paragraph, small enough that six chunks fit a
modest context window. The overlap prevents a fact from being split across a boundary
and lost by both chunks. Splitting is recursive on paragraph → line → sentence → word,
so boundaries land on natural breaks. [PLACEHOLDER: state the tuning you actually did
on the real corpus.]

**Q: Why only 6 chunks?**
More context is not better context. Beyond a point, added chunks are noise that dilutes
attention and lowers groundedness while raising latency and cost. Six was chosen against
the eval set; `FINAL_TOP_K` is configurable. [PLACEHOLDER: state the measured
groundedness at k=4, 6, 10.]

**Q: How do you handle a follow-up like "what about the second one?"**
The rolling conversation summary feeds a rewrite step that produces a standalone query
before retrieval runs. Without it, the retriever sees a pronoun and returns noise. This
is why the summary is retrieval infrastructure, not a chat nicety.

**Q: What happens when retrieval finds nothing relevant?**
The system says so and names what document would be needed. It does not fall back to
parametric knowledge. An ungrounded answer in this domain is worse than no answer.

---

## Vector database

**Q: Why Chroma and not pgvector / Pinecone / Weaviate?**
At this corpus size the differentiator is metadata filtering and zero operational
overhead, both of which Chroma gives locally with persistence. Pinecone adds a network
hop and a vendor dependency for data that must stay in-boundary. pgvector would be the
right answer at millions of vectors or if we needed transactional consistency between
documents and embeddings — `vector_store.py` is the only module that touches the store,
so that migration is one file.

**Q: How does the vector store scale?**
Chroma's HNSW index is fine into the low millions of chunks on one box. In hybrid mode
the BM25 index is in-process and rebuilt on corpus change, which would be the first
thing to replace at scale — Elasticsearch or OpenSearch for the keyword side. Both
limits are known and neither is on the critical path for this deployment size.

---

## Agent architecture

**Q: Why LangGraph rather than a linear chain?**
For one edge: `verify → retrieve`. When an answer fails the groundedness check, the
usual cause is a bad first query, not a bad generation — so the graph routes back to
retrieval once with a decomposed query rather than regenerating on the same context. A
linear chain cannot express that, and a while-loop hides the control flow. The graph is
also where domain-specialist nodes get added without touching the request path.

**Q: Is this really "agentic", or is it a RAG pipeline with extra steps?**
It plans (route selection), acts (retrieval, decomposition), verifies its own output,
and retries on failure. It does not yet take external actions — no writes to other
systems. [PLACEHOLDER: if the action/tool layer was added on build day, describe the
tools here: what they do, what verifies them, what a failed call does.]

**Q: Why cap the retry at one?**
Retries that do not change the input do not change the outcome. The one retry changes
the query strategy; a second would just burn latency. The eval set showed [PLACEHOLDER:
measured retry success rate].

---

## Guardrails and safety

**Q: Walk me through prompt-injection defence.**
Layered. High-precision regex signatures block known patterns at zero cost. Weak signals
escalate to an LLM classifier that only fires on suspicion, so the median request pays
no extra call. Retrieved content is placed in a clearly delimited context block and the
system prompt instructs the model to treat it as data. The strongest defence is
structural: the model has no tools and no write access, so a successful injection can
only affect one answer's text — which the output guardrail then screens.

**Q: How do you know the answer isn't hallucinated?**
An LLM judge scores every answer's claims against the exact context the generator saw.
Below 0.25 the answer is refused; between 0.25 and 0.5 it ships with a visible caveat.
Citations are page-level, so a human can verify in seconds. **The honest limitation:**
the judge is the same model family being judged, so it shares blind spots. It is a
regression signal and a floor, not a proof. A production deployment would use a
stronger judge model or spot-check human review — the human-in-the-loop review queue is
already built for exactly that.

**Q: Why both regex and LLM for PII?**
Different failure modes. Regex is exact, instant, and cannot hallucinate — right for
structured identifiers and right for the hot path. An LLM catches contextual
identifiers regex cannot express, like a person's name in free text — but it is slow
and probabilistic, so it runs only at ingest time where latency does not matter. Regex
alone misses names; LLM alone is unreliable on card numbers and too slow to run on
every request.

**Q: Masking loses information — doesn't that hurt retrieval?**
Tokens are typed and stable: the same person is `[PERSON_1]` throughout a document, so
relationships and structure survive. "[PERSON_1] approved [PERSON_2]'s claim twice"
remains fully answerable. The mapping is retained, so an authorised viewer could
re-identify — that path is deliberately not exposed in this build.

**Q: What if PII gets into an answer anyway?**
The output guardrail scans every generated answer independently of ingest and redacts
irreversibly. Defence in depth: ingest masking is the primary control, output scanning
is the backstop.

---

## Governance and access control

**Q: How is document-level access control enforced?**
As a filter passed **into** the vector query, not applied to its results. That
distinction is the whole design. Post-filtering means unauthorised text was already
retrieved and could already have been placed in the prompt, and it silently degrades
top-k for restricted users — ask for 6 chunks, get 2 after filtering. Filtering inside
Chroma means the user's top-6 is the top-6 of what they are allowed to see.

**Q: Roles are a list — how do you filter on that in a vector store?**
Chroma metadata values must be scalars, so a list column is not filterable. Each
permitted role is expanded to a flat boolean key (`acl_analyst: true`) at chunk time,
and the query builds an `$or` over the user's roles and clearances. Exact-match, fast,
and it composes with the sensitivity ceiling. `can_read()` re-checks after retrieval as
defence in depth — it should never fire, and if it does, the `where` clause and the
check have drifted.

**Q: What makes the audit log "immutable"? It's a SQL table.**
Each entry's hash covers its own content plus the previous entry's hash. Editing or
deleting any row invalidates every hash after it, and `/api/audit/verify` walks the
chain and names the first broken entry. It does not prevent tampering — nothing at the
application layer can — it makes tampering **detectable**, which is the actual audit
requirement. Production would append to write-once storage; the chain logic is
unchanged.

**Q: What is actually logged?**
Action, actor, resource, timestamp, and structured details — groundedness scores,
chunk counts, block reasons. Deliberately **not** raw PII: guardrail findings record the
*type* detected, never the value. An audit log that stores what it was built to protect
is a liability.

---

## Engineering

**Q: Why Flask rather than FastAPI?**
[PLACEHOLDER: this was a stack constraint — say so plainly if asked.] Validation is
Pydantic either way, so the contract is identical; what Flask costs us is automatic
OpenAPI generation and native async. Neither is on the critical path for this
deployment, and the LLM calls are I/O-bound work already handled by a bounded thread
pool with hard timeouts.

**Q: How do you stop a hung model from hanging a request?**
Every external call goes through `with_timeout`, which runs it in a bounded pool under a
wall-clock cap. Fan-out work — embedding batches, the parallel groundedness and policy
checks, multi-query retrieval — goes through `parallel_map`, which returns partial
results rather than failing the batch. No code path can block indefinitely on a model.

**Q: Where is the latency actually spent?**
Traces break every request into stages. [PLACEHOLDER: fill in the real p50/p95 split —
typically embed, vector search, BM25, rerank, generate, verify.] The parallel
groundedness/policy pair means the output guardrail costs one round-trip, not two.

**Q: You have no tests. Why should I trust this?**
The eval set is the test suite, and it tests the thing that actually breaks — retrieval
and generation quality — which unit tests cannot. It runs on demand from the UI and
persists results, so quality is a tracked metric rather than an assertion. Unit tests
for a 20-hour build would have covered the code least likely to fail.

**Q: What breaks first under load?**
The in-memory rate limiter, and the in-process BM25 index if hybrid mode is on — both
are single-process by design. The vector store and the SQL layer are unaffected.
Horizontal scale means moving the limiter to Redis and BM25 to a search service;
neither changes the pipeline.

**Q: Why is there no CORS configuration?**
Because there is no cross-origin request. Flask serves the built frontend and the API
from one host; in development Vite proxies `/api` to the same backend, so the browser
only ever sees one origin. Relaxing CORS headers is a workaround for an architecture
that split the tiers unnecessarily — we didn't split them.

**Q: You disabled TLS verification. Isn't that a security hole?**
In this deployment, no — the model runtime is `localhost`, plain http, with no network
hop to protect. The flag exists because TLS-inspecting corporate proxies break
certificate validation against hosted endpoints, and discovering that mid-demo costs
more than it protects here. It is a single env variable (`DISABLE_SSL_VERIFY`) applied
in one place, `ai/llm.py`, so a real deployment turns it off without touching code.

---

## Evaluation

**Q: What do your four metrics mean?**
`groundedness` — are the answer's claims supported by retrieved context (generation
quality). `context_precision` — what share of retrieved chunks were relevant (retrieval
noise). `context_recall` — did retrieval find what the answer needed (retrieval misses).
`hallucination` — reported separately as `1 − groundedness` because that is the number a
risk officer asks for. Precision and recall together localise a failure: bad answers with
high precision mean the generator is at fault; low recall means retrieval is.

**Q: Your judge is an LLM. How is that trustworthy?**
It is directionally reliable and comparably scored across runs, which makes it valid for
**regression** — did this change make retrieval better or worse. It is not an absolute
truth claim. The eval set is fixed, so run-to-run comparisons are apples to apples.

**Q: Current numbers?**
[PLACEHOLDER: fill in from the last eval run before demoing — groundedness, precision,
recall, hallucination rate, p95 latency. Do not present a dashboard of zeros.]

---

## Domain-specific

[PLACEHOLDER: DOMAIN_QUESTIONS — after the problem statement lands, add 5-8 questions a
domain expert would ask. Regulatory framing (HIPAA / GDPR / SOX / RBI), what the
system deliberately refuses to do, what a wrong answer costs in this domain, and who is
accountable for a decision the system informed.]
