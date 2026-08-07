# TriageIQ — Frontend Specification

**Owner:** Trapti (sole frontend) · **Tooling:** Windsurf · **Window:** ~10 of the 24 hours
**Companion doc:** `../.claude/plans/BLUEPRINT.md` (whole system) — this file is the frontend contract
**Design language:** `../.claude/skills/guide-me/references/frontend-design.md` — **locked, not up for discussion**

This spec is written to be followed without reading the backend. Every API shape you need
is typed here. Where the backend does not exist yet, build against the mock layer in §7
and flip one flag when it lands.

---

## 1. Hard rules

Break any of these and the work gets reverted, not reviewed.

1. **Ant Design components only.** No Tailwind, no styled-components, no second UI kit,
   no custom CSS framework. `antd` + `@ant-design/icons` + `recharts` are the whole
   vocabulary.
2. **No hard-coded hex, radius, or font-family in any component file.** Colour comes from
   the AntD theme tokens or the CSS variables in §4.4. If you are typing `#` inside a
   `.tsx` file, you are doing it wrong — the two exceptions are the theme object in
   `main.tsx` and the Recharts `stroke`/`fill` props, which cannot read tokens (§4.6).
3. **All HTTP goes through `src/api/client.ts`.** No `fetch` in a component, ever.
4. **Server data → TanStack Query. UI state → Zustand.** Zustand holds filters, drawer
   open/closed, selected row. It never holds a ticket.
5. **Tables are AntD `<Table>` in server-side mode.** Never `dataSource={allRows}` with
   client-side pagination — the backend does paging, sorting, filtering and search, and
   the contract is in §6.3. Copy the pattern already in `src/pages/Documents.tsx`.
6. **Light mode only.** No dark theme. It doubles the surface for zero judging credit.
7. **Never remove a focus ring.** Judges tab through things.
8. **Numeric columns are right-aligned with `tabular-nums`.** Use `className="tabular"`
   (defined in §4.4). Proportional digits in a data table is the giveaway of an amateur
   enterprise UI.
9. **Severity and status never rely on colour alone** — always a text label, and an icon
   where space allows. Accessibility, and it survives a projector with bad colour.
10. **Do not restructure.** Add files where §5 says. Do not move pages, do not rename
    existing files, do not "reorganise" `api/client.ts`.

---

## 2. Setup

```bash
cd frontend && npm install && npm run dev
```

Vite serves `http://localhost:5173` and proxies `/api` → `http://127.0.0.1:5000`. **There
is no CORS in this project by construction** — one origin. If you hit a cross-origin
error, the fix is to route through the proxy, never to add headers or `flask-cors`.

You do **not** need the backend running to build screens — see the mock layer in §7.

```bash
npm run build     # tsc --noEmit && vite build — must pass clean before you call anything done
```

Stack already installed: React 19, TypeScript 5.6, Vite 5, antd 5.22, `@ant-design/icons`,
`@tanstack/react-query` 5, `zustand` 5, `recharts` 2.13, `react-markdown` 9,
`react-router-dom` 6. **Add no new dependencies** without asking — every added package is
a risk on a machine you cannot reinstall on demo day.

---

## 3. The product, in one paragraph

TriageIQ takes a raw IT maintenance ticket, runs it through a multi-agent pipeline
(normalise → retrieve precedent → classify → assess severity → route to a team → self-check
→ guardrails → human gate → sync back to Jira) and produces a **decision** the user can
accept, override, or trace back to the evidence it was based on. Two audiences:
**platform engineers** (Ops / Azure / AWS / GCP) who work a queue, and **support
managers** who watch all four queues, approve escalations and ask questions of the ticket
history. The UI's whole job is to make an AI decision **legible and reversible in two
clicks**.

---

## 4. Design brief

Corporate enterprise design language: crisp, clinical, trustworthy, calm. Warm off-white
grounds, muted accents, precise 4px geometry, breathable space. No stark contrasts, no
playful rounding, no gradients, no glassmorphism except where §4.5 allows.

**Density over decoration.** This is an operations console. A screen showing more verified
information beats one showing less, more beautifully.

### 4.1 Colour

| Role | Hex | Use |
|---|---|---|
| App background | `#FCFBF8` | The page itself. Buttery cream. |
| Surface | `#FFFFFF` | Cards, modals, drawers, table bodies, inputs |
| Surface alt | `#F5F4F0` | Sider, table headers, hover fills, user chat bubble |
| Border | `#EBE9E1` | Row dividers, card edges, input outlines |
| Text primary | `#1A1A1A` | **Never `#000000`** |
| Text secondary | `#5E5E5E` | Labels, helper text, metadata |
| Text tertiary | `#8A8A8A` | Placeholders, disabled. **Decorative only — fails AA, never for content** |
| Primary — clay | `#C45A5E` | Accents carrying **no text**: borders, icons, indicators, chart fills |
| Primary action | `#A84A4D` | **Filled buttons with white labels** (5.60:1 — passes AA) |
| Primary hover | `#8F3E41` | Hover on those buttons |
| Secondary — teal | `#4A7C82` | Links, focus rings, informational states, chart series 2 |
| Tertiary — ochre | `#B08D57` | "Needs attention", chart series 3 |
| Structural navy | `#2E3B4E` | Chart axes, dense headers, chart series 4 |

