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
      if (!location.pathname.startsWith("/login")) location.href = "/login";
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

  search: (query: string, options?: { top_k?: number; decompose?: boolean }) =>
    post<RetrievedChunk[]>("/search", { query, ...options }),

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
  ticket: (id: string) => get<TicketDetail>(`/tickets/${id}`),
  ticketTimeline: (id: string) => get<TimelineEvent[]>(`/tickets/${id}/timeline`),

  createTicket: (body: {
    title: string;
    description: string;
    application?: string;
    environment?: string;
  }) => post<TriageRunResult>("/tickets", body),

  bulkTriage: (count: number) =>
    post<{ processed: number; total_ms: number; results: TriageRunResult[] }>("/tickets/bulk", {
      count,
    }),

  retriage: (id: string) => post<TriageRunResult>(`/tickets/${id}/retriage`),

  override: (id: string, body: { field: string; new_value: string; reason: string }) =>
    patch<TicketRow>(`/tickets/${id}/override`, body),

  approve: (id: string) => post<TicketRow>(`/tickets/${id}/approve`),

  teamQueue: (params?: TicketListParams) => list<TicketRow>("/teams/queue", params),

  triageAnalytics: () => get<TriageAnalytics>("/analytics/triage"),

  transcribe: (blob: Blob) => {
    const body = new FormData();
    body.append("audio", blob, "speech.webm");
    return request<{ text: string }>("/voice/transcribe", { method: "POST", body });
  },

  syncNow: () => post<{ pulled: number; pushed: number; failed: number }>("/integrations/sync"),

  audit: (params?: ListParams) => list<any>("/audit", params),
  verifyAudit: () => get<{ valid: boolean; entries: number; broken_at: number | null }>("/audit/verify"),
};
