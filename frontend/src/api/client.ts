/**
 * The only place the app talks HTTP.
 *
 * Unwraps the backend's {data, meta} / {error} envelope so components never see it,
 * attaches the JWT, and drops the token on a 401 so an expired session bounces to
 * login instead of failing silently.
 */

const TOKEN_KEY = "auth_token";

export const auth = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

/** Bind /me (and role-gated UI) to the current JWT so a new login never reuses the previous user. */
export function meQueryKey() {
  return ["me", auth.get() ?? "anon"] as const;
}

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message);
  }
}

/** Standard list-endpoint contract — same for documents, sessions, audit, evals. */
export interface ListParams {
  page?: number;
  page_size?: number;
  sort?: string;
  order?: "asc" | "desc";
  q?: string;
  filter?: Record<string, string | undefined>;
}

export interface Paged<T> {
  data: T[];
  meta: { total: number; page: number; page_size: number; pages: number };
}

function toQueryString(params: ListParams = {}): string {
  const search = new URLSearchParams();
  const { filter, ...rest } = params;
  Object.entries(rest).forEach(([k, v]) => {
    if (v !== undefined && v !== "") search.set(k, String(v));
  });
  Object.entries(filter ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== "") search.set(`filter[${k}]`, String(v));
  });
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<{ data: T; meta: any }> {
  // Mock mode keeps every screen buildable with the backend off, and keeps the demo
  // alive if the backend dies. Flip the flag, delete nothing.
  if (import.meta.env.VITE_USE_MOCKS === "true") {
    const { mockResponse } = await import("./mocks");
    return mockResponse<T>(path, init);
  }

  const token = auth.get();
  const isFormData = init.body instanceof FormData;

  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });

  const payload = await response.json().catch(() => ({}));

  if (!response.ok) {
    if (response.status === 401) {
      auth.clear();
      if (!location.pathname.startsWith("/login")) {
        location.href = "/login";
      }
    }
    const error = payload?.error ?? {};
    throw new ApiError(error.code ?? "unknown", error.message ?? response.statusText, response.status);
  }

  return { data: payload.data as T, meta: payload.meta ?? {} };
}

const get = <T,>(path: string) => request<T>(path);
const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
const patch = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined });
const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });

async function list<T>(path: string, params?: ListParams): Promise<Paged<T>> {
  const { data, meta } = await request<T[]>(`${path}${toQueryString(params)}`);
  return { data, meta };
}

// --- types (mirror backend/rag/schemas.py) ----------------------------------

export interface Citation {
  label: string;
  doc_id: string;
  filename: string;
  page: number | null;
  snippet: string;
}

export interface ChatResponse {
  session_id: string;
  message_id: string;
  answer: string;
  citations: Citation[];
  suggestions: string[];
  groundedness: number | null;
  blocked: boolean;
  blocked_reason: string | null;
  latency_ms: number;
  total_tokens: number;
  trace_id: string;
  /** Only ever non-empty for role=="admin" on a ticket-SQL answer (e.g. "get me
   * all P1 issues") — ids the "Bulk approve & route" button sends to
   * POST /tickets/bulk-approve. */
  actionable_ticket_ids: string[];
}

export interface BulkApproveResult {
  ticket_id: string;
  ok: boolean;
  ticket?: TicketRow;
  code?: string;
  message?: string;
}

export interface RetrievedChunk {
  id: string;
  doc_id: string;
  filename: string;
  text: string;
  page: number | null;
  score: number;
  vector_rank: number | null;
  keyword_rank: number | null;
  rerank_score: number | null;
  metadata?: Record<string, unknown>;
}

export interface DocumentRow {
  id: string;
  filename: string;
  modality: string;
  sensitivity: string;
  allowed_roles: string[];
  chunk_count: number;
  status: string;
  created_at: string;
}

export interface User {
  id: string;
  username: string;
  role: string;
  clearances: string[];
}

// --- triage domain ----------------------------------------------------------