> **The one contrast trap.** White text on `#C45A5E` measures **4.23:1** — it looks fine
> and fails audit. Text-bearing fills use `#A84A4D`. This is why there are two "reds".

The warm ground is the whole trick: white cards on cream read as elevated without a shadow
doing the work. **Never put a white card on a white page.**

### 4.2 Semantic states

AntD's stock red/green/gold are far too saturated for this ground and will look like a
different product. They are overridden in the theme:

| State | Hex | Where it appears |
|---|---|---|
| Success | `#4F7A5B` | Groundedness ≥ 75%, synced, chain intact, S4 resolved |
| Warning | `#B08D57` | Groundedness 50–75%, awaiting approval, SLA at risk, S2 |
| Error | `#A84A4D` | Blocked answer, failed sync, broken chain, S1 |
| Info | `#4A7C82` | Retrieval mode badge, provider badge, S3, neutral notices |

### 4.3 Typography

```css
--font-body:    'JJ Circular Std Book', 'Circular Std', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
--font-heading: 'JJ Circular Std Black', 'Circular Std', 'Inter', system-ui, sans-serif;
```

The first two are licensed commercial faces almost certainly not on the build machine —
declared for machines that have them, `Inter`/`system-ui` is what will actually render.
**Do not add a webfont `<link>`;** a blocking font request before a demo is not worth it.

| Level | Size / line-height | Use |
|---|---|---|
| Display / H1 | `32px / 40px`, tracking `-0.02em` | Page title, one per screen. Also stat-tile values. |
| H2 | `24px / 1.4` | Section headings |
| H3 | `20px / 1.4` | Card titles |
| Label | `12px / 16px`, tracking `0.05em`, **uppercase**, text-secondary | Form labels, stat captions, citation tags |
| Body | `14px / 20px` | Default |
| Data | `13px` + `tabular-nums` | Any column of numbers, ids, hashes |

Negative tracking on the 32px display size only. At 14px it hurts legibility.

### 4.4 Geometry, elevation, and the two files that set them

- **8px grid.** Every padding, margin and gap is 8 / 16 / 24 / 32 / 40 / 48. No 10px, no 15px.
- **Radius:** `4px` buttons, inputs, tags, badges. `8px` cards, modals, drawers. **Nothing
  above 8px** — pill shapes read as consumer, not enterprise.
- **Elevation, diffuse and never dark:** card `0 4px 12px rgba(0,0,0,0.03)`, floating
  `0 8px 24px rgba(0,0,0,0.06)`. Prefer a 1px border to a shadow for anything not floating.
- **Control height:** 32px default, 24px small, 40px large.

**Task F0.1 — replace the placeholder theme in `src/main.tsx`.** Delete
`token: { colorPrimary: "#1668dc", borderRadius: 6 }` and paste this object into
`<ConfigProvider theme={…}>`:

```ts
{
  token: {
    colorPrimary: "#A84A4D",
    colorInfo: "#4A7C82",
    colorSuccess: "#4F7A5B",
    colorWarning: "#B08D57",
    colorError: "#A84A4D",

    colorBgLayout: "#FCFBF8",
    colorBgContainer: "#FFFFFF",
    colorBgElevated: "#FFFFFF",

    colorText: "#1A1A1A",
    colorTextSecondary: "#5E5E5E",
    colorTextTertiary: "#8A8A8A",
    colorBorder: "#EBE9E1",
    colorBorderSecondary: "#EBE9E1",

    borderRadius: 4,
    borderRadiusLG: 8,
    borderRadiusSM: 4,

    fontFamily:
      "'JJ Circular Std Book', 'Circular Std', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
    fontSize: 14,
    fontSizeHeading1: 32,
    fontSizeHeading2: 24,
    fontSizeHeading3: 20,
    lineHeight: 1.43,

    controlHeight: 32,
    boxShadow: "0 4px 12px rgba(0,0,0,0.03)",
    boxShadowSecondary: "0 8px 24px rgba(0,0,0,0.06)",
    wireframe: false,
  },
  components: {
    Layout: { bodyBg: "#FCFBF8", headerBg: "#FFFFFF", siderBg: "#F5F4F0", headerHeight: 56 },
    Menu: {
      itemBg: "#F5F4F0",
      itemSelectedBg: "#FFFFFF",
      itemSelectedColor: "#A84A4D",
      itemHoverBg: "#FCFBF8",
      itemBorderRadius: 4,
    },
    Table: {
      headerBg: "#F5F4F0",
      headerColor: "#5E5E5E",
      rowHoverBg: "#FCFBF8",
      borderColor: "#EBE9E1",
      cellPaddingBlock: 12,
    },
    Card: { paddingLG: 24, headerBg: "transparent" },
    Button: { primaryShadow: "none", defaultShadow: "none", contentFontSize: 14 },
    Input: {
      activeBorderColor: "#4A7C82",
      hoverBorderColor: "#4A7C82",
      activeShadow: "0 0 0 2px rgba(74,124,130,0.10)",
    },
    Tag: { defaultBg: "#F5F4F0", defaultColor: "#5E5E5E" },
  },
}
```

Keep `algorithm: theme.defaultAlgorithm`. **This is the single highest-leverage 20 minutes
in the whole frontend build — do it first.** Retro-fitting a theme over screens built
against AntD defaults costs three times as much.

