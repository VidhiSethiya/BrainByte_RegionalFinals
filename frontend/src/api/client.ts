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

  audit: (params?: ListParams) => list<any>("/audit", params),
  verifyAudit: () => get<{ valid: boolean; entries: number; broken_at: number | null }>("/audit/verify"),
};
