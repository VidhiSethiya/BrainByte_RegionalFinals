# TicketSphere — Build Plans

**24-hour build, three people, three coordinated backend plans.**

---

## The plans

| Plan | Owner | Responsibility | Hours | Start with |
|---|---|---|---|---|
| [**rag.md**](rag.md) | Shashank (Cursor) | RAG layer, vector DB, SQLite schema, chunking, embeddings, retrieval | ~9 | Read "Contract signatures" first |
| [**chatbot.md**](chatbot.md) | Priyal | Conversation management, session state, memory, context assembly, KB Q&A | ~6 | Read "Contract signatures" first |
| [**llm.md**](llm.md) | Vidhi & Naman | Triage agent (10 nodes), tools, Jira sync, guardrails, all API endpoints | ~10 | Read "Contract signatures" first |
| [**BLUEPRINT.md**](BLUEPRINT.md) | For context | The full system architecture, domain model, demo script, risks | — | Read if you need the big picture |
| [**INTEGRATION.md**](INTEGRATION.md) | **Read this first** | File ownership matrix, interface contracts, merge conflict prevention, sync protocol | — | **Start here to understand coordination** |

---

## How to use these

### Day 0 (before coding starts)

1. **All three:** Read [INTEGRATION.md](INTEGRATION.md) once top to bottom
2. **Each person:** Read your assigned plan's "Contract signatures" section
3. **Coordinate:** Post in Slack that you've read INTEGRATION.md; agree on standup time & Jira update frequency

### During the build

Each plan has:
- **Phases** — numbered, with "done when" criteria
- **File ownership** — what you edit, what you read-only-import
- **Contract signatures** — the APIs you depend on or provide
- **Integration tests** — when to test against other layers
- **Definition of done** — your exit criteria per phase

### Sync points

- **Phase 0 end** (1h) — Shashank posts "models.py and chunk_config live"; Vidhi/Naman posts "prompts.py frozen"; Priyal ready to start Ph1
- **Phase 1 end** (5h) — Shashank has retrieve() signature; Priyal has session model; Vidhi/Naman have 7 nodes (normalize → route)
- **Phase 2 end** (11h) — Shashank ships hybrid retrieval; Priyal has memory; Vidhi/Naman have tools and Jira
- **Phase 3 end** (15h) — Shashank runs eval set; Priyal does integration test with Shashank; Vidhi/Naman tune guardrails
- **Phase 4 end** (18h) — All three layers online, cold-start demo runs

**Every day at standup:** Post in Slack what shipped, what blocks you, who to unblock you.

---

## Key principles

**1. No merge conflicts.** Every file is edited by exactly one person. Read-only imports are OK.

**2. Interfaces are frozen.** Once Shashank publishes `retrieve()`, the signature does not
change. Vidhi/Naman depend on it; if you need new output, add a field to the return type,
don't rewrite the call.

**3. Backward compatibility on signature changes.** If you must add a parameter,
make it optional with a sensible default: `optional_param: int | None = None`.

**4. Jira board is the source of truth.** Story completions are the contract, not Slack.

**5. The demo works, or nothing works.** Cold-start (reset both DBs, re-seed, run the demo
script from BLUEPRINT.md §13) is the single success criterion. If the demo runs, you shipped.

---

## Who depends on whom

```
Vidhi/Naman ←calls── Priyal ←calls── Shashank
    ↓                                    ↓
   /api/*                        retrieve() +
   tools.py                       ACL filtering
   agents.py
```

- **Shashank Phase 0 & 1 must ship first** — Vidhi/Naman and Priyal both depend on retrieve()
- **Priyal Phase 1 must ship before Vidhi/Naman wire /chat** — they call handle_message()
- **Vidhi/Naman wire the routes** — all `/api/*` routes land in their code

---

## Jira board structure

Each person has a parent story with five child stories (one per phase):

