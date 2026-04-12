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
};

export async function postAnalyzeStream(
  projectId: number,
  body: { chunk_limit: number; focus_points: string[] } & AnalyzeStreamPresetFields,
  onEvent: (ev: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${BASE}/api/v1/projects/${projectId}/analyze/stream`, {
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

export async function getConversationDetail(
  projectId: number,
  conversationId: number,
): Promise<{
  id: number;
  analysis_type: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  /** 与 rules 中 focus_presets[].id 对应；旧会话可能为空 */
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
