function resolveApiBase(): string {
  // Prefer explicit Vite env var (build-time)
  const fromEnv = String((import.meta as any)?.env?.VITE_API_BASE || "").trim();
  if (fromEnv) return fromEnv.replace(/\/+$/, "");

  // Runtime heuristic: when frontend dev server runs on :3000, backend is usually on :8765
  if (typeof window !== "undefined") {
    const { protocol, hostname, port } = window.location;
    if (port === "3000") {
      return `${protocol}//${hostname}:8765`;
    }
  }
  return "";
}

const BASE = resolveApiBase();

export type ApiOk<T> = { status: "success"; data: T; message?: string };
export type ApiErr = { status: "error"; message: string; data?: unknown };

export async function apiJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  const text = await r.text();
  let j: unknown;
  try {
    j = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(`非 JSON 响应 HTTP ${r.status}：${text.slice(0, 160)}`);
  }
  if (!j || typeof j !== "object") {
    throw new Error(`空响应 HTTP ${r.status}`);
  }
  const body = j as Record<string, unknown>;
  // 后端 err() 或业务错误
  if (body.status === "error") {
    throw new Error(String(body.message || "request failed"));
  }
  // FastAPI HTTPException / 未注册路由 等
  if (!r.ok) {
    const detail = body.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: string }).msg) : String(d))).join("; ")
          : `HTTP ${r.status}`;
    throw new Error(msg);
  }
  if (body.status === "success" && "data" in body) {
    return body.data as T;
  }
  // Some endpoints return plain JSON objects without a status wrapper — return as-is
  if (!("status" in body)) {
    return body as unknown as T;
  }
  throw new Error(`Unexpected API shape HTTP ${r.status}`);
}

async function consumeSseFromResponse(
  response: Response,
  onEvent: (ev: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("empty response body");
  }
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    if (signal?.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = block.trim();
      if (!line.startsWith("data: ")) {
        continue;
      }
      let obj: Record<string, unknown>;
      try {
        obj = JSON.parse(line.slice(6)) as Record<string, unknown>;
      } catch {
        continue;
      }
      if (obj.type === "error") {
        throw new Error(String(obj.message ?? "stream error"));
      }
      onEvent(obj);
    }
  }
}

export type AnalyzeStreamPresetFields = {
  review_role?: string | null;
  review_goals_principles?: string | null;
  output_requirements?: string | null;
  /** 记忆召回查询；不传时后端用关注点拼接作为查询 */
  memory_query?: string | null;
};

export async function getConversationDetail(
  projectId: number,
  conversationId: number,
): Promise<{
  id: number;
  analysis_type: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  /** 与审查技能包预设（focus_presets[].id）对应；旧会话可能为空 */
  preset_id?: string | null;
  has_analysis_run: boolean;
  /** 最近一次 analyze 写入的关注点名称列表；与当前预设比对可判断是否需重新全文审查 */
  last_analysis_focus_points?: string[] | null;
}> {
  return apiJson(`/api/v1/projects/${projectId}/conversations/${conversationId}`);
}

export async function getPresetHistory(
  projectId: number,
  presetId: string,
): Promise<{
  has_reviewed_history: boolean;
  latest_conversation: { id: number; title: string; updated_at?: string } | null;
}> {
  const q = encodeURIComponent(presetId);
  return apiJson(`/api/v1/projects/${projectId}/conversations/preset-history?preset_id=${q}`);
}

export async function getProjectIngestStatus(projectId: number): Promise<{
  project_id: number;
  chunk_count: number;
  initialized: boolean;
  has_review_records: boolean;
}> {
  return apiJson(`/api/v1/projects/${projectId}/ingest-status`);
}

export async function postAnalyzeConversationStream(
  projectId: number,
  conversationId: number,
  body: { chunk_limit: number; focus_points: string[]; incremental_user_notes?: string | null } & AnalyzeStreamPresetFields,
  onEvent: (ev: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${BASE}/api/v1/projects/${projectId}/conversations/${conversationId}/analyze/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) {
    const j = (await r.json().catch(() => ({}))) as ApiErr;
    throw new Error(j.message || `HTTP ${r.status}`);
  }
  await consumeSseFromResponse(r, onEvent, signal);
}

