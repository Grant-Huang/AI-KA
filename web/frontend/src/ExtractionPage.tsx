import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert, Badge, Button, Card, Dropdown, Empty, Input,
  Modal, Space, Table, Tag,
  Tooltip, Typography, Upload, message,
} from "antd";
import { ChatWindow } from "./ChatWindow";

import {
  ArrowUpOutlined, CheckOutlined, ClockCircleOutlined, CloseOutlined,
  DeleteOutlined, EditOutlined, EllipsisOutlined, InboxOutlined, PaperClipOutlined,
  PlusOutlined, ReloadOutlined, RetweetOutlined, StarFilled, StarOutlined, StopOutlined,
  UnorderedListOutlined, WarningOutlined,
} from "@ant-design/icons";
import { AllSessionsPanel, AllSessionItem } from "./AllSessionsPanel";
import type {
  ExtractionSession, PendingRuleItem, ReviewQueueItem,
} from "./api";
import {
  appendExtractionMessages, approvePendingRule, createExtractionSession,
  deleteExtractionSession, deleteReviewQueueItem,
  generateExtractionSessionTitle,
  getExtractionSessionMessages, getPendingRules, getReviewQueue,
  listExtractionSessions, patchExtractionSession, patchReviewQueueItem,
  postActiveExtractionStream, postDocExtractionStream, postReviewExtractionStream,
  rejectPendingRule, uploadExtractionMaterial,
} from "./api";
import SimpleMarkdown from "./SimpleMarkdown";

const { Text, Title } = Typography;
const { TextArea } = Input;

// ── Constants ────────────────────────────────────────────────────────────────

const DOMAIN_OPTIONS = [
  "项目管理", "需求分析", "产品设计", "系统集成",
  "运维管理", "质量保证", "数据分析", "安全合规",
  "供应链管理", "客户服务", "财务管理", "风险管理",
];

const STRATEGY_OPTIONS = [
  { value: "gap_based", label: "发现规则盲点", desc: "找出哪些经验还没有被总结成规律", example: "例：我做完项目复盘时总感觉有哪些坑没预见到，但不知道规律在哪" },
  { value: "fuzzy_signal", label: "澄清模糊印象", desc: "把说不清的直觉转化成清晰的规则", example: "例：碰到某类客户我会有点警觉，但我说不清楚具体在看什么" },
  { value: "critical_incident", label: "复盘具体案例", desc: "从一次实际经历提炼可复用的经验", example: "例：上次那个项目延期了，我们来拆解一下当时发生了什么" },
  { value: "reverse_validation", label: "挑战现有规则", desc: "检验一条规则是否在各种情境下都成立", example: "例：我一直觉得蓝图要在两周内锁定，但真的每次都该这样吗？" },
];

const CONFIDENCE_COLOR: Record<string, string> = {
  high: "green", medium: "orange", low: "red",
};

// ── Types ────────────────────────────────────────────────────────────────────

type StrategyOption = typeof STRATEGY_OPTIONS[number];
type ChatMsg =
  | { role: "user" | "assistant" | "status"; content: string }
  | { role: "choices"; options: StrategyOption[] }
  | { role: "clarify"; questions: string[] };


// ── ChatArea ─────────────────────────────────────────────────────────────────

