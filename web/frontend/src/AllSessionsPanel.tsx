import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button, Input, Spin } from "antd";
import { SearchOutlined, StarFilled } from "@ant-design/icons";

export interface AllSessionItem {
  id: number;
  title: string;
  updated_at: string;
  starred?: boolean;
  project_id?: number;
}

interface Props {
  fetchSessions: (opts: { limit: number; offset: number; q: string }) => Promise<{ items: AllSessionItem[]; hasMore: boolean }>;
  onSelect: (item: AllSessionItem) => void;
}

const PAGE_SIZE = 50;

export function AllSessionsPanel({ fetchSessions, onSelect }: Props) {
  const [items, setItems] = useState<AllSessionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (query: string, currentOffset: number, append: boolean) => {
    setLoading(true);
    try {
      const { items: newItems, hasMore: more } = await fetchSessions({ limit: PAGE_SIZE, offset: currentOffset, q: query });
      setItems(prev => append ? [...prev, ...newItems] : newItems);
      setHasMore(more);
      setOffset(currentOffset + newItems.length);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, [fetchSessions]);

  useEffect(() => { void load("", 0, false); }, [load]);

  const handleSearchChange = (val: string) => {
    setQ(val);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => {
      setOffset(0);
      void load(val, 0, false);
    }, 300);
  };

  return (
    <div className="all-sessions-panel">
      <div className="all-sessions-panel__header">所有会话</div>
      <div className="all-sessions-panel__search">
        <Input
          prefix={<SearchOutlined style={{ color: "#aaa" }} />}
          placeholder="搜索会话标题…"
          value={q}
          onChange={(e) => handleSearchChange(e.target.value)}
          allowClear
        />
      </div>
      <div className="all-sessions-panel__list">
        {loading && items.length === 0 ? (
          <div style={{ padding: "48px 0", textAlign: "center" }}><Spin /></div>
        ) : items.length === 0 ? (
          <div style={{ padding: "48px 0", textAlign: "center", color: "#aaa", fontSize: 13 }}>
            {q ? "没有匹配的会话" : "暂无历史会话"}
          </div>
        ) : (
          <>
            {items.map(item => (
              <div key={item.id} className="all-sessions-item" onClick={() => onSelect(item)}>
                <div className="all-sessions-item__title-row">
                  {item.starred && <StarFilled style={{ color: "#f59e0b", fontSize: 11, flexShrink: 0 }} />}
                  <span className="all-sessions-item__title">{item.title || "(无标题)"}</span>
                </div>
                <div className="all-sessions-item__time">
                  {(item.updated_at ?? "").slice(0, 16).replace("T", " ")}
                </div>
              </div>
            ))}
            {hasMore && (
              <div style={{ textAlign: "center", padding: "16px 0 8px" }}>
                <Button size="small" onClick={() => { void load(q, offset, true); }} loading={loading}>
                  加载更多
                </Button>
              </div>
            )}
            {loading && items.length > 0 && (
              <div style={{ textAlign: "center", padding: "8px 0" }}><Spin size="small" /></div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