**Task F0.2 — create `frontend/src/index.css`** (it does not exist yet) and import it once
at the top of `main.tsx`. It covers only the handful of elements we author ourselves;
everything else takes the theme above.

```css
:root {
  --bg-app: #FCFBF8;
  --bg-surface: #FFFFFF;
  --bg-surface-alt: #F5F4F0;

  --accent: #C45A5E;            /* non-text use only */
  --accent-action: #A84A4D;     /* text-bearing fills */
  --accent-action-hover: #8F3E41;
  --accent-secondary: #4A7C82;
  --structural-navy: #2E3B4E;

  --text-primary: #1A1A1A;
  --text-secondary: #5E5E5E;
  --border-color: #EBE9E1;

  --success: #4F7A5B;
  --warning: #B08D57;
  --error: #A84A4D;
  --info: #4A7C82;

  --font-body: 'JJ Circular Std Book', 'Circular Std', 'Inter', system-ui, sans-serif;
  --font-heading: 'JJ Circular Std Black', 'Circular Std', 'Inter', system-ui, sans-serif;

  --radius-sm: 4px;
  --radius-md: 8px;
  --space: 8px;
  --shadow-card: 0 4px 12px rgba(0, 0, 0, 0.03);
  --shadow-float: 0 8px 24px rgba(0, 0, 0, 0.06);

  --glass-bg: rgba(252, 251, 248, 0.72);
  --glass-blur: blur(12px) saturate(115%);
}

body {
  background: var(--bg-app);
  color: var(--text-primary);
  font-family: var(--font-body);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

h1, h2, h3 { font-family: var(--font-heading); color: var(--text-primary); }
h1 { font-size: 32px; line-height: 40px; letter-spacing: -0.02em; }

.tabular { font-variant-numeric: tabular-nums; }
```

### 4.5 Glass — restrained, or not at all

Allowed **only** on floating chrome: the sticky app header, the chatbot drawer panel, a
modal backdrop, a float button. **Forbidden** on content cards, table rows, stat tiles, or
anything containing body copy. Opacity stays ≥ 0.7, blur ≤ 12px, and never
`backdrop-filter` on a scrolling surface — it repaints every frame and will visibly stutter
the demo on integrated graphics. **If the header janks, delete the glass.** It is worth
zero points and a stutter is worth negative ones.

### 4.6 Charts (Recharts)

Recharts props cannot read AntD tokens, so hexes are permitted **only** here. Define them
once in `src/components/chartTheme.ts` and import — never inline in a page.

```ts
export const SERIES = ["#C45A5E", "#4A7C82", "#B08D57", "#2E3B4E"]; // clay, teal, ochre, navy — in this order
export const AXIS = "#2E3B4E";
export const GRID = "#EBE9E1";
```

Rules: series colours in that order, always. Axis and grid from the constants above.
`<CartesianGrid stroke={GRID} strokeDasharray="3 3" />`. No AntD-default blue/green
anywhere. Height 260px inside a `<Card size="small">` wrapped in `<ResponsiveContainer>`.
Legend on, tooltip on, dots off on line charts.

### 4.7 Components

- **Primary button** — `type="primary"`, fills `#A84A4D` from the theme, no shadow.
  One per screen region; a screen with three primary buttons has no primary action.
- **Secondary** — default AntD button (white, 1px border). **Text button** for tertiary.
  There is no third filled style.
- **Tags** — 4px radius, tinted background at ~12% of the semantic colour with the solid
  colour as text. Never full-saturation fills. Use AntD `<Tag color="…">` with the
  semantic names, which the theme has already remapped.
- **Cards** — white on cream, 8px radius, 1px border **and** the soft shadow, 24px padding,
  16px between title and body. `<Card size="small">` for dense regions.
- **Tables** — header `#F5F4F0` with 12px uppercase labels, 1px row dividers, hover
  `#FCFBF8`, **no zebra striping** (it fights the warm ground).
- **Inputs** — focus ring is `1px solid #4A7C82` + `0 0 0 2px rgba(74,124,130,0.10)`,
  already in the theme. Never override it away.

---

## 5. File map

Create exactly these. **Nothing else.**

```
frontend/src/
  index.css                      NEW — §4.4
  main.tsx                       EDIT — theme object + import "./index.css"
  App.tsx                        EDIT — new routes, role-aware redirect
  api/
    client.ts                    EDIT — add types + endpoints from §6
    mocks.ts                     NEW — fixture data, §7
  store/
    ui.ts                        NEW — Zustand: filters, drawer state, selection
  components/
    ChatbotDrawer.tsx            EDIT — voice button, restyle bubbles to tokens
    DecisionDrawer.tsx           NEW — the decision card. Used by Queue AND History.
    SeverityTag.tsx              NEW — severity + status + confidence display atoms
    StatTile.tsx                 NEW — the dashboard/control stat tile
    GraphRunner.tsx              NEW — the live agent-pipeline visual
    TicketTable.tsx              NEW — shared server-side table, used by Queue + History
    VoiceButton.tsx              NEW — push-to-talk
    chartTheme.ts                NEW — §4.6
  layouts/
    AppLayout.tsx                EDIT — nav by role, product name, header badges
  pages/
    Login.tsx                    EDIT — two modes, design pass
    Queue.tsx                    NEW
    History.tsx                  NEW
    Triage.tsx                   NEW
    Control.tsx                  NEW
    Dashboard.tsx  Chat.tsx  Documents.tsx  Evals.tsx  Audit.tsx   EDIT — design pass only
```