export type Severity = "Highest" | "High" | "Medium" | "Low";

const LEGACY_SEVERITY: Record<string, Severity> = {
  S1: "Highest",
  S2: "High",
  S3: "Medium",
  S4: "Low",
};

/** Map legacy S1–S4 (and case variants) onto Jira Priority names. */
export function normalizeSeverity(value: string | null | undefined): Severity | "" {
  if (!value) return "";
  const raw = String(value).trim();
  if (raw === "Highest" || raw === "High" || raw === "Medium" || raw === "Low") return raw;
  const mapped = LEGACY_SEVERITY[raw.toUpperCase()];
  if (mapped) return mapped;
  const hit = (["Highest", "High", "Medium", "Low"] as Severity[]).find(
    (name) => name.toLowerCase() === raw.toLowerCase()
  );
  return hit ?? "";
}
export type Team = "ops" | "azure" | "aws" | "gcp";
export type TicketStatus =
  | "new" | "triaged" | "awaiting_approval" | "approved" | "routed" | "synced" | "failed" | "resolved";

export interface TicketRow {
  id: string;
  external_id: string;              // "SCRUM-3" / "INC0012345"
  source: "jira" | "synthetic" | "manual";
  title: string;
  body_masked?: string;
  application: string;
  environment: "prod" | "uat" | "dev" | string;
  category: string;
  subcategory?: string;
  /** Empty string until triage finishes — treat as unset in the UI. */
  severity: Severity | "";
  priority_score: number;           // 0–100
  assigned_team: Team | "" | null;
  status: TicketStatus | string;
  confidence: number;               // 0–1
  needs_human: boolean;
  /** Optional — live Ticket.to_dict does not send SLA fields. */
  sla_target_mins?: number;
  sla_due_at?: string | null;
  overridden_by: string | null;
  override_reason: string | null;
  last_error?: string | null;
  sync_attempts?: number;
  /** From latest TriageRun — why the gate held the ticket (Control Tower). */
  escalation_reason?: string | null;
  confidence_limited_by?: string | null;
  confidence_gates?: Record<string, number> | null;
  created_at: string;
  updated_at?: string | null;
  resolved_at?: string | null;
  resolution_minutes?: number | null;
}

export interface SyncResult {
  pulled: number;
  triaged: number;
  failed: number;
  error: string | null;
}

/** Raw GET /tickets/:id payload before UI adaptation. */
interface TicketDetailRaw {
  ticket: TicketRow;
  runs?: Array<{
    id: string;
    ticket_id: string;
    decision_json?: Partial<TriageDecision> | Record<string, unknown>;
    model?: string;
    tier?: string;
    tokens?: number;
    cost_usd?: number;
    latency_ms?: number;
    trace_id?: string;
    guardrails_fired?: { type: string; detail?: string }[];
    created_at?: string;
  }>;
  // Mock / richer shapes may already be flattened:
  body_masked?: string;
  decision?: TriageDecision | null;
  guardrails_fired?: { type: string; detail?: string }[];
  model?: string;
  tier?: string;
  latency_ms?: number;
  total_tokens?: number;
  cost_usd?: number;
  trace_id?: string;
}

interface CreateTicketRaw {
  ticket: TicketRow;
  decision?: TriageDecision | null;
  blocked?: boolean;
  blocked_reason?: string;
  guardrails_fired?: { type: string; detail?: string }[];
}

