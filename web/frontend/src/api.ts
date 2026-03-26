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

export function openAnalyzeStream(
  projectId: number,
  chunkLimit: number,
  onEvent: (ev: Record<string, unknown>) => void,
  onError: (e: Error) => void,
): () => void {
  const url = `${BASE}/api/v1/projects/${projectId}/analyze/stream?chunk_limit=${chunkLimit}`;
  const es = new EventSource(url);
  es.onmessage = (e) => {
    try {
      const obj = JSON.parse(e.data) as Record<string, unknown>;
      onEvent(obj);
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