---

## 6. API contract

Backend returns `{"data": …, "meta": {…}}` on success and
`{"error": {"code", "message"}}` on failure. **`client.ts` already unwraps this** — your
components see `{ data, meta }` and never the envelope. A 401 auto-clears the token and
bounces to `/login`; do not re-implement that.

### 6.1 Types — add these to `src/api/client.ts`

```ts
export type Severity = "S1" | "S2" | "S3" | "S4";
export type Team = "ops" | "azure" | "aws" | "gcp";
export type TicketStatus =
  | "new" | "triaged" | "awaiting_approval" | "routed" | "synced" | "failed" | "resolved";

export interface TicketRow {
  id: string;
  external_id: string;              // "INC0012345"
  source: "jira" | "synthetic" | "manual";
  title: string;
  application: string;
  environment: "prod" | "uat" | "dev";
  category: string;
  severity: Severity;
  priority_score: number;           // 0–100
  assigned_team: Team | null;
  status: TicketStatus;
  confidence: number;               // 0–1
  needs_human: boolean;
  sla_target_mins: number;
  sla_due_at: string | null;        // ISO — drives the countdown
  overridden_by: string | null;
  override_reason: string | null;
  created_at: string;
  resolved_at: string | null;
  resolution_minutes: number | null;
}

export interface TriageDecision {
  ticket_id: string;
  category: string;
  subcategory: string;
  severity: Severity;
  priority_score: number;
  assigned_team: Team;
  sla_target_mins: number;
  confidence: number;
  rationale: string;                // markdown, cites [C1] [C2]
  evidence: Citation[];
  duplicate_of: string | null;
  suggested_first_action: string;
  needs_human: boolean;
  escalation_reason: string;
}

export interface TicketDetail {
  ticket: TicketRow;
  body_masked: string;
  decision: TriageDecision | null;
  guardrails_fired: { type: string; detail?: string }[];
  model: string;                    // e.g. "genailab-maas-gpt-5.1"
  tier: "fast" | "standard" | "deep";
  latency_ms: number;
  total_tokens: number;
  cost_usd: number;
  trace_id: string;
}

export interface TimelineEvent {
  at: string;                       // ISO
  kind: "triaged" | "override" | "approved" | "synced" | "failed" | "resolved" | "blocked";
  actor: string;                    // username or "system"
  summary: string;
  detail?: Record<string, unknown>;
}

/** One node of the triage graph, streamed-in-effect by polling or returned in bulk. */
export interface GraphNode {
  name: "normalize" | "enrich" | "grade" | "classify" | "assess" | "route"
      | "reflect" | "verify" | "gate" | "sync";
  status: "pending" | "running" | "done" | "skipped" | "failed";
  ms: number;
  tokens: number;
  tier: "fast" | "standard" | "deep" | null;
  output_summary: string;
}

export interface TriageRunResult {
  ticket: TicketRow;
  decision: TriageDecision;
  nodes: GraphNode[];
  retries: number;
  total_ms: number;
  total_tokens: number;
  cost_usd: number;
}

export interface TriageAnalytics {
  by_severity: { severity: Severity; count: number }[];
  by_team: { team: Team; open: number; capacity: number; oldest_age_mins: number }[];
  over_time: { date: string; triaged: number; overridden: number }[];
  classification_accuracy: number;  // 0–1
  routing_precision: number;        // 0–1
  severity_mae: number;
  override_rate: number;
  avg_cost_usd: number;
  avg_latency_ms: number;
  sla_at_risk: number;
  awaiting_approval: number;
}
```

### 6.2 Endpoints — add to the `api` object in `client.ts`

| Method | Path | Signature |
|---|---|---|
| GET | `/tickets` | `tickets(params?: ListParams) => Paged<TicketRow>` |
| GET | `/tickets/:id` | `ticket(id) => TicketDetail` |
| GET | `/tickets/:id/timeline` | `ticketTimeline(id) => TimelineEvent[]` |
| POST | `/tickets` | `createTicket(body: {title, description, application?, environment?}) => TriageRunResult` |
| POST | `/tickets/bulk` | `bulkTriage(count: number) => { processed, total_ms, results: TriageRunResult[] }` |
| POST | `/tickets/:id/retriage` | `retriage(id) => TriageRunResult` |
| PATCH | `/tickets/:id/override` | `override(id, {field, new_value, reason}) => TicketRow` |
| POST | `/tickets/:id/approve` | `approve(id) => TicketRow` |
| GET | `/teams/queue` | `teamQueue(params?: ListParams) => Paged<TicketRow>` |
| GET | `/analytics/triage` | `triageAnalytics() => TriageAnalytics` |
| POST | `/voice/transcribe` | `transcribe(blob: Blob) => { text: string }` — multipart |
| POST | `/integrations/sync` | `syncNow() => { pulled, pushed, failed }` |

Everything else (`login`, `chat`, `chatbot`, `documents`, `search`, `evals`, `audit`,
`usage`, `traces`, `feedback`) already exists in `client.ts` — **read it before writing
anything, and follow its shape exactly.**

### 6.3 List-endpoint contract