function decisionFromJson(
  ticket: TicketRow,
  raw: Partial<TriageDecision> | Record<string, unknown> | null | undefined
): TriageDecision | null {
  if (!raw || typeof raw !== "object") return null;
  // Empty {} from a failed sync must not win over an older successful run.
  if (!Object.keys(raw).length) return null;
  const severity =
    normalizeSeverity(String(raw.severity ?? "")) ||
    normalizeSeverity(ticket.severity) ||
    undefined;
  const team = (raw.assigned_team as Team | undefined) || (ticket.assigned_team as Team) || undefined;
  if (!severity || !team) {
    // Ticket may still carry fields when decision_json is thin.
    if (!normalizeSeverity(ticket.severity) || !ticket.assigned_team) return null;
  }
  const rationale = String(raw.rationale ?? "").trim();
  const hasSubstance =
    rationale.length > 0 ||
    Array.isArray(raw.evidence) && raw.evidence.length > 0 ||
    Boolean(raw.category) ||
    Boolean(raw.suggested_first_action);
  // Prefer falling through to an older run when this payload is only defaults.
  if (!hasSubstance && !raw.severity && !raw.assigned_team) return null;
  return {
    ticket_id: String(raw.ticket_id ?? ticket.id),
    category: String(raw.category ?? ticket.category ?? ""),
    subcategory: String(raw.subcategory ?? ticket.subcategory ?? ""),
    severity: (severity || normalizeSeverity(ticket.severity)) as Severity,
    priority_score: Number(raw.priority_score ?? ticket.priority_score ?? 0),
    assigned_team: (team || ticket.assigned_team) as Team,
    sla_target_mins: Number(raw.sla_target_mins ?? ticket.sla_target_mins ?? 0),
    confidence: Number(raw.confidence ?? ticket.confidence ?? 0),
    rationale: String(raw.rationale ?? ""),
    evidence: Array.isArray(raw.evidence) ? (raw.evidence as Citation[]) : [],
    duplicate_of: (raw.duplicate_of as string | null | undefined) ?? null,
    suggested_first_action: String(raw.suggested_first_action ?? ""),
    needs_human: Boolean(raw.needs_human ?? ticket.needs_human),
    escalation_reason: String(raw.escalation_reason ?? ""),
  };
}

function decisionFromTicket(ticket: TicketRow): TriageDecision | null {
  const severity = normalizeSeverity(ticket.severity);
  if (!severity || !ticket.assigned_team) return null;
  return {
    ticket_id: ticket.id,
    category: ticket.category || "",
    subcategory: ticket.subcategory || "",
    severity,
    priority_score: ticket.priority_score ?? 0,
    assigned_team: ticket.assigned_team as Team,
    sla_target_mins: ticket.sla_target_mins ?? 0,
    confidence: ticket.confidence ?? 0,
    rationale: "",
    evidence: [],
    duplicate_of: null,
    suggested_first_action: "",
    needs_human: ticket.needs_human,
    escalation_reason: "",
  };
}

/** Adapt live `{ ticket, runs }` (or mock flat detail) into TicketDetail. */
export function adaptTicketDetail(raw: TicketDetailRaw): TicketDetail {
  const ticket = {
    ...raw.ticket,
    severity: normalizeSeverity(raw.ticket.severity) || raw.ticket.severity,
  };
  const runs = raw.runs ?? [];
  // Newest run first; skip empty failed syncs so the drawer keeps the last real decision.
  let chosenRun = runs[0];
  let decision =
    raw.decision ??
    (chosenRun ? decisionFromJson(ticket, chosenRun.decision_json) : null);
  if (!decision) {
    for (const run of runs) {
      const parsed = decisionFromJson(ticket, run.decision_json);
      if (parsed) {
        chosenRun = run;
        decision = parsed;
        break;
      }
    }
  }
  decision = decision ?? decisionFromTicket(ticket);
  return {
    ticket,
    body_masked: raw.body_masked ?? ticket.body_masked ?? "",
    decision,
    guardrails_fired: raw.guardrails_fired ?? chosenRun?.guardrails_fired ?? [],
    model: raw.model ?? chosenRun?.model ?? "",
    tier: (raw.tier as TicketDetail["tier"]) ?? (chosenRun?.tier as TicketDetail["tier"]) ?? "standard",
    latency_ms: raw.latency_ms ?? chosenRun?.latency_ms ?? 0,
    total_tokens: raw.total_tokens ?? chosenRun?.tokens ?? 0,
    cost_usd: raw.cost_usd ?? chosenRun?.cost_usd ?? 0,
    trace_id: raw.trace_id ?? chosenRun?.trace_id ?? "",
  };
}

