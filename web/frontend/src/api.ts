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
  throw new Error(`Unexpected API shape HTTP ${r.status}`);
}

export function openConvertStream(
  projectId: number,
  onEvent: (ev: Record<string, unknown>) => void,
  onError: (e: Error) => void,
): () => void {
  const url = `${BASE}/api/v1/projects/${projectId}/convert-md/stream`;
  const es = new EventSource(url);
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data) as Record<string, unknown>);
    } catch {
      onEvent({ type: "parse_error", raw: e.data });
    }
  };
  es.onerror = () => {
    onError(new Error("EventSource error"));
    es.close();
  };
  return () => es.close();
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
  md_out: string;
  md_out_exists: boolean;
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

export function waitConvertStream(
  projectId: number,
  onLogLine: (line: string) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const stop = openConvertStream(
      projectId,
      (ev) => {
        if (ev.type === "log" && typeof ev.text === "string") {
          onLogLine(ev.text + "\n");
        }
        if (ev.type === "complete") {
          stop();
          resolve();
        }
        if (ev.type === "error") {
          stop();
          reject(new Error(String(ev.message)));
        }
      },
      (e) => {
        stop();
        reject(e);
      },
    );
    setTimeout(() => {
      stop();
      reject(new Error("docs2md 转换超时"));
    }, 600_000);
  });
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
export async function getReviewQueue(): Promise<{ items: ReviewQueueItem[]; total: number }> {
  return apiJson("/api/v1/review-queue");
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

export async function postExpertInterviewStream(
  body: { user_input: string; prior_messages?: Array<{role: string; content: string}>; rq_topics?: string[] },
  onEvent: (ev: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${BASE}/api/v1/expert-interview/stream`, {
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