Every table endpoint accepts `page`, `page_size`, `sort`, `order`, `q`, and
`filter[<field>]`, and returns `meta: { total, page, page_size, pages }`. `ListParams` and
`toQueryString` in `client.ts` already build this — use them, do not hand-roll a query
string.

Filterable fields on tickets: `status`, `severity`, `assigned_team`, `category`,
`environment`, `source`, `needs_human`. Searchable via `q`: `external_id`, `title`.
Date range on History: `from` / `to` as top-level params.

### 6.4 What the backend enforces, so you don't

**Access control is enforced server-side.** An engineer's token scopes the query — you do
**not** filter by team in the client, and you must not add a team filter that an engineer
could use to peek at another team. On `Control.tsx` the team filter is legitimate because
only managers can reach that route. Hide manager-only nav from engineers as a *courtesy*;
the security boundary is the API, not the menu.

---

## 7. Working before the backend exists

`src/api/mocks.ts` exports a fixture for every shape in §6.1 — ~24 tickets across four
teams, all four severities, two `needs_human`, one `failed` sync, one blocked-by-guardrail,
plus a canned `GraphNode[]` sequence with realistic per-node latencies.

In `client.ts`, at the top of `request()`:

```ts
if (import.meta.env.VITE_USE_MOCKS === "true") return mockResponse<T>(path, init);
```

Run mocked with `VITE_USE_MOCKS=true npm run dev`. **Delete nothing when the backend
lands** — flip the flag off. Keeping mocks alive means a backend outage during the demo
does not cost you the UI, and you can develop on a laptop with no Ollama running.

Mock latency: `await sleep(400 + Math.random() * 600)` so loading states are real and you
actually build them. The `GraphRunner` mock should step nodes on a timer so the animation
is developed against something honest.

---

## 8. Shared conventions

### 8.1 Query keys

```
["health"] ["me"]
["tickets", params] ["ticket", id] ["ticket-timeline", id]
["team-queue", params] ["triage-analytics"]
["usage"] ["message-metrics"] ["traces"] ["evals", params] ["audit", params] ["documents", params]
```

After any mutation (`override`, `approve`, `retriage`, `createTicket`) invalidate
`["tickets"]`, `["team-queue"]` and `["triage-analytics"]`. Refetch intervals: analytics
and queue `10_000`, health `30_000`. Everything else on demand.

### 8.2 Zustand — `src/store/ui.ts`

Holds **only**: `queueFilters`, `historyFilters`, `selectedTicketId`, `drawerOpen`,
`voiceEnabled`. Never a ticket object, never a response, never anything TanStack owns.

### 8.3 Toasts and errors

`const { message: toast } = App.useApp()` — the `<AntApp>` provider is already in
`main.tsx`. Success toasts state the *outcome* with a number: "Routed to AWS · SLA 4h" not
"Success". Errors surface `error.message` from `ApiError`, which already carries the
backend's message.

### 8.4 Every screen ships four states

Never merge a screen with only the happy path.

| State | Treatment |
|---|---|
| Loading | AntD `loading` prop on Table/Card. **No full-page spinners** on a screen that has a layout. |
| Empty | `<Empty>` with copy naming the next action — "No tickets in your queue. Triage one from the Triage tab." |
| Error | Inline `<Alert type="error">` with the message and a Retry button. Never a blank screen. |
| Blocked / degraded | Tinted `--error` at 8% background with the guardrail reason spelled out. This is a *feature* here — it is the demo's third beat. Make it look intentional, not broken. |

### 8.5 Domain display maps

Put these in `src/components/SeverityTag.tsx` and import everywhere. Defining them twice is
how the UI drifts.

```ts
export const SEVERITY = {
  S1: { label: "S1 · Critical", color: "error",   icon: <FireOutlined /> },
  S2: { label: "S2 · High",     color: "warning", icon: <WarningOutlined /> },
  S3: { label: "S3 · Medium",   color: "info",    icon: <InfoCircleOutlined /> },
  S4: { label: "S4 · Low",      color: "default", icon: <MinusCircleOutlined /> },
} as const;

export const STATUS = {
  new:               { label: "New",         color: "default" },
  triaged:           { label: "Triaged",     color: "info" },
  awaiting_approval: { label: "Needs review", color: "warning" },
  routed:            { label: "Routed",      color: "info" },
  synced:            { label: "Synced",      color: "success" },
  resolved:          { label: "Resolved",    color: "success" },
  failed:            { label: "Sync failed", color: "error" },
} as const;

export const TEAM_LABEL = { ops: "Ops", azure: "Azure", aws: "AWS", gcp: "GCP" } as const;
```

Confidence display: ≥ 0.85 success, 0.70–0.85 warning, < 0.70 error **and** the row shows
"Needs review". Always render the number too — `87%` in tabular figures. A bar alone is
not an answer.

---

## 9. Screen specs

### 9.1 `Login.tsx` — two surfaces, one file

Two routes, one component, a `mode` prop. Do **not** duplicate the file.

| Route | Mode | Title | Sub | Demo hint | Redirects to |
|---|---|---|---|---|---|
| `/login` | `team` | "TriageIQ — Team Console" | "Sign in to your team queue" | `aws1 / aws123` | `/queue` |
| `/manager/login` | `manager` | "TriageIQ — Manager Console" | "Queue oversight, approvals and history" | `manager / manager123` | `/control` |