/** Adapt POST /tickets create payload into TriageRunResult (empty graph nodes). */
export function adaptCreateResult(raw: CreateTicketRaw): TriageRunResult {
  const ticket = raw.ticket;
  const decision =
    raw.decision ??
    (raw.blocked ? null : decisionFromTicket(ticket));
  return {
    ticket,
    decision,
    nodes: [],
    retries: 0,
    total_ms: 0,
    total_tokens: 0,
    cost_usd: 0,
  };
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
  /** Null when a guardrail blocked the run before the model was called. */
  decision: TriageDecision | null;
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

  /**
   * Optional extras. §9.7 asks for a category-mix chart, a tokens-today tile and a
   * recent-overrides table; §6.1 does not type them yet. They are optional so the
   * screen degrades to "—" rather than breaking the day the backend lands, and no
   * total is ever computed in the browser from a partial page of rows.
   */
  by_category?: { category: string; count: number }[];
  tokens_today?: number;
  /** Predicted vs. labelled severity, for the confusion matrix on Evaluations. */
  severity_confusion?: { predicted: Severity; actual: Severity; count: number }[];
  recent_overrides?: {
    ticket_id: string;
    external_id: string;
    title: string;
    field: string;
    from: string;
    to: string;
    by: string;
    reason: string;
    at: string;
  }[];
}

/** Date range on History rides alongside the standard list contract. */
export interface TicketListParams extends ListParams {
  from?: string;
  to?: string;
}

// --- endpoints --------------------------------------------------------------

