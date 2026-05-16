import React, { ReactNode, useEffect, useRef, useState } from "react";
import { message as antdMsg } from "antd";
import { CopyOutlined, LikeOutlined, DislikeOutlined, ReloadOutlined } from "@ant-design/icons";
import { ThinkableMarkdown, ThinkingDots } from "./SimpleMarkdown";

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
  onRegenerate?: (index: number) => void;
  style?: React.CSSProperties;
  className?: string;
  "aria-label"?: string;
}

function formatMsgTime(ts: string): string {
  try {
    const d = new Date(ts.trim().replace(" ", "T"));
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    }
  } catch { /* ignore */ }
  return ts;
}

function AssistantActions({
  content,
  index,
  onRegenerate,
}: {
  content: string;
  index: number;
  onRegenerate?: (i: number) => void;
}) {
  const [liked, setLiked] = useState<"like" | "dislike" | null>(null);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      antdMsg.success("已复制", 1.5);
    } catch {
      antdMsg.error("复制失败");
    }
  };

  return (
    <div className="chat-bubble__actions">
      <CopyOutlined title="复制" onClick={handleCopy} />
      <LikeOutlined
        title="有帮助"
        className={liked === "like" ? "active" : ""}
        onClick={() => setLiked((v) => (v === "like" ? null : "like"))}
      />
      <DislikeOutlined
        title="没帮助"
        className={liked === "dislike" ? "active" : ""}
        onClick={() => setLiked((v) => (v === "dislike" ? null : "dislike"))}
      />
      {onRegenerate && (
        <ReloadOutlined title="重新生成" onClick={() => onRegenerate(index)} />
      )}
    </div>
  );
}

export function ChatWindow<T extends ChatWindowMsg>({
  messages,
  isStreaming = false,
  renderSpecialMsg,
  onRegenerate,
  style,
  className,
  "aria-label": ariaLabel,
}: ChatWindowProps<T>) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);

  // Use IntersectionObserver to detect if the bottom sentinel is visible.
  // This works regardless of which ancestor provides the scroll container.
  useEffect(() => {
    const el = bottomRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => { isNearBottomRef.current = entry.isIntersecting; },
      { threshold: 0 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    if (isNearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const lastAssistantIdx = messages.reduce(
    (last, m, i) => (m.role === "assistant" ? i : last),
    -1,
  );

  return (
    <div
      className={`chat-thread${className ? ` ${className}` : ""}`}
      style={style}
      aria-label={ariaLabel}
    >
      {messages.map((msg, i) => {
        const special = renderSpecialMsg?.(msg, i);
        if (special != null) {
          return <div key={msg.id ?? i} className="chat-bubble-row">{special}</div>;
        }

        if (msg.role === "status") {
          return (
            <div key={msg.id ?? i} className="chat-status-line">
              {msg.content}
            </div>
          );
        }

        const isUser = msg.role === "user";
        const isAssistant = msg.role === "assistant";
        const isLast = i === messages.length - 1;
        const showCursor = isStreaming && isLast && isAssistant;

        return (
          <div key={msg.id ?? i} className={`chat-bubble-row${isUser ? " chat-bubble-row--user" : " chat-bubble-row--assistant"}`}>
            {isUser ? (
              <div className="chat-bubble chat-bubble--user">
                {msg.created_at && (
                  <div className="chat-bubble__meta">{formatMsgTime(msg.created_at)}</div>
                )}
                <div className="chat-bubble__text">{String(msg.content ?? "")}</div>
              </div>
            ) : isAssistant ? (
              <div className="chat-bubble chat-bubble--assistant">
                {msg.created_at && (
                  <div className="chat-bubble__meta">{formatMsgTime(msg.created_at)}</div>
                )}
                <ThinkableMarkdown markdown={String(msg.content ?? "")} showCursor={showCursor} />
                {(!isStreaming || !isLast) && (
                  <AssistantActions
                    content={String(msg.content ?? "")}
                    index={i}
                    onRegenerate={onRegenerate}
                  />
                )}
              </div>
            ) : null}
          </div>
        );
      })}
      {isStreaming && lastAssistantIdx < 0 && (
        <div className="chat-bubble-row chat-bubble-row--assistant">
          <div className="chat-thinking">
            <ThinkingDots />
            <span>思考中…</span>
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