Cream page, single 380px white card centred, `#A84A4D` submit button (from the theme —
kill the AntD blue). Team mode shows a `<Select>` of Ops/Azure/AWS/GCP above the username
**as a convenience that prefills the username** (`aws` → `aws1`); the actual authority is
the role in the JWT, so treat the picker as UX, not access control. A small text link
switches between the two consoles.

After `api.login()`, `auth.set(token)`, then redirect **by the role in `data.user.role`**:
`manager`/`admin` → `/control`, `engineer` → `/queue`. Do not trust the route the user
came from.

**Done when:** all five demo accounts sign in, each lands on the right screen, and there is
no AntD blue anywhere on the page.

### 9.2 `AppLayout.tsx` — shell

Sider `#F5F4F0`, header white (glass optional, §4.5), content cream. Product name
**TriageIQ** replaces the `[PLACEHOLDER: PRODUCT_NAME]`; tagline replaces the other
placeholder: *"Multi-agent ticket triage — classified, prioritised, routed, and auditable."*

Nav, filtered by role:

| Item | Route | Engineer | Manager |
|---|---|---|---|
| My Queue | `/queue` | ✓ | ✓ (all teams) |
| Triage | `/triage` | ✓ | ✓ |
| History | `/history` | ✓ | ✓ |
| Control Tower | `/control` | — | ✓ |
| Assistant | `/chat` | — | ✓ |
| Knowledge Base | `/documents` | — | ✓ |
| Evaluations | `/evals` | — | ✓ |
| Audit Trail | `/audit` | — | ✓ |
| Dashboard | `/dashboard` | — | ✓ |

Header keeps the existing `/api/health` badges (provider · model, retrieval mode, chunk
count) — **restyle them to semantic tags, they are currently AntD blue/green/purple** — and
adds the live cost/latency ticker: `last answer 2.4s · 1,840 tok · $0.0031`, all
`tabular-nums`. Right side: username + role tag + Sign out.

### 9.3 `Queue.tsx` — the engineer console *(the screen that gets used)*

`GET /teams/queue`. Above the table, four small stat tiles: **Open**, **S1 open**,
**SLA at risk**, **Awaiting review**.

Columns — id, title (ellipsis, tooltip), severity, priority, SLA, age, team (managers
only), confidence, status:

| Column | Notes |
|---|---|
| `external_id` | 13px data font, tabular, monospace-feel. Sortable. |
| `title` | `<Typography.Text ellipsis>`, tooltip on hover. The widest column. |
| `severity` | `<SeverityTag>`. Sortable. |
| `priority_score` | Right-aligned, `tabular`, 0–100. **Default sort, desc.** |
| `sla_due_at` | `<SlaCountdown>` — live `mm:ss` under 1h, `2h 40m` above. Ochre under 30min, error when breached. |
| `created_at` | Relative age ("18m"). |
| `confidence` | Small bar + number per §8.5. |
| `status` | `<StatusTag>`. |

Row click → `<DecisionDrawer>`. **Triage-to-action must be two clicks: row → Accept.**

Keyboard: `j`/`k` move selection, `Enter` open, `a` accept, `o` override, `/` focus search,
`Esc` close. Show the shortcuts in a small `<Tooltip>` on a "?" icon — an unadvertised
shortcut is a shortcut nobody uses, including the judge.

**Done when:** logging in as `aws1` shows only AWS tickets, `ops1` shows a different set,
and accepting a ticket updates the row without a full-page refetch flash.

### 9.4 `DecisionDrawer.tsx` — the component everything hangs off

560px right drawer, `--shadow-float`. Used by Queue (actionable) and History (read-only)
— one component, a `readOnly` prop. **Build this well; it is on screen for most of the
demo.**

Sections, top to bottom:

1. **Header** — `INC0012345` + title, severity tag, status tag, team tag.
2. **The decision, stated as a sentence.** *"Routed to **AWS** as **S2 · High**, priority
   **78**, SLA **4h**, confidence **87%**."* One line, plain language, before any detail.
   A judge who reads nothing else must get the decision from this line.
3. **Rationale** — `<Markdown>` of `decision.rationale`, with `[C1]`/`[C2]` rendered as
   clickable citation chips (12px uppercase, teal).
4. **Evidence** — the cited chunks: filename, page, snippet, and for precedent tickets a
   link into `/history`. Click a chip in §3 → scrolls and highlights the matching item here.
5. **Suggested first action** — bordered callout, ochre left rule. Label it clearly as a
   *recommendation*; **the system never executes it** and the UI must not imply otherwise.
6. **Provenance** — collapsed `<Descriptions size="small">`: model, tier, latency, tokens,
   cost, trace id, retrieval mode, guardrails fired, prompt version. This is the
   "model card" judges ask for. Add a Copy button.
7. **Actions** (hidden when `readOnly`) — **Accept** (primary), **Reassign** (select team +
   mandatory reason), **Dispute severity** (select + mandatory reason), **Re-triage**
   (text button). Managers additionally get **Approve** when `needs_human`.

Override modal: the reason field is `required` with `min 10 chars`. Say why in the helper
text — *"Your reason trains the eval set."* That is true, and it makes people write one.

If `guardrails_fired` is non-empty, a tinted banner sits directly under the header naming
each one. If the ticket was blocked, the drawer leads with that and hides the decision.

### 9.5 `History.tsx` — previous tickets *(both roles)*