**Shashank's epic:** RAG & Data Layer
- [SCRUM-xxx-1] Phase 0: Schema & Setup
- [SCRUM-xxx-2] Phase 1: Ingest & Anonymisation
- [SCRUM-xxx-3] Phase 2: Hybrid Retrieval
- [SCRUM-xxx-4] Phase 3: ACL & Validation
- [SCRUM-xxx-5] Phase 4: Integration & Eval

**Priyal's epic:** Chatbot & Memory
- [SCRUM-xxx-1] Phase 1: Session Management
- [SCRUM-xxx-2] Phase 2: Memory & Summarisation
- [SCRUM-xxx-3] Phase 3: Context Assembly
- [SCRUM-xxx-4] Phase 4: Entry Point & Integration

**Vidhi & Naman's epic:** LLM, Agents & Jira
- [SCRUM-xxx-1] Phase 0: Prompts & Setup
- [SCRUM-xxx-2] Phase 1: Triage Graph
- [SCRUM-xxx-3] Phase 2: Tools & Jira
- [SCRUM-xxx-4] Phase 3: Guardrails
- [SCRUM-xxx-5] Phase 4: API & Integration

---

## Total budget: 20 hours (verified)

| Person | Hours | Phases | Overlap? |
|---|---|---|---|
| Shashank | 9 | Ph0–4 | No — RAG only |
| Priyal | 6 | Ph1–4 | Ph1–4; parallel with Shashank's Ph2–4 |
| Vidhi & Naman | 10 | Ph0–4 | Ph0–4; parallel with Shashank's Ph1–4 and Priyal's Ph2–4 |
| **Buffer** | **4–5** | Ph5 | Demo rehearsal, dry run, fix whatever broke first time |
| **Unused** | — | — | If everything lands on time, use this to polish or optimize |

Actual parallel work is Ph1–4, so real elapsed time is ~10 hours, not 20. The 20-hour budget
is for a single person doing all of it sequentially; three people means ~7-hour sprint.

---

## Troubleshooting

**"I'm blocked waiting for [other person]"**
- Check INTEGRATION.md § Phase synchronisation — is their phase actually supposed to be done?
- If yes, @ them in Slack immediately with the phase number
- If no, start a different phase that doesn't depend on them

**"The interface changed and my code broke"**
- This is a coordination failure. Post in Slack ASAP.
- Violators of "signatures are frozen" must fix it same day
- Add a note to the phase "done when" list: "No signature changes after published"

**"I think I found a bug in the other person's code"**
- Create a Jira task, link it to their phase story
- Post in Slack with the task number
- Do NOT work around it in your own code — let them fix it
- (Exception: if it's blocking you for >30min, ask in standup for a quick fix)

**"Phase 4 integration tests are failing"**
- Check the "Definition of done" checklist in your plan — you probably skipped a step
- Run the integration test from your plan, not the full demo yet
- If the integration test passes but the demo fails, it's likely Vidhi/Naman's wiring issue

---

## Example day

**8am:** Standup. Shashank says "Ph0 done, retrieve() is callable"; Priyal says "ready for Ph1"; Vidhi/Naman say "Ph0 done, starting Ph1".

**8:30am–10:30am:** Shashank works Ph1 (chunker + anonymizer). Priyal works Ph1 (sessions). Vidhi/Naman work Ph1 (nodes 1–7).

**10:30am:** Shashank pings Vidhi/Naman: "Try calling retrieve() now, it's not crashed."

**2pm:** Priyal pings Vidhi/Naman: "handle_message() is in; you can wire /chat now."

**4pm:** Standup. Shashank says "Ph1 done"; Priyal says "Ph2 starting"; Vidhi/Naman say "Ph2 starting".

**6pm:** Everything is integrated and the demo runs once.

---

## Links

- [BLUEPRINT.md](BLUEPRINT.md) — domain model, agent design, model choices, full roadmap
- [rag.md](rag.md) — Shashank's plan
- [chatbot.md](chatbot.md) — Priyal's plan
- [llm.md](llm.md) — Vidhi & Naman's plan
- [INTEGRATION.md](INTEGRATION.md) — **Start here**

---

## Questions?

Ask in #brainbytes-backend on Slack, or create a Jira task.
