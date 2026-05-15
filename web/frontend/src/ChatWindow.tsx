import React, { ReactNode, useEffect, useRef } from "react";
import { Spin } from "antd";
import { ThinkableMarkdown } from "./SimpleMarkdown";

export interface ChatWindowMsg {
  role: string;
  content?: string;
  id?: string | number;
  created_at?: string;
}

interface ChatWindowProps<T extends ChatWindowMsg> {
  messages: T[];
  isStreaming?: boolean;
  renderSpecialMsg?: (msg: T, index: number) => ReactNode | null | undefined;
  style?: React.CSSProperties;
  className?: string;
  "aria-label"?: string;
}

function formatMsgTime(ts: string): string {
  try {
    const d = new Date(ts.trim().replace(" ", "T"));
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString("zh-CN", {
        month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
    }
  } catch {
    // ignore
  }
  return ts;
}

export function ChatWindow<T extends ChatWindowMsg>({
  messages,
  isStreaming = false,
  renderSpecialMsg,
  style,
  className,
  "aria-label": ariaLabel,
}: ChatWindowProps<T>) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const lastAssistantIdx = messages.reduce(
    (last, m, i) => (m.role === "assistant" ? i : last),
    -1,
  );

  return (
    <div
      className={`conv-thread${className ? ` ${className}` : ""}`}
      style={style}
      aria-label={ariaLabel}
    >
      {messages.map((msg, i) => {
        const special = renderSpecialMsg?.(msg, i);
        if (special != null) {
          return <div key={msg.id ?? i}>{special}</div>;
        }

        if (msg.role === "status") {
          return (
            <div key={msg.id ?? i} style={{ padding: "2px 6px" }}>
              <span style={{ fontSize: 12, color: "rgba(47,58,50,0.55)" }}>{msg.content}</span>
            </div>
          );
        }

        const isUser = msg.role === "user";
        return (
          <div key={msg.id ?? i} className="conv-msg">
            <div className="conv-msg-role">{isUser ? "用户" : "助手"}</div>
            <div className={`conv-msg-body${isUser ? " conv-msg-body--user" : ""}`}>
              {msg.created_at && (
                <div className="conv-msg-meta">{formatMsgTime(msg.created_at)}</div>
              )}
              {isUser ? (
                <div className="conv-msg-plain">{String(msg.content ?? "")}</div>
              ) : (
                <ThinkableMarkdown markdown={String(msg.content ?? "")} />
              )}
            </div>
          </div>
        );
      })}
      {isStreaming && lastAssistantIdx < 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}>
          <Spin size="small" />
          <span style={{ fontSize: 12, color: "rgba(47,58,50,0.55)" }}>Agent思考中...</span>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
