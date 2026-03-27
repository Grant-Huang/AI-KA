const BASE = "";

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
  const j = (await r.json()) as ApiOk<T> | ApiErr;
  if ((j as ApiErr).status === "error") {
    throw new Error((j as ApiErr).message || "request failed");
  }
  return (j as ApiOk<T>).data;
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

export async function postAnalyzeStream(
  projectId: number,
  body: { chunk_limit: number; focus_points: string[] },
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