export const api = {
  health: () => get<any>("/health"),

  login: (username: string, password: string) =>
    post<{ token: string; user: User }>("/auth/login", { username, password }),
  me: () => get<User>("/auth/me"),

  // Full pipeline, multi-session. Used by the Assistant page.
  chat: (message: string, sessionId?: string, filters?: Record<string, string>) =>
    post<ChatResponse>("/chat", { message, session_id: sessionId, filters }),

  // Knowledge-base widget. Single server-pinned session — no session_id to manage.
  chatbot: (message: string) => post<ChatResponse>("/chatbot", { message }),
  chatbotHistory: () => get<any[]>("/chatbot/history"),
  resetChatbot: () => del("/chatbot/history"),

  sessions: (params?: ListParams) => list<any>("/sessions", params),
  messages: (sessionId: string, params?: ListParams) =>
    list<any>(`/sessions/${sessionId}/messages`, params),
  deleteSession: (id: string) => del(`/sessions/${id}`),

  documents: (params?: ListParams) => list<DocumentRow>("/documents", params),
  deleteDocument: (id: string) => del(`/documents/${id}`),
  uploadDocument: (file: File, allowedRoles: string[], sensitivity: string) => {
    const body = new FormData();
    body.append("file", file);
    body.append("allowed_roles", allowedRoles.join(","));
    body.append("sensitivity", sensitivity);
    return request<any>("/documents/upload", { method: "POST", body });
  },

  search: (
    query: string,
    options?: {
      top_k?: number;
      decompose?: boolean;
      exclude_external_id?: string;
      exclude_ticket_id?: string;
      filters?: Record<string, string>;
    }
  ) => post<RetrievedChunk[]>("/search", { query, ...options }),

  feedback: (messageId: string, rating: 1 | -1, comment = "") =>
    post("/feedback", { message_id: messageId, rating, comment }),
  feedbackQueue: (params?: ListParams) => list<any>("/feedback", params),
  reviewFeedback: (id: string, correctedAnswer?: string) =>
    patch(`/feedback/${id}/review`, { corrected_answer: correctedAnswer }),

  usage: () => get<any>("/analytics/usage"),
  traces: (params?: ListParams) => list<any>("/analytics/traces", params),
  messageMetrics: () => get<any[]>("/analytics/messages"),

  runEvals: () => post<any>("/evals/run"),
  evals: (params?: ListParams) => list<any>("/evals", params),

  // --- triage ---------------------------------------------------------------

  tickets: (params?: TicketListParams) => list<TicketRow>("/tickets", params),
  ticket: async (id: string) => {
    const { data, meta } = await get<TicketDetailRaw>(`/tickets/${id}`);
    return { data: adaptTicketDetail(data), meta };
  },
  ticketTimeline: async (id: string) => {
    try {
      return await get<TimelineEvent[]>(`/tickets/${id}/timeline`);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.code === "not_found")) {
        return { data: [] as TimelineEvent[], meta: {} };
      }
      throw err;
    }
  },

  createTicket: async (input: {
    title: string;
    /** Preferred — matches TicketIngestRequest.body */
    body?: string;
    /** @deprecated use body; kept so older form callers still compile */
    description?: string;
    application?: string;
    environment?: string;
  }) => {
    const payload = {
      title: input.title,
      body: input.body ?? input.description ?? "",
      application: input.application ?? "",
      environment: input.environment ?? "prod",
      source: "manual" as const,
      channel: "ui",
    };
    const { data, meta } = await post<CreateTicketRaw | TriageRunResult>("/tickets", payload);
    // Mock returns TriageRunResult already; live returns { ticket, decision, … }.
    if (data && "nodes" in data && Array.isArray((data as TriageRunResult).nodes)) {
      return { data: data as TriageRunResult, meta };
    }
    return { data: adaptCreateResult(data as CreateTicketRaw), meta };
  },

  bulkTriage: (count: number) =>
    post<{ processed: number; total_ms: number; results: TriageRunResult[] }>("/tickets/bulk", {
      count,
    }),

  retriage: async (id: string) => {
    try {
      return await post<TriageRunResult>(`/tickets/${id}/retriage`);
    } catch (err) {
      if (
        err instanceof ApiError &&
        (err.status === 404 || err.status === 405 || err.code === "not_found" || err.code === "method_not_allowed")
      ) {
        throw new ApiError(
          "not_implemented",
          "Re-triage is not available on this backend yet. Use Sync Now or submit a new ticket.",
          501
        );
      }
      throw err;
    }
  },

  override: (id: string, body: { field: string; new_value: string; reason: string }) =>
    patch<TicketRow>(`/tickets/${id}/override`, body),

  approve: (id: string) => post<TicketRow>(`/tickets/${id}/approve`),

  /** Admin-only. Backs the chat "Bulk approve & route" button. */
  bulkApprove: (ticketIds: string[]) =>
    post<BulkApproveResult[]>("/tickets/bulk-approve", { ticket_ids: ticketIds }),

  recalculateConfidence: () =>
    post<{ updated: number; failed: number; errors: { ticket_id: string; error: string }[] }>(
      "/analytics/recalculate-confidence"
    ),

  teamQueue: (params?: TicketListParams) => list<TicketRow>("/teams/queue", params),

  triageAnalytics: () => get<TriageAnalytics>("/analytics/triage"),

  transcribe: (blob: Blob) => {
    const body = new FormData();
    body.append("audio", blob, "speech.webm");
    return request<{ text: string }>("/voice/transcribe", { method: "POST", body });
  },

  syncNow: async () => {
    const { data, meta } = await post<SyncResult>("/integrations/sync");
    return {
      data: {
        pulled: data?.pulled ?? 0,
        triaged: data?.triaged ?? 0,
        failed: data?.failed ?? 0,
        error: data?.error ?? null,
        watermark: meta?.watermark ?? null,
      },
      meta,
    };
  },

  audit: (params?: ListParams) => list<any>("/audit", params),
  verifyAudit: () => get<{ valid: boolean; entries: number; broken_at: number | null }>("/audit/verify"),
};
