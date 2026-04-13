import { useEffect, useMemo, useState } from "react";

import { fetchTextFile, getConversationOutputsIndex } from "../api";

export type ReplayOutputEntry = {
  id: string;
  convId: number;
  kind: string;
  createdAt: string;
  markdown: string;
};

export type ReplayMilestonesResult = {
  events: Array<
    | { type: "stage"; stage: string; status: string; detail?: string }
    | { type: "chunk_index"; markdown: string; index_file_path?: string | null }
    | { type: "error"; message: string }
    | { type: string; [k: string]: unknown }
  >;
  rawText: string;
};

function parseJsonlFencedBlock(text: string): string[] {
  const m = text.match(/```jsonl\s*\n([\s\S]*?)\n```/i);
  const body = (m?.[1] || "").trim();
  if (!body) return [];
  return body
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
}

export function useConversationReplay(projectId: number | null, conversationId: number | null) {
  const [entries, setEntries] = useState<ReplayOutputEntry[]>([]);
  const [milestones, setMilestones] = useState<ReplayMilestonesResult | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const key = useMemo(() => `${projectId ?? ""}:${conversationId ?? ""}`, [projectId, conversationId]);

  useEffect(() => {
    let alive = true;
    setError(null);
    setEntries([]);
    setMilestones(null);
    (async () => {
      if (projectId == null || conversationId == null) return;
      try {
        const idx = await getConversationOutputsIndex(projectId, conversationId, 50);
        const items = Array.isArray(idx.items) ? idx.items : [];
        const rebuilt: ReplayOutputEntry[] = [];
        for (const it of [...items].reverse()) {
          if (!alive) return;
          const md = await fetchTextFile(it.final_download_path);
          rebuilt.push({
            id: `replay-${it.id}`,
            convId: conversationId,
            kind: it.kind,
            createdAt: it.created_at,
            markdown: md,
          });
        }
        if (!alive) return;
        setEntries(rebuilt);

        const latest = items[0];
        if (latest?.milestones_download_path) {
          const raw = await fetchTextFile(String(latest.milestones_download_path));
          if (!alive) return;
          const lines = parseJsonlFencedBlock(raw);
          const events: ReplayMilestonesResult["events"] = [];
          for (const line of lines) {
            try {
              const obj = JSON.parse(line) as any;
              events.push(obj);
            } catch {
              // ignore malformed line
            }
          }
          setMilestones({ events, rawText: raw });
        }
      } catch (e) {
        if (!alive) return;
        const err = e instanceof Error ? e : new Error(String(e));
        setError(err);
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { entries, milestones, error };
}