Same `<TicketTable>` component, different endpoint (`/tickets`) and different defaults:
status filter defaults to *closed states*, sort `created_at desc`, date-range picker
(default last 30 days) wired to `from`/`to`.

Filter bar: search (`q` on id + title), severity, team (managers only — see §6.4), category,
environment, status, date range. Every filter change resets `page` to 1 and lands in the
Zustand `historyFilters` so a drawer round-trip does not lose them.

Extra columns vs Queue: `resolved_at`, `resolution_minutes` (tabular), and an
**Overridden** column — a small ochre tag when `overridden_by` is set. That column is
quietly the most interesting thing on the screen: it is where a manager sees how often the
AI was wrong.

Row click → `<DecisionDrawer readOnly>` **plus a Timeline tab** rendering
`GET /tickets/:id/timeline` as an AntD `<Timeline>`: triaged → overridden by X ("reason") →
approved by Y → synced to Jira → resolved. Colour each node semantically.

Two actions on a historical ticket: **Find similar** (`api.search` on its title+body,
results as a compact list with scores) and **Reuse resolution** (copies the resolution text
into a target open ticket's first-action field — a manager-only convenience; if it looks
like more than 30 minutes, cut it and say so).

**Done when:** an `aws1` login sees AWS history only; the timeline of an overridden ticket
reads as a coherent story; filters survive opening and closing the drawer.

### 9.6 `Triage.tsx` — the demo centrepiece

Two tabs.

**Tab 1 — Live triage.** Left: a `<Input.TextArea rows={8}>` for the ticket body, a title
field, application/environment selects, a **`<VoiceButton>`**, three "load sample"
buttons (a clean RDS failover ticket, a vague one-liner, and the **injected** ticket), and
a primary **Triage** button.

Right: `<GraphRunner>` — the ten nodes as a vertical stepper, each with name, one-line
plain-English description, status dot, latency, tokens and model tier badge. Nodes light
up in sequence. If `retries > 0`, draw the loop-back edge visibly and label it *"low
retrieval confidence — re-retrieved once"*. **That visible retry is the single best
multi-agent proof on the screen; do not hide it.**

If the backend returns the whole run at once, animate the reveal client-side at the real
per-node latencies rather than dumping it — the animation must never claim a timing the
data does not contain.

Below: the decision card (reuse `<DecisionDrawer>`'s inner content as an inline panel —
extract the body into `DecisionBody` so both the drawer and this page render it).

**Tab 2 — Bulk.** A count selector (10 / 25 / 50), a Run button, a live progress bar,
throughput (`tickets/min`, tabular), a running cost total, and a compact result table
grouped by assigned team. This is the "does it scale" answer.

**Done when:** the injected sample visibly gets blocked with the reason shown, and a
50-ticket run completes with a real throughput number on screen.

### 9.7 `Control.tsx` — manager control tower

**Row 1 — stat tiles** (`<StatTile>`, 32px heading values, tabular): Open by severity
(four tiles), SLA at risk, Awaiting approval, Classification accuracy, Routing precision,
Override rate, Avg cost/decision, Tokens today.

**Row 2 — charts** from `GET /analytics/triage`, in the §4.6 palette:
severity distribution (bar), per-team volume vs capacity (grouped bar), decisions over time
with overrides overlaid (line), category mix (bar — **not** a pie; a pie of eight
categories is unreadable and reads as a student project).

**Row 3 — approval queue.** Every `needs_human` decision: id, title, severity, team,
confidence, **escalation reason** (the most important column — why the system stopped),
and inline Approve / Override. Approving requires no reason; overriding always does.

**Row 4 — recent overrides**, so the manager can see the correction pattern. Small table,
last ten, each linking into History.

**Done when:** approving an item removes it from the queue and increments the routed
count; every number on this screen traces to an endpoint, none are computed in the browser
from a partial page of rows.

### 9.8 `Chat.tsx` + `ChatbotDrawer.tsx` — manager assistant

Design pass, plus two changes. Restyle the hard-coded bubble colours
(`#e6f4ff` / `#fff2f0` / `#fafafa` currently in `ChatbotDrawer.tsx`) to
`--bg-surface-alt` for user, white + border for assistant, `--error` at 8% for blocked.
Add the `<VoiceButton>`. Groundedness renders as a semantic tag with the number
(≥75% success, 50–75% warning, <50% error).

**One thing to render specially:** when the answer came from the deterministic
`ticket_stats` tool, the backend marks it and the UI shows a teal **"Counted from the
database, not generated"** chip. That chip is worth more than any chart on the screen —
it is the honest answer to "how do you know it isn't hallucinating the number".

### 9.9 `Dashboard.tsx`, `Evals.tsx`, `Audit.tsx`, `Documents.tsx`

**Design pass only** — do not restructure them. Replace the AntD-default chart colours in
`Dashboard.tsx` (`#1668dc`, `#52c41a`) with `SERIES[0]`/`SERIES[1]`, add `className="tabular"`
to numeric columns, remap tags to the semantic set, and drop the domain placeholder
comments.

`Evals.tsx` additionally gets the **triage accuracy panel**: classification accuracy,
routing precision, severity MAE, a small confusion matrix (a plain `<Table>` is fine —
resist building a heatmap), and the **hybrid-vs-vector A/B** as two labelled score
columns. `Audit.tsx` gets the hash column in the data font with `tabular` so hashes align,
and the chain-verification result as a success/error banner.