function ChatArea({
  messages, streaming, onStrategyChoose, onClarify,
}: {
  messages: ChatMsg[];
  streaming: boolean;
  onStrategyChoose?: (opt: StrategyOption) => void;
  onClarify?: (text: string) => void;
}) {
  const [otherInput, setOtherInput] = useState("");
  const [showOther, setShowOther] = useState(false);

  useEffect(() => { setShowOther(false); setOtherInput(""); }, [messages.length]);

  const submitOther = () => {
    const t = otherInput.trim();
    if (!t) return;
    onClarify?.(t);
    setOtherInput("");
    setShowOther(false);
  };

  return (
    <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
      <ChatWindow<ChatMsg>
        messages={messages}
        isStreaming={streaming}
        renderSpecialMsg={(msg) => {
          if (msg.role === "choices") {
            const letters = ["A", "B", "C", "D"];
            return (
              <div style={{ paddingLeft: 2 }}>
                {msg.options.map((opt, oi) => (
                  <div
                    key={opt.value}
                    onClick={() => !streaming && onStrategyChoose?.(opt)}
                    style={{
                      display: "flex", gap: 10, padding: "8px 10px", borderRadius: 8,
                      cursor: streaming ? "default" : "pointer", marginBottom: 4,
                      transition: "background 0.12s", opacity: streaming ? 0.5 : 1,
                    }}
                    onMouseEnter={(e) => { if (!streaming) (e.currentTarget as HTMLElement).style.background = "rgba(82,124,94,0.07)"; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                  >
                    <span style={{ fontWeight: 600, color: "#527c5e", minWidth: 18, flexShrink: 0, paddingTop: 1 }}>
                      {letters[oi]}
                    </span>
                    <div>
                      <div style={{ fontWeight: 500, fontSize: 14, color: "#222", lineHeight: 1.4 }}>{opt.label}</div>
                      <div style={{ fontSize: 13, color: "#666", marginTop: 2, lineHeight: 1.45 }}>{opt.desc}</div>
                      {opt.example && (
                        <div style={{ fontSize: 12, color: "#999", marginTop: 3, lineHeight: 1.45 }}>↳ {opt.example}</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            );
          }
          if (msg.role === "clarify") {
            return (
              <div style={{ paddingLeft: 4 }}>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: showOther ? 8 : 0 }}>
                  {msg.questions.map((q, qi) => (
                    <Button key={qi} size="small" onClick={() => onClarify?.(q)} disabled={streaming} style={{ borderRadius: 16 }}>
                      {q}
                    </Button>
                  ))}
                  <Button size="small" onClick={() => setShowOther((v) => !v)} disabled={streaming} style={{ borderRadius: 16 }}>
                    其他…
                  </Button>
                </div>
                {showOther && (
                  <div style={{ display: "flex", gap: 6 }}>
                    <Input size="small" value={otherInput} onChange={(e) => setOtherInput(e.target.value)}
                      onPressEnter={submitOther} placeholder="输入自定义回复…" autoFocus style={{ flex: 1 }} />
                    <Button size="small" type="primary" onClick={submitOther}>发送</Button>
                  </div>
                )}
              </div>
            );
          }
          return null;
        }}
        style={{ flex: 1, overflowY: "auto" }}
      />
    </div>
  );
}

// ── ExpertQATab ──────────────────────────────────────────────────────────────

function ExpertQATab({
  postReviewCtx,
  preloadMessages,
  sessionId,
  onFirstMessage,
  onRoundComplete,
}: {
  postReviewCtx: { projectId: number; conversationId: number } | null;
  preloadMessages: ChatMsg[];
  sessionId: number | null;
  onFirstMessage: (title: string, strategy: string) => Promise<number>;
  onRoundComplete: (sid: number, messages: Array<{ role: string; content: string }>, roundNum: number) => void;
}) {
  const [phase, setPhase] = useState<"choosing" | "chatting">("choosing");
  const [strategy, setStrategy] = useState("gap_based");
  const [rqItems, setRqItems] = useState<ReviewQueueItem[]>([]);
  const [rqItemId, setRqItemId] = useState<string | null>(null);
  const [materialId, setMaterialId] = useState<string | null>(null);
  const [docName, setDocName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>(preloadMessages);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [roundNumber, setRoundNumber] = useState(1);
  const [newKiIds, setNewKiIds] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const isPostReview = postReviewCtx != null;
  const isDocMode = materialId != null;

  const makeInitialMessages = (postReview: boolean): ChatMsg[] => {
    const opening: ChatMsg = {
      role: "assistant",
      content: postReview
        ? `已关联本次审查结果（项目 #${postReviewCtx!.projectId}）。请描述遗漏或补充发现，或直接点击「开始提取」。`
        : "你好！今天想总结些什么经验？选一个方向，或者直接告诉我你想聊什么：",
    };
    if (postReview) return [opening];
    return [opening, { role: "choices", options: STRATEGY_OPTIONS }];
  };

  useEffect(() => {
    if (preloadMessages.length > 0) {
      setMessages(preloadMessages);
      setPhase("chatting");
    } else {
      setPhase("choosing");
      setMessages(makeInitialMessages(isPostReview));
    }
    setRoundNumber(1);
    setNewKiIds([]);
    setMaterialId(null);
    setDocName("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPostReview, postReviewCtx?.projectId, postReviewCtx?.conversationId]);

  useEffect(() => {
    getReviewQueue().then(({ items }) => setRqItems(items)).catch(() => {});
  }, []);

  const priorMessages = messages
    .filter((m): m is { role: "user" | "assistant"; content: string } =>
      m.role === "user" || m.role === "assistant"
    )
    .map((m) => ({ role: m.role as string, content: m.content }));

  const runStream = async (userText: string) => {
    let sid = sessionId;
    if (sid === null) {
      try {
        const title = userText.slice(0, 40) + (userText.length > 40 ? "…" : "");
        sid = await onFirstMessage(title, strategy);
      } catch { /* ignore */ }
    }

    setMessages((prev) => [...prev, { role: "user", content: userText }]);
    setStreaming(true);
    abortRef.current = new AbortController();

    const acc: string[] = [];

    try {
      const streamFn = isPostReview
        ? (ev: Parameters<typeof postReviewExtractionStream>[3]) =>
            postReviewExtractionStream(
              postReviewCtx!.projectId,
              postReviewCtx!.conversationId,
              { user_input: userText, prior_messages: priorMessages },
              ev,
              abortRef.current!.signal,
            )
        : isDocMode
          ? (ev: Parameters<typeof postDocExtractionStream>[1]) =>
              postDocExtractionStream(
                { material_id: materialId!, user_input: userText, strategy, prior_messages: priorMessages },
                ev,
                abortRef.current!.signal,
              )
          : (ev: Parameters<typeof postActiveExtractionStream>[1]) =>
              postActiveExtractionStream(
                {
                  user_input: userText,
                  strategy,
                  review_queue_item_id: rqItemId,
                  prior_messages: priorMessages,
                  round_number: roundNumber,
                },
                ev,
                abortRef.current!.signal,
              );

      await streamFn(
        (ev) => {
          if (ev.type === "status") {
            setMessages((prev) => [...prev, { role: "status", content: String(ev.msg ?? "") }]);
          } else if (ev.type === "text") {
            const chunk = String(ev.text ?? "");
            acc.push(chunk);
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (last?.role === "assistant") {
                return [...prev.slice(0, -1), { role: "assistant", content: last.content + chunk }];
              }
              return [...prev, { role: "assistant", content: chunk }];
            });
          } else if (ev.type === "ki") {
            const kid = String((ev as any).kid ?? "");
            if (kid) setNewKiIds((prev) => (prev.includes(kid) ? prev : [...prev, kid]));
          } else if (ev.type === "clarify") {
            const clarify = (ev as any).clarify as { questions?: string[] } | undefined;
            if (clarify?.questions?.length) {
              setMessages((prev) => [
                ...prev,
                { role: "clarify", questions: clarify!.questions! },
              ]);
            }
          } else if (ev.type === "final") {
            const satisfaction = (ev as any).satisfaction as number | null;
            const autoAdv = Boolean((ev as any).auto_advance);
            const kiCount = Number((ev as any).new_ki_count ?? 0);
            let msg = "";
            if (kiCount > 0) msg += `✓ 生成 ${kiCount} 条知识条目，已发送到「待批准规则」。`;
            if (autoAdv) msg += "  满意度已达标。";
            else if (satisfaction !== null) msg += `  满意度 ${Math.round(satisfaction * 100)}%，可继续追问。`;
            if (msg) setMessages((prev) => [...prev, { role: "status", content: msg }]);
            setRoundNumber((n) => n + 1);
          }
        },
      );

      const fullAssistant = acc.join("");
      if (sid !== null) {
        const toSave: Array<{ role: string; content: string }> = [
          { role: "user", content: userText },
        ];
        if (fullAssistant) toSave.push({ role: "assistant", content: fullAssistant });
        onRoundComplete(sid, toSave, roundNumber);
      }
    } catch (e) {
      if ((e as Error)?.name !== "AbortError") {
        message.error(`提取失败: ${e instanceof Error ? e.message : String(e)}`);
      }
    } finally {
      setStreaming(false);
    }
  };

  const handleStrategySelect = async (s: StrategyOption) => {
    setStrategy(s.value);
    setPhase("chatting");
    setMessages((prev) => prev.filter((m) => m.role !== "choices"));
    await runStream(`我想从「${s.label}」方向开始`);
  };

  const handleClarifyChoice = async (text: string) => {
    setMessages((prev) => prev.filter((m) => m.role !== "clarify"));
    await runStream(text);
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    if (phase === "choosing") setPhase("chatting");
    await runStream(text);
  };

  const handlePostReviewStart = async () => {
    setPhase("chatting");
    await runStream("请开始分析，帮我识别可以提炼的知识");
  };

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const res = await uploadExtractionMaterial(file);
      setMaterialId(res.material_id);
      setDocName(res.original_name);
      setPhase("chatting");
      setMessages((prev) => [
        ...prev,
        { role: "status", content: `📎 已加载文档：${res.original_name}` },
      ]);
      await runStream("请基于文档内容开始提取知识");
    } catch (e) {
      message.error(`上传失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(false);
    }
    return false;
  };

  const handleStop = () => { abortRef.current?.abort(); setStreaming(false); };

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
      {materialId && docName && (
        <Tag closable onClose={() => { setMaterialId(null); setDocName(""); }}
          icon={<PaperClipOutlined />} style={{ margin: "8px 12px 0", flexShrink: 0 }}>
          {docName}
        </Tag>
      )}

      {/* Chat area fills available height */}
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <ChatArea
          messages={messages}
          streaming={streaming}
          onStrategyChoose={(opt) => void handleStrategySelect(opt)}
          onClarify={(text) => void handleClarifyChoice(text)}
        />
      </div>

      {/* Input box pinned at bottom */}
      <div style={{ flexShrink: 0, padding: "0 12px 12px" }}>
        <div style={{
          border: "1px solid var(--color-border, #e0e0d8)", borderRadius: 10,
          background: "#fff", overflow: "hidden",
        }}>
          <TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void handleSend(); }
            }}
            placeholder={
              isPostReview
                ? "描述遗漏的问题或补充发现（Shift+Enter 换行）"
                : "输入 A / B / C / D，或直接说你想聊的…（Shift+Enter 换行）"
            }
            autoSize={{ minRows: 2, maxRows: 6 }}
            disabled={streaming}
            style={{ border: "none", boxShadow: "none", resize: "none", padding: "10px 12px", background: "#fff" }}
          />
          {/* Input toolbar */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "4px 8px 6px" }}>
            <div style={{ display: "flex", gap: 4 }}>
              {!isPostReview && (
                <Tooltip
                  trigger="click"
                  placement="topLeft"
                  title={
                    <div style={{ display: "flex", flexDirection: "column", gap: 2, padding: "2px 0" }}>
                      <Upload accept=".md,.html,.htm,.txt,.docx,.pdf,.xlsx,.csv,.pptx" beforeUpload={(file) => { void handleUpload(file); return false; }}
                        showUploadList={false} disabled={uploading || streaming}>
                        <div style={{
                          display: "flex", alignItems: "center", gap: 8, padding: "6px 10px",
                          cursor: "pointer", borderRadius: 6, color: "#fff", fontSize: 13,
                          whiteSpace: "nowrap",
                        }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.15)")}
                          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                        >
                          <PaperClipOutlined />
                          <span>{uploading ? "上传中…" : "上传参考文档"}</span>
                        </div>
                      </Upload>
                    </div>
                  }
                  overlayInnerStyle={{ padding: "4px 0" }}
                >
                  <Button size="small" type="text" icon={<PlusOutlined />}
                    style={{ borderRadius: 6, fontWeight: 600, fontSize: 15 }}
                    title="更多操作" disabled={streaming} />
                </Tooltip>
              )}
              {/* 换个方向：mid-session strategy pivot */}
              {!isPostReview && phase === "chatting" && !streaming && (
                <Tooltip title="换个方向" placement="top">
                  <Button size="small" type="text" icon={<RetweetOutlined />}
                    style={{ borderRadius: 6 }}
                    onClick={() => {
                      setMessages((prev) => [
                        ...prev.filter((m) => m.role !== "choices"),
                        { role: "choices", options: STRATEGY_OPTIONS },
                      ]);
                    }}
                  />
                </Tooltip>
              )}
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              {streaming ? (
                <Button danger size="small" shape="circle" icon={<StopOutlined />} onClick={handleStop} title="停止" />
              ) : isPostReview && messages.filter((m) => m.role !== "status" && m.role !== "assistant").length === 0 ? (
                <Button type="primary" size="small" onClick={() => void handlePostReviewStart()}>开始提取</Button>
              ) : (
                <Button type="primary" size="small" shape="circle" icon={<ArrowUpOutlined />}
                  onClick={() => void handleSend()} disabled={!input.trim() || streaming} />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── PendingRulesTab ──────────────────────────────────────────────────────────

function PendingRulesTab() {
  const [items, setItems] = useState<PendingRuleItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [actionId, setActionId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { items: data } = await getPendingRules();
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleApprove = async (id: string) => {
    setActionId(id);
    try {
      await approvePendingRule(id, {});
      message.success("已批准，规则已写入活动技能包");
      setItems((prev) => prev.filter((x) => x.id !== id));
    } catch (e) {
      message.error(`批准失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setActionId(null);
    }
  };

  const handleReject = async () => {
    if (!rejectTarget) return;
    setActionId(rejectTarget);
    try {
      await rejectPendingRule(rejectTarget, { reason: rejectReason });
      message.success("已拒绝");
      setItems((prev) => prev.filter((x) => x.id !== rejectTarget));
    } catch (e) {
      message.error(`拒绝失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setActionId(null);
      setRejectTarget(null);
      setRejectReason("");
    }
  };

  const CONF_LABEL: Record<string, string> = { high: "高", medium: "中", low: "低" };

  const columns = [
    {
      title: "标题 / 关注点",
      key: "title",
      render: (_: unknown, row: PendingRuleItem) => (
        <div>
          <div style={{ fontWeight: 500 }}>{row.title}</div>
          <Tag style={{ marginTop: 4 }}>{row.extraction_focus_id}</Tag>
        </div>
      ),
    },
    {
      title: "内容摘要",
      dataIndex: "content",
      ellipsis: true,
      render: (v: string) => (
        <Tooltip title={<div style={{ maxWidth: 360, whiteSpace: "pre-wrap" }}>{v}</div>} placement="left">
          <span style={{ cursor: "pointer", color: "#666" }}>{v.slice(0, 80)}{v.length > 80 ? "…" : ""}</span>
        </Tooltip>
      ),
    },
    {
      title: "置信度",
      dataIndex: "confidence",
      width: 70,
      render: (v: string) => (
        <Tag color={CONFIDENCE_COLOR[v] || "default"}>{CONF_LABEL[v] || v}</Tag>
      ),
    },
    {
      title: "冲突",
      key: "conflicts",
      width: 70,
      render: (_: unknown, row: PendingRuleItem) =>
        row.has_conflicts ? (
          <Tooltip title={row.conflict_with.map((c) => `${c.focus_id}: ${c.reason}`).join("\n")}>
            <Tag color="warning" icon={<WarningOutlined />}>冲突</Tag>
          </Tooltip>
        ) : (
          <Tag color="success">无</Tag>
        ),
    },
    {
      title: "操作",
      width: 150,
      render: (_: unknown, row: PendingRuleItem) => (
        <Space>
          <Button
            type="primary" size="small" icon={<CheckOutlined />}
            loading={actionId === row.id}
            onClick={() => void handleApprove(row.id)}
          >
            批准
          </Button>
          <Button
            danger size="small" icon={<CloseOutlined />}
            onClick={() => { setRejectTarget(row.id); setRejectReason(""); }}
          >
            拒绝
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: "16px 0" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 12, gap: 8 }}>
        <Title level={5} style={{ margin: 0 }}>待批准规则</Title>
        <Button icon={<ReloadOutlined />} size="small" onClick={load} loading={loading}>刷新</Button>
        <Text type="secondary" style={{ marginLeft: "auto", fontSize: 12 }}>
          批准后写入活动技能包；拒绝的条目不影响规则库
        </Text>
      </div>
      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      {!loading && items.length === 0 ? (
        <Empty
          description="暂无待批准规则。通过专家答问生成知识条目后，它们会出现在此处。"
          style={{ padding: "40px 0" }}
        />
      ) : (
        <Table
          dataSource={items}
          columns={columns}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ pageSize: 15, showSizeChanger: false }}
          expandable={{
            expandedRowRender: (row) => (
              <div style={{ padding: "8px 16px" }}>
                <Text strong>完整内容：</Text>
                <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: "6px 0", fontSize: 13 }}>
                  {row.content}
                </pre>
                {row.scope_note && (
                  <div style={{ marginTop: 6 }}>
                    <Text type="secondary">适用范围：{row.scope_note}</Text>
                  </div>
                )}
              </div>
            ),
          }}
        />
      )}
      <Modal
        title="拒绝原因"
        open={!!rejectTarget}
        onCancel={() => { setRejectTarget(null); setRejectReason(""); }}
        onOk={() => void handleReject()}
        okText="确认拒绝"
        okButtonProps={{ danger: true }}
        cancelText="取消"
      >
        <TextArea
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder="请说明拒绝原因（可选）"
          rows={3}
        />
      </Modal>
    </div>
  );
}

// ── ExtractionSessionItem (sidebar row) ──────────────────────────────────────

function ExtractionSessionItem({ s, active, onSelect, onStar, onRename, onDelete }: {
  s: ExtractionSession;
  active: boolean;
  onSelect: () => void;
  onStar: () => void;
  onRename: () => void;
  onDelete: (ev: React.MouseEvent) => void;
}) {
  return (
    <div
      className={`session-item${active ? " session-item--active" : ""}`}
      onClick={onSelect}
    >
      {s.starred && <span className="session-item__star"><StarFilled /></span>}
      <div className="session-item__body">
        <Tooltip title={s.title} placement="right" mouseEnterDelay={0.5}>
          <div className="session-item__title">{s.title}</div>
        </Tooltip>
        <div className="session-item__time">
          <ClockCircleOutlined style={{ marginRight: 3 }} />
          {s.updated_at.slice(0, 16).replace("T", " ")}
        </div>
      </div>
      <Dropdown
        trigger={["click"]}
        placement="bottomRight"
        menu={{
          items: [
            {
              key: "star",
              label: s.starred ? "取消收藏" : "收藏",
              icon: s.starred ? <StarFilled style={{ color: "#f59e0b" }} /> : <StarOutlined />,
              onClick: ({ domEvent }) => { domEvent.stopPropagation(); onStar(); },
            },
            {
              key: "rename",
              label: "重命名",
              icon: <EditOutlined />,
              onClick: ({ domEvent }) => { domEvent.stopPropagation(); onRename(); },
            },
            { type: "divider" as const },
            {
              key: "delete",
              label: "删除",
              icon: <DeleteOutlined />,
              danger: true,
              onClick: ({ domEvent }) => { domEvent.stopPropagation(); onDelete(domEvent as unknown as React.MouseEvent); },
            },
          ],
        }}
      >
        <Button type="text" size="small" className="session-item__menu"
          icon={<EllipsisOutlined />} onClick={(e) => e.stopPropagation()} />
      </Dropdown>
    </div>
  );
}

// ── ExtractionPage (main) ─────────────────────────────────────────────────────

export default function ExtractionPage() {
  const [postReviewCtx, setPostReviewCtx] = useState<{ projectId: number; conversationId: number } | null>(null);

  // Session history state
  const [sessions, setSessions] = useState<ExtractionSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<number | null>(null);
  const [preloadMessages, setPreloadMessages] = useState<ChatMsg[]>([]);
  const [sessionKey, setSessionKey] = useState(0);

  // Rename state
  const [renameTargetId, setRenameTargetId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [showAllSessions, setShowAllSessions] = useState(false);

  // Accumulated messages for title generation
  const accumulatedMsgsRef = useRef<Array<{ role: string; content: string }>>([]);

  useEffect(() => {
    const raw = window.sessionStorage.getItem("aika_post_review_ctx");
    if (raw) {
      try {
        const ctx = JSON.parse(raw) as { projectId: number; conversationId: number };
        window.sessionStorage.removeItem("aika_post_review_ctx");
        setPostReviewCtx(ctx);
      } catch { /* ignore */ }
    }
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const { sessions: s } = await listExtractionSessions();
      setSessions(s);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { void loadSessions(); }, [loadSessions]);

  const handleNewSession = () => {
    setCurrentSessionId(null);
    setPreloadMessages([]);
    setSessionKey((k) => k + 1);
    accumulatedMsgsRef.current = [];
  };

  const handleSelectSession = async (sid: number) => {
    try {
      const { messages } = await getExtractionSessionMessages(sid);
      const chatMsgs: ChatMsg[] = messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));
      setCurrentSessionId(sid);
      setPreloadMessages(chatMsgs);
      setSessionKey((k) => k + 1);
      } catch { /* ignore */ }
  };

  const handleDeleteSession = (sid: number, ev: React.MouseEvent) => {
    ev.stopPropagation();
    Modal.confirm({
      title: "确认删除会话",
      content: "此操作不可撤销。",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        await deleteExtractionSession(sid);
        if (currentSessionId === sid) handleNewSession();
        await loadSessions();
        message.success("会话已删除");
      },
    });
  };

  const handleStarSession = async (sid: number, starred: boolean) => {
    try {
      await patchExtractionSession(sid, { starred });
      await loadSessions();
    } catch { /* ignore */ }
  };

  const handleRenameSubmit = async () => {
    const name = renameValue.trim();
    if (!name || renameTargetId === null) { setRenameTargetId(null); return; }
    try {
      await patchExtractionSession(renameTargetId, { title: name });
      await loadSessions();
    } catch { /* ignore */ }
    setRenameTargetId(null);
  };

  const handleFirstMessage = async (_title: string, strat: string): Promise<number> => {
    accumulatedMsgsRef.current = [];
    const s = await createExtractionSession("新会话", strat);
    setCurrentSessionId(s.id);
    void loadSessions();
    return s.id;
  };

  const handleRoundComplete = (sid: number, msgs: Array<{ role: string; content: string }>, roundNum: number) => {
    accumulatedMsgsRef.current = [...accumulatedMsgsRef.current, ...msgs];
    void appendExtractionMessages(sid, msgs).then(() => void loadSessions());
    if (roundNum === 5) {
      void generateExtractionSessionTitle(sid, accumulatedMsgsRef.current)
        .then(() => void loadSessions())
        .catch(() => {});
    }
  };

  const SIDEBAR_LIMIT = 25;
  const starredSessions = sessions.filter(s => s.starred);
  const recentSessions = sessions.filter(s => !s.starred);
  const displayStarred = starredSessions.slice(0, SIDEBAR_LIMIT);
  const displayRecent = recentSessions.slice(0, Math.max(0, SIDEBAR_LIMIT - displayStarred.length));

  const fetchExtractionSessions = useCallback(async (opts: { limit: number; offset: number; q: string }): Promise<{ items: AllSessionItem[]; hasMore: boolean }> => {
    const { sessions: all } = await listExtractionSessions();
    const filtered = opts.q ? all.filter(s => s.title.toLowerCase().includes(opts.q.toLowerCase())) : all;
    const page = filtered.slice(opts.offset, opts.offset + opts.limit);
    return {
      items: page.map(s => ({ id: s.id, title: s.title, updated_at: s.updated_at, starred: s.starred })),
      hasMore: opts.offset + page.length < filtered.length,
    };
  }, []);

  return (
    <div className="extraction-page" style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* ── Two-column content ── */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Left session sidebar */}
        <div className="session-col">
          <div className="session-col__header">
            <Text strong style={{ fontSize: 13 }}>知识归纳</Text>
            <Button size="small" icon={<PlusOutlined />} onClick={handleNewSession} title="新会话" />
          </div>
          <div className="session-col__list">
            {sessions.length === 0 ? (
              <Text type="secondary" style={{ fontSize: 12, padding: "8px 4px", display: "block" }}>暂无历史会话</Text>
            ) : (
              <>
                {displayStarred.length > 0 && (
                  <>
                    <div className="session-group-label">置顶</div>
                    {displayStarred.map((s) => (
                      <ExtractionSessionItem key={s.id} s={s} active={s.id === currentSessionId}
                        onSelect={() => { setShowAllSessions(false); void handleSelectSession(s.id); }}
                        onStar={() => void handleStarSession(s.id, !s.starred)}
                        onRename={() => { setRenameTargetId(s.id); setRenameValue(s.title); }}
                        onDelete={(ev) => handleDeleteSession(s.id, ev)} />
                    ))}
                  </>
                )}
                {displayRecent.length > 0 && (
                  <>
                    <div className="session-group-label">近期会话</div>
                    {displayRecent.map((s) => (
                      <ExtractionSessionItem key={s.id} s={s} active={s.id === currentSessionId}
                        onSelect={() => { setShowAllSessions(false); void handleSelectSession(s.id); }}
                        onStar={() => void handleStarSession(s.id, !s.starred)}
                        onRename={() => { setRenameTargetId(s.id); setRenameValue(s.title); }}
                        onDelete={(ev) => handleDeleteSession(s.id, ev)} />
                    ))}
                  </>
                )}
              </>
            )}
            <div className="session-col__all-btn" onClick={() => setShowAllSessions(true)}>
              <UnorderedListOutlined style={{ fontSize: 12 }} />
              <span>所有会话</span>
            </div>
          </div>
        </div>

        {/* Main content */}
        <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          {showAllSessions ? (
            <AllSessionsPanel
              fetchSessions={fetchExtractionSessions}
              onSelect={(item) => {
                setShowAllSessions(false);
                void handleSelectSession(item.id);
              }}
            />
          ) : (
            <ExpertQATab
              key={sessionKey}
              postReviewCtx={postReviewCtx}
              preloadMessages={preloadMessages}
              sessionId={currentSessionId}
              onFirstMessage={handleFirstMessage}
              onRoundComplete={handleRoundComplete}
            />
          )}
        </div>
      </div>

      {/* Rename modal */}
      <Modal
        title="重命名会话"
        open={renameTargetId !== null}
        onCancel={() => setRenameTargetId(null)}
        onOk={() => void handleRenameSubmit()}
        okText="保存"
        cancelText="取消"
      >
        <Input
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onPressEnter={() => void handleRenameSubmit()}
          maxLength={60}
          autoFocus
        />
      </Modal>
    </div>
  );
}


// ── ReviewQueueTab (used as 结果评审 tab in project review) ───────────────────

export function ReviewQueueTab({
  onStartExtraction,
}: {
  onStartExtraction?: (item: ReviewQueueItem) => void;
}) {
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { items: data } = await getReviewQueue();
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleDelete = async (id: string) => {
    try {
      await deleteReviewQueueItem(id);
      setItems((prev) => prev.filter((x) => x.id !== id));
      message.success("已删除");
    } catch (e) {
      message.error(`删除失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleStatus = async (id: string, status: string) => {
    try {
      await patchReviewQueueItem(id, { status });
      setItems((prev) => prev.map((x) => (x.id === id ? { ...x, status } : x)));
    } catch (e) {
      message.error(`更新失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const STATUS_COLOR: Record<string, string> = {
    pending_review: "default", in_review: "processing",
    approved: "success", rejected: "error", archived: "warning",
  };
  const STATUS_LABEL: Record<string, string> = {
    pending_review: "待审查", in_review: "审查中",
    approved: "已批准", rejected: "已拒绝", archived: "已归档",
  };

  const columns = [
    { title: "关注点", dataIndex: "focus_id", width: 100, render: (v: string) => <Tag>{v}</Tag> },
    { title: "知识线索", dataIndex: "suggestion", ellipsis: true },
    {
      title: "出现次数", dataIndex: "occurrences", width: 80, align: "center" as const,
      render: (v: number) => <Badge count={v} color={v >= 3 ? "red" : v >= 2 ? "orange" : "blue"} showZero />,
    },
    {
      title: "状态", dataIndex: "status", width: 90,
      render: (v: string) => <Tag color={STATUS_COLOR[v] || "default"}>{STATUS_LABEL[v] || v}</Tag>,
    },
    {
      title: "操作", width: 180,
      render: (_: unknown, row: ReviewQueueItem) => (
        <Space size={4}>
          {onStartExtraction && (
            <Button
              type="link" size="small"
              onClick={() => onStartExtraction(row)}
              disabled={row.status === "approved" || row.status === "rejected"}
            >
              深入提取
            </Button>
          )}
          <Button
            type="link" size="small"
            onClick={() => void handleStatus(row.id, row.status === "archived" ? "pending_review" : "archived")}
          >
            {row.status === "archived" ? "恢复" : "归档"}
          </Button>
          <Button
            type="link" size="small" danger
            icon={<DeleteOutlined />}
            onClick={() => void handleDelete(row.id)}
          />
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: "16px 0" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 12, gap: 8 }}>
        <Title level={5} style={{ margin: 0 }}>结果评审</Title>
        <Button icon={<ReloadOutlined />} size="small" onClick={load} loading={loading}>刷新</Button>
        <Text type="secondary" style={{ marginLeft: "auto", fontSize: 12 }}>
          项目审查后 LLM 自动识别的可泛化知识线索，按出现次数降序
        </Text>
      </div>
      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      {!loading && items.length === 0 ? (
        <Empty
          description="暂无队列条目。完成一次项目审查后，LLM 会自动提取泛化知识线索到此处。"
          style={{ padding: "40px 0" }}
        />
      ) : (
        <Table
          dataSource={items}
          columns={columns}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: false }}
        />
      )}
    </div>
  );
}