export async function postFollowupConversationStream(
  projectId: number,
  conversationId: number,
  body: { question: string },
  onEvent: (ev: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${BASE}/api/v1/projects/${projectId}/conversations/${conversationId}/followup/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) {
    const j = (await r.json().catch(() => ({}))) as ApiErr;
    throw new Error(j.message || `HTTP ${r.status}`);
  }
  await consumeSseFromResponse(r, onEvent, signal);
}

export async function postAgentConversationStream(
  projectId: number,
  conversationId: number,
  body: { message: string },
  onEvent: (ev: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(
    `${BASE}/api/v1/projects/${projectId}/conversations/${conversationId}/agent/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    },
  );
  if (!r.ok) {
    const j = (await r.json().catch(() => ({}))) as ApiErr;
    throw new Error(j.message || `HTTP ${r.status}`);
  }
  await consumeSseFromResponse(r, onEvent, signal);
}

export type ConversationOutputsIndexItem = {
  id: number;
  conversation_id: number;
  kind: string;
  created_at: string;
  final_download_path: string;
  milestones_download_path: string;
  fragments_index_download_path: string | null;
};

export async function getConversationOutputsIndex(
  projectId: number,
  conversationId: number,
  limit: number = 50,
): Promise<{ items: ConversationOutputsIndexItem[] }> {
  return apiJson(
    `/api/v1/projects/${projectId}/conversations/${conversationId}/outputs-index?limit=${encodeURIComponent(String(limit))}`,
  );
}

export async function getConversationMessages(
  projectId: number,
  conversationId: number,
  limit: number = 200,
): Promise<{ messages: Array<{ id: number; role: string; content: string; created_at?: string }> }> {
  return apiJson(
    `/api/v1/projects/${projectId}/conversations/${conversationId}/messages?limit=${encodeURIComponent(String(limit))}`,
  );
}

export async function deleteConversation(
  projectId: number,
  conversationId: number,
): Promise<{ deleted: boolean }> {
  return apiJson(`/api/v1/projects/${projectId}/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

export async function patchConversation(
  conversationId: number,
  data: { title?: string; starred?: boolean },
): Promise<void> {
  await apiJson(`/api/v1/conversations/${conversationId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteProject(projectId: number): Promise<{ deleted: boolean }> {
  return apiJson(`/api/v1/projects/${projectId}`, {
    method: "DELETE",
  });
}

export async function fetchTextFile(downloadPath: string): Promise<string> {
  const r = await fetch(`${BASE}${downloadPath}`);
  if (!r.ok) {
    throw new Error(`HTTP ${r.status}`);
  }
  return await r.text();
}

export type GlobalConversationItem = {
  id: number;
  project_id: number;
  project_name: string;
  analysis_type: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  preset_id?: string | null;
  project_exists: boolean;
  project_available: boolean;
  starred?: boolean;
};

export async function getConversationsGlobal(opts?: {
  limit?: number;
  offset?: number;
  q?: string;
}): Promise<{ conversations: GlobalConversationItem[] }> {
  const limit = opts?.limit ?? 50;
  const offset = opts?.offset ?? 0;
  const q = (opts?.q ?? "").trim();
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  qs.set("offset", String(offset));
  if (q) qs.set("q", q);
  return apiJson(`/api/v1/conversations?${qs.toString()}`);
}

export async function getConversationsByPair(
  projectId: number,
  presetId: string,
): Promise<{
  count: number;
  conversations: Array<{
    id: number;
    project_id: number;
    analysis_type: string;
    title: string;
    created_at?: string;
    updated_at?: string;
    preset_id?: string | null;
  }>;
}> {
  const qs = new URLSearchParams();
  qs.set("project_id", String(projectId));
  qs.set("preset_id", presetId);
  return apiJson(`/api/v1/conversations/by-pair?${qs.toString()}`);
}

// ── Extraction module ──────────────────────────────────────────────────────

export type ExpertProfileData = { domains: string[]; background: string; updated_at?: string };
export type ReviewQueueItem = {
  id: string; focus_id: string; suggestion: string; status: string;
  occurrences: number; source_role: string; source_type: string;
  project_id?: string | null; conversation_id?: number | null; created_at: string;
};
export type PendingRuleItem = {
  id: string; extraction_focus_id: string; title: string; content: string;
  confidence: string; status: string; source_role: string; source_type: string;
  has_conflicts: boolean; conflict_with: Array<{focus_id: string; reason: string}>;
  scope_note?: string; created_at: string;
};

export async function getExpertProfile(): Promise<ExpertProfileData> {
  return apiJson("/api/v1/expert-profile");
}
export async function putExpertProfile(data: Partial<ExpertProfileData>): Promise<ExpertProfileData> {
  return apiJson("/api/v1/expert-profile", { method: "PUT", body: JSON.stringify(data) });
}
export async function getReviewQueue(opts?: { projectId?: number | null }): Promise<{ items: ReviewQueueItem[]; total: number }> {
  const qs = new URLSearchParams();
  if (opts?.projectId != null) qs.set("project_id", String(opts.projectId));
  const q = qs.toString();
  return apiJson(`/api/v1/review-queue${q ? `?${q}` : ""}`);
}
export async function patchReviewQueueItem(id: string, data: { status: string }): Promise<ReviewQueueItem> {
  return apiJson(`/api/v1/review-queue/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(data) });
}
export async function deleteReviewQueueItem(id: string): Promise<{ deleted: boolean }> {
  return apiJson(`/api/v1/review-queue/${encodeURIComponent(id)}`, { method: "DELETE" });
}
export async function getPendingRules(): Promise<{ items: PendingRuleItem[]; total: number }> {
  return apiJson("/api/v1/pending-rules");
}
export async function approvePendingRule(kid: string, body: { note?: string }): Promise<{ approved: string; written_to?: string }> {
  return apiJson(`/api/v1/pending-rules/${encodeURIComponent(kid)}/approve`, { method: "POST", body: JSON.stringify(body) });
}
export async function rejectPendingRule(kid: string, body: { reason: string }): Promise<{ rejected: string }> {
  return apiJson(`/api/v1/pending-rules/${encodeURIComponent(kid)}/reject`, { method: "POST", body: JSON.stringify(body) });
}

export type KnowledgeItem = {
  id: string; extraction_focus_id: string; title: string; content: string;
  confidence: string; status: string; source_role: string; source_type: string;
  scope_note?: string | null; has_conflicts?: boolean; created_at?: string;
};
export async function getKnowledgeItems(opts?: { status?: string; limit?: number }): Promise<{ items: KnowledgeItem[]; total: number }> {
  const qs = new URLSearchParams();
  if (opts?.status) qs.set("status", opts.status);
  if (opts?.limit) qs.set("limit", String(opts.limit));
  return apiJson(`/api/v1/knowledge-items?${qs.toString()}`);
}
export async function patchKnowledgeItem(kid: string, data: { status?: string; title?: string; content?: string; scope_note?: string }): Promise<KnowledgeItem> {
  return apiJson(`/api/v1/knowledge-items/${encodeURIComponent(kid)}`, { method: "PATCH", body: JSON.stringify(data) });
}
export async function submitKnowledgeItem(kid: string): Promise<{ submitted: string; status: string }> {
  return apiJson(`/api/v1/knowledge-items/${encodeURIComponent(kid)}/submit`, { method: "POST" });
}

export async function uploadExtractionMaterial(
  file: File,
  title?: string,
): Promise<{ material_id: string; original_name: string; size_bytes: number; path: string }> {
  const fd = new FormData();
  fd.append("file", file);
  if (title) fd.append("title", title);
  const r = await fetch(`${BASE}/api/v1/extraction/upload-material`, { method: "POST", body: fd });
  const text = await r.text();
  let j: Record<string, unknown>;
  try { j = JSON.parse(text); } catch { throw new Error(`Upload failed HTTP ${r.status}: ${text.slice(0, 120)}`); }
  if ((j as any).status === "error") throw new Error(String((j as any).message || "upload error"));
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (j as any).data;
}

export async function postActiveExtractionStream(
  body: { user_input: string; strategy: string; review_queue_item_id?: string | null; prior_messages?: Array<{role: string; content: string}>; round_number?: number },
  onEvent: (ev: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${BASE}/api/v1/extraction/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) {
    const j = (await r.json().catch(() => ({}))) as ApiErr;
    throw new Error(j.message || `HTTP ${r.status}`);
  }
  await consumeSseFromResponse(r, onEvent, signal);
}

export async function postDocExtractionStream(
  body: { material_id: string; user_input?: string; strategy?: string; prior_messages?: Array<{role: string; content: string}> },
  onEvent: (ev: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${BASE}/api/v1/extraction/doc-stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) {
    const j = (await r.json().catch(() => ({}))) as ApiErr;
    throw new Error(j.message || `HTTP ${r.status}`);
  }
  await consumeSseFromResponse(r, onEvent, signal);
}

export async function postReviewExtractionStream(
  projectId: number,
  conversationId: number,
  body: { user_input: string; prior_messages?: Array<{role: string; content: string}>; findings_summary?: Array<Record<string, unknown>> },
  onEvent: (ev: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(
    `${BASE}/api/v1/projects/${projectId}/conversations/${conversationId}/post-review-extraction/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    },
  );
  if (!r.ok) {
    const j = (await r.json().catch(() => ({}))) as ApiErr;
    throw new Error(j.message || `HTTP ${r.status}`);
  }
  await consumeSseFromResponse(r, onEvent, signal);
}

// ── Auth & session-based extraction (legacy, used by App.tsx) ─────────────

export type AuthUser = { user_id: number; username: string; display_name: string; profile_completed: boolean };
export type ExpertProfile = {
  industries: string[]; production_modes: string[]; functional_modules: string[];
  focus_areas: string[]; profile_completed: boolean;
};
export type KnowledgeCard = {
  id: number; conversation_id: number; card_index: number; card_type: string;
  title: string; content: string; applicable_scope: string | null;
  exceptions: string | null; confidence: string; status: string;
  source_turn: number | null; created_at: string; updated_at: string;
};
export type LegacyExtractionSession = {
  session_id: number; id?: number; title: string; created_at: string; card_count: number;
  confirmed_cards?: number; total_cards?: number;
};

export async function authLogin(username: string, password: string): Promise<AuthUser> {
  return apiJson("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
}
export async function authLogout(): Promise<void> {
  await apiJson("/api/v1/auth/logout", { method: "POST" });
}
export async function authMe(): Promise<AuthUser> {
  return apiJson("/api/v1/auth/me");
}

export async function createLegacyExtractionSession(body?: { title?: string; focus_label?: string }): Promise<{ session_id: number; opening: string; profile_completed: boolean }> {
  return apiJson("/api/v1/extraction/sessions", { method: "POST", body: JSON.stringify(body ?? {}) });
}
export async function listLegacyExtractionSessions(): Promise<{ sessions: LegacyExtractionSession[] }> {
  return apiJson("/api/v1/extraction/sessions");
}
export async function getLegacyExtractionSession(sessionId: number): Promise<{ session_id: number; messages: Array<{role: string; content: string}>; cards: KnowledgeCard[] }> {
  return apiJson(`/api/v1/extraction/sessions/${sessionId}`);
}
export async function postExtractionChatStream(
  sessionId: number,
  body: string | { message: string },
  onEvent: (ev: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const payload = typeof body === "string" ? { message: body } : body;
  const r = await fetch(`${BASE}/api/v1/extraction/sessions/${sessionId}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
    signal,
  });
  if (!r.ok) {
    const j = (await r.json().catch(() => ({}))) as ApiErr;
    throw new Error(j.message || `HTTP ${r.status}`);
  }
  await consumeSseFromResponse(r, onEvent, signal);
}
export async function confirmExtractionCard(sessionId: number, cardId: number): Promise<{ card: KnowledgeCard }> {
  return apiJson(`/api/v1/extraction/sessions/${sessionId}/cards/${cardId}/confirm`, { method: "POST" });
}
export async function rejectExtractionCard(sessionId: number, cardId: number): Promise<{ card: KnowledgeCard }> {
  return apiJson(`/api/v1/extraction/sessions/${sessionId}/cards/${cardId}/reject`, { method: "POST" });
}
export async function updateExtractionCard(
  sessionId: number,
  cardId: number,
  updates: Partial<Pick<KnowledgeCard, "card_type" | "title" | "content" | "applicable_scope" | "exceptions" | "confidence">>,
): Promise<{ card: KnowledgeCard }> {
  return apiJson(`/api/v1/extraction/sessions/${sessionId}/cards/${cardId}`, {
    method: "PUT",
    body: JSON.stringify(updates),
  });
}
export async function endExtractionSession(sessionId: number): Promise<{
  session_id: number; filename: string;
  summary: { confirmed: number; edited: number; rejected: number; pending: number; total: number };
}> {
  return apiJson(`/api/v1/extraction/sessions/${sessionId}/end`, { method: "POST" });
}
export async function uploadExtractionDocument(
  sessionId: number,
  file: File,
): Promise<{ filename: string; char_count: number; preview: string }> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`${BASE}/api/v1/extraction/sessions/${sessionId}/upload`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  const j = (await r.json()) as { status: string; data?: unknown; message?: string };
  if (!r.ok || j.status === "error") throw new Error(String(j.message || `HTTP ${r.status}`));
  return j.data as { filename: string; char_count: number; preview: string };
}

// ── Obsidian Vaults ───────────────────────────────────────────────────────

export type ObsidianVault = {
  id: number;
  path: string;
  name: string;
  /** "project" | "knowledge" | "both" */
  role: string;
  frontmatter_filter?: Record<string, unknown> | null;
  output_folder: string;
  created_at: string;
  updated_at: string;
};

export type DiscoveredVault = {
  path: string;
  name: string;
  already_registered: boolean;
};

export async function listVaults(): Promise<{ vaults: ObsidianVault[] }> {
  return apiJson("/api/v1/vaults");
}

export async function discoverVaults(): Promise<{ vaults: DiscoveredVault[] }> {
  return apiJson("/api/v1/vaults/discover");
}

export async function registerVault(data: {
  path: string;
  name?: string;
  role?: string;
  frontmatter_filter?: Record<string, unknown> | null;
  output_folder?: string;
}): Promise<ObsidianVault> {
  return apiJson("/api/v1/vaults", { method: "POST", body: JSON.stringify(data) });
}

export async function deleteVault(vaultId: number): Promise<{ deleted: boolean }> {
  return apiJson(`/api/v1/vaults/${vaultId}`, { method: "DELETE" });
}

export async function updateVault(
  vaultId: number,
  data: Partial<Pick<ObsidianVault, "name" | "role" | "frontmatter_filter" | "output_folder">>,
): Promise<ObsidianVault> {
  return apiJson(`/api/v1/vaults/${vaultId}`, { method: "PATCH", body: JSON.stringify(data) });
}

export async function exportConversationToObsidian(
  projectId: number,
  conversationId: number,
  body: { vault_id: number; content?: string; focus_point_ids?: string[] },
): Promise<{ note_path: string; vault_id: number }> {
  return apiJson(
    `/api/v1/projects/${projectId}/conversations/${conversationId}/export/obsidian`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

// ── Extraction Sessions ──────────────────────────────────────────────────────

export interface ExtractionSession {
  id: number;
  title: string;
  strategy: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  starred: boolean;
}

export const listExtractionSessions = () =>
  apiJson<{ sessions: ExtractionSession[] }>("/api/v1/extraction/sessions");

export const createExtractionSession = (title: string, strategy?: string | null) =>
  apiJson<ExtractionSession>("/api/v1/extraction/sessions", {
    method: "POST",
    body: JSON.stringify({ title, strategy: strategy ?? null }),
  });

export const getExtractionSessionMessages = (sid: number) =>
  apiJson<{ messages: Array<{ role: string; content: string; created_at: string }> }>(
    `/api/v1/extraction/sessions/${sid}/messages`,
  );

export const deleteExtractionSession = (sid: number) =>
  apiJson<{ ok: boolean }>(`/api/v1/extraction/sessions/${sid}`, { method: "DELETE" });

export const patchExtractionSession = (
  sid: number,
  data: { title?: string; starred?: boolean },
) =>
  apiJson<{ ok: boolean }>(`/api/v1/extraction/sessions/${sid}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const generateExtractionSessionTitle = (
  sid: number,
  messages: Array<{ role: string; content: string }>,
) =>
  apiJson<{ title: string }>(`/api/v1/extraction/sessions/${sid}/generate-title`, {
    method: "POST",
    body: JSON.stringify({ messages }),
  });

export const appendExtractionMessages = (
  sid: number,
  messages: Array<{ role: string; content: string }>,
) =>
  apiJson<{ ok: boolean }>(`/api/v1/extraction/sessions/${sid}/messages`, {
    method: "POST",
    body: JSON.stringify({ messages }),
  });

export async function addToReviewQueue(params: {
  focus_id: string;
  suggestion: string;
  source_type?: string;
  project_id?: number | null;
  conversation_id?: number | null;
}): Promise<void> {
  await apiJson("/api/v1/review-queue", { method: "POST", body: JSON.stringify(params) });
}