---

## 10. Voice

`<VoiceButton>` on `Chat.tsx`, `ChatbotDrawer.tsx` and `Triage.tsx`.

Web Speech API first (`window.SpeechRecognition ?? window.webkitSpeechRecognition`), zero
upload and zero latency. If unavailable, record with `MediaRecorder` and POST the blob to
`/voice/transcribe` (Whisper). If both fail, the button hides itself — it never blocks
typing.

**Three rules, non-negotiable:**
1. The transcript appears in the normal input field, **editable**, before anything happens.
2. **No voice command ever triggers a write without an on-screen confirm.** Read-only
   queries may run on release; approve/override/triage always show a confirm step.
3. The typed input stays visible and usable at all times. Voice is an accelerator, never a
   mode.

States: idle (mic icon, secondary), listening (clay pulse ring + live transcript),
transcribing (spinner), error (tooltip with the reason, falls back to typing silently).

**Do not spend more than 90 minutes here.** It is a nice-to-have that demos badly in a
noisy hall; the fallback path is the real path.

---

## 11. Accessibility

- Contrast: body text `#1A1A1A` on `#FCFBF8`, secondary `#5E5E5E` (5.99:1 — passes).
  **Never `#8A8A8A` for content.** Never white text on `#C45A5E`.
- Focus rings stay. Every interactive element is reachable by keyboard; the drawer traps
  focus and `Esc` closes it.
- Severity, status and groundedness always carry a text label — colour is reinforcement,
  never the sole carrier.
- Tables get `scroll={{ x: true }}` so nothing is lost at 1280px; the demo screen may not
  be your screen.
- `aria-label` on every icon-only button. The mic, the copy button, the row actions.
- Respect `prefers-reduced-motion` in the `GraphRunner` animation — snap to final state
  rather than animating.

---

## 12. Build order

| # | Task | Est | Gate |
|---|---|---|---|
| F0.1 | Theme object into `main.tsx` | 20m | Zero AntD blue anywhere |
| F0.2 | `index.css` + import | 10m | Cream ground visible on every page |
| F0.3 | `mocks.ts` + `VITE_USE_MOCKS` | 40m | Every screen buildable with the backend off |
| F0.4 | Types + endpoints into `client.ts` | 30m | `npm run build` clean |
| F1.1 | `SeverityTag`, `StatTile`, `chartTheme` | 40m | Imported, not duplicated |
| F1.2 | `Login.tsx` two modes + role redirect | 45m | Five accounts land correctly |
| F1.3 | `AppLayout` nav by role, product name, ticker | 45m | Engineer cannot see manager nav |
| F2.1 | `TicketTable` shared server-side table | 60m | Paging/sort/filter all server-side |
| F2.2 | `DecisionDrawer` + `DecisionBody` | 90m | Renders decision, evidence, provenance, actions |
| F2.3 | `Queue.tsx` + keyboard shortcuts | 60m | Two clicks to accept |
| F2.4 | `History.tsx` + timeline | 60m | Filters persist; timeline reads as a story |
| F3.1 | `GraphRunner` | 75m | Retry edge visible when it happens |
| F3.2 | `Triage.tsx` both tabs | 75m | Injected sample blocks visibly |
| F3.3 | `Control.tsx` tiles + charts + approval queue | 90m | Approve empties the row |
| F4.1 | Design pass on the five existing pages | 60m | No AntD defaults left |
| F4.2 | `VoiceButton` | 90m | Confirm-before-write proven |
| F4.3 | Empty / error / loading states audit | 45m | Every screen has all four |

**≈ 15h single-track.** If you are tight, cut in this order: Voice (F4.2) → Reuse
resolution (9.5) → Bulk tab (9.6 tab 2) → glass on the header. **Never cut**
`DecisionDrawer` quality, the blocked-state styling, or the four-states audit — those are
what the demo is actually made of.

---

## 13. Definition of done

- [ ] `npm run build` passes (`tsc --noEmit` included) with zero errors
- [ ] No `#` hex in any `.tsx` outside `main.tsx` and `chartTheme.ts`
- [ ] No `fetch` outside `api/client.ts`
- [ ] No client-side pagination anywhere
- [ ] Every table's numeric columns are right-aligned and `tabular`
- [ ] Every screen has loading, empty, error and blocked states
- [ ] `aws1` and `ops1` see different data on Queue and History
- [ ] Engineer nav has no manager routes; typing `/control` manually still fails at the API
- [ ] Keyboard: tab through Queue, open the drawer, accept, `Esc` — no mouse
- [ ] Works at 1280×800 without horizontal page scroll
- [ ] Runs with `VITE_USE_MOCKS=true` and with the real backend

---

## 14. Do not

- Add a dependency, a UI library, Tailwind, or styled-components
- Build a dark theme or a theme switcher
- Round anything past 8px, or use `#000000`
- Put white text on `#C45A5E`
- Apply `backdrop-filter` to a table, list or any scrolling surface
- Compute totals in the browser from one page of rows — ask the analytics endpoint
- Duplicate `DecisionDrawer` for History; it takes a `readOnly` prop
- Invent an endpoint. If you need data that §6 does not list, ask — the backend adds it
- Imply the system executes remediation. It **recommends**; a human acts
- Restyle, rename or move an existing page while doing a "design pass"
