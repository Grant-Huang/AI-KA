import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert, Badge, Button, Card, Empty, Input,
  Modal, Select, Space, Spin, Table, Tag,
  Tooltip, Typography, Upload, message,
} from "antd";

import {
  CheckOutlined, CloseOutlined, DeleteOutlined, InboxOutlined,
  PaperClipOutlined, ReloadOutlined, UserOutlined, WarningOutlined,
} from "@ant-design/icons";
import type {
  ExpertProfileData, PendingRuleItem, ReviewQueueItem,
} from "./api";
import {
  approvePendingRule, deleteReviewQueueItem, getExpertProfile,
  getPendingRules, getReviewQueue, patchReviewQueueItem, postActiveExtractionStream,
  postDocExtractionStream, postReviewExtractionStream, putExpertProfile, rejectPendingRule,
  uploadExtractionMaterial,
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
  { value: "gap_based", label: "规则差距", desc: "对比 Review Queue 与现有规则，识别空白" },
  { value: "fuzzy_signal", label: "模糊信号", desc: "澄清模糊印象，转化为清晰规则" },
  { value: "critical_incident", label: "关键事件", desc: "从具体案例提炼可复用规律" },
  { value: "reverse_validation", label: "反向验证", desc: "验证或反驳现有规则的适用边界" },
];

const CONFIDENCE_COLOR: Record<string, string> = {
  high: "green", medium: "orange", low: "red",
};

// ── Types ────────────────────────────────────────────────────────────────────

type ChatMsg = { role: "user" | "assistant" | "status"; content: string };
type ActiveTab = "extract" | "pending";

// ── ExpertProfileModal ───────────────────────────────────────────────────────

function ExpertProfileModal({
  open, profile, onSave, onClose,
}: {
  open: boolean;
  profile: ExpertProfileData | null;
  onSave: (p: ExpertProfileData) => Promise<void>;
  onClose: () => void;
}) {
  const [domains, setDomains] = useState<string[]>(profile?.domains ?? []);
  const [background, setBackground] = useState(profile?.background ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setDomains(profile?.domains ?? []);
      setBackground(profile?.background ?? "");
    }
  }, [open, profile]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({ domains, background });
      onClose();
    } catch (e) {
      message.error(`保存失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="专家背景设置"
      open={open}
      onCancel={onClose}
      onOk={handleSave}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      width={480}
    >
      <div style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ fontSize: 13 }}>
          填写您的专业领域与背景，LLM 将据此优化提问策略。
        </Text>
      </div>
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 6 }}>
          <Text strong>擅长领域（多选）</Text>
        </div>
        <Select
          mode="multiple"
          value={domains}
          onChange={setDomains}
          options={DOMAIN_OPTIONS.map((d) => ({ value: d, label: d }))}
          placeholder="选择领域..."
          style={{ width: "100%" }}
          allowClear
        />
      </div>
      <div>
        <div style={{ marginBottom: 6 }}>
          <Text strong>背景描述</Text>
        </div>
        <TextArea
          value={background}
          onChange={(e) => setBackground(e.target.value)}
          placeholder="简要描述您的工作经验与专长（可选）"
          rows={4}
          showCount
          maxLength={500}
        />
      </div>
    </Modal>
  );
}

// ── ChatArea ─────────────────────────────────────────────────────────────────

function ChatArea({ messages, streaming }: { messages: ChatMsg[]; streaming: boolean }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div style={{
      border: "1px solid var(--color-border, #e0e0d8)", borderRadius: 8,
      padding: "12px 14px", background: "var(--color-bg-card, #fff)",
      minHeight: 200, maxHeight: 420, overflowY: "auto",
    }}>
      {messages.map((msg, i) => (
        <div
          key={i}
          style={{
            marginBottom: 12,
            padding: msg.role === "status" ? "4px 8px" : "8px 12px",
            borderRadius: 6,
            background: msg.role === "user"
              ? "rgba(82, 124, 94, 0.08)"
              : msg.role === "status"
                ? "transparent"
                : "var(--color-bg-card, #fff)",
            borderLeft: msg.role === "assistant" ? "3px solid rgba(82,124,94,0.4)" : "none",
          }}
        >
          {msg.role === "status" ? (
            <Text type="secondary" style={{ fontSize: 12 }}>{msg.content}</Text>
          ) : msg.role === "user" ? (
            <Text>{msg.content}</Text>
          ) : (
            <SimpleMarkdown markdown={msg.content} />
          )}
        </div>
      ))}
      {streaming && (
        <div style={{ padding: "4px 0" }}>
          <Spin size="small" />
          <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>生成中…</Text>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}

// ── ExpertQATab ──────────────────────────────────────────────────────────────

function ExpertQATab({
  postReviewCtx,
}: {
  postReviewCtx: { projectId: number; conversationId: number } | null;
}) {
  // phase: "choosing" shows opening question; "chatting" is active conversation
  const [phase, setPhase] = useState<"choosing" | "chatting">("choosing");
  const [strategy, setStrategy] = useState("gap_based");
  const [rqItems, setRqItems] = useState<ReviewQueueItem[]>([]);
  const [rqItemId, setRqItemId] = useState<string | null>(null);
  const [materialId, setMaterialId] = useState<string | null>(null);
  const [docName, setDocName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [roundNumber, setRoundNumber] = useState(1);
  const [newKiIds, setNewKiIds] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const isPostReview = postReviewCtx != null;
  const isDocMode = materialId != null;

  // Opening canned message shown on mount
  const OPENING_MSG: ChatMsg = {
    role: "assistant",
    content: isPostReview
      ? `已关联本次审查结果（项目 #${postReviewCtx!.projectId}）。请描述遗漏或补充发现，或直接点击「开始提取」。`
      : "你好！今天想从哪里开始提取知识？选择一种提取方式，或直接输入你想聊的内容。",
  };

  useEffect(() => {
    setPhase("choosing");
    setMessages([OPENING_MSG]);
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
    .filter((m) => m.role !== "status")
    .map((m) => ({ role: m.role as string, content: m.content }));

  const runStream = async (userText: string) => {
    setMessages((prev) => [...prev, { role: "user", content: userText }]);
    setStreaming(true);
    abortRef.current = new AbortController();

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
              const qs = clarify.questions.map((q, i) => `${i + 1}. ${q}`).join("\n");
              setMessages((prev) => [
                ...prev,
                { role: "status", content: `💡 建议追问方向：\n${qs}` },
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
    } catch (e) {
      if ((e as Error)?.name !== "AbortError") {
        message.error(`提取失败: ${e instanceof Error ? e.message : String(e)}`);
      }
    } finally {
      setStreaming(false);
    }
  };

  // Strategy chip selected → auto-start LLM
  const handleStrategySelect = async (s: typeof STRATEGY_OPTIONS[number]) => {
    setStrategy(s.value);
    setPhase("chatting");
    await runStream(`我想通过「${s.label}」开始——${s.desc}`);
  };

  // User types and sends
  const handleSend = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    if (phase === "choosing") setPhase("chatting");
    await runStream(text);
  };

  // Post-review auto-start
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
  const handleReset = () => {
    handleStop();
    setPhase("choosing");
    setMessages([OPENING_MSG]);
    setRoundNumber(1);
    setNewKiIds([]);
    setMaterialId(null);
    setDocName("");
  };

  return (
    <div style={{ padding: "16px 0" }}>
      <Upload.Dragger
        accept=".md,.html"
        beforeUpload={(file) => { void handleUpload(file); return false; }}
        showUploadList={false}
        disabled={uploading}
        style={{ marginBottom: 16 }}
      >
        <p className="ant-upload-drag-icon">
          {uploading ? <Spin /> : <InboxOutlined style={{ fontSize: 32, color: "#527c5e" }} />}
        </p>
        <p>拖拽或点击上传规则文档（.md / .html）</p>
        <p style={{ fontSize: 12, color: "#888" }}>上传后 LLM 将基于文档内容做知识澄清</p>
      </Upload.Dragger>

      {materialId && (
        <>
          <Alert
            type="info"
            message={`已加载文档：${docName}（material_id: ${materialId}）`}
            style={{ marginBottom: 12 }}
          />
          {docName && (
            <Tag
              closable
              onClose={() => { setMaterialId(null); setDocName(""); }}
              icon={<PaperClipOutlined />}
            >
              {docName}
            </Tag>
          )}
        </div>
      )}

      <ChatArea messages={messages} streaming={streaming} />

      {/* Strategy chips — shown while choosing */}
      {phase === "choosing" && !isPostReview && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
          {STRATEGY_OPTIONS.map((s) => (
            <Button
              key={s.value}
              size="small"
              onClick={() => void handleStrategySelect(s)}
              disabled={streaming}
              style={{ borderRadius: 16 }}
            >
              {s.label}
            </Button>
          ))}
        </div>
      )}

      {/* Input row */}
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <div style={{ flex: 1, position: "relative" }}>
          <TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void handleSend(); }
            }}
            placeholder={
              isPostReview
                ? "描述遗漏的问题或补充发现（Shift+Enter 换行）"
                : "输入您的想法或回答 LLM 的问题（Shift+Enter 换行）"
            }
            autoSize={{ minRows: 2, maxRows: 6 }}
            disabled={streaming}
          />
          {/* Inline upload button */}
          {!isPostReview && (
            <Upload
              accept=".md,.html"
              beforeUpload={(file) => { void handleUpload(file); return false; }}
              showUploadList={false}
              disabled={uploading || streaming}
            >
              <Tooltip title="上传文档（.md / .html）开启文档澄清模式">
                <Button
                  icon={uploading ? <Spin size="small" /> : <PaperClipOutlined />}
                  size="small"
                  type="text"
                  disabled={uploading || streaming}
                  style={{ position: "absolute", bottom: 6, right: 6 }}
                />
              </Tooltip>
            </Upload>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {isPostReview && !streaming && messages.filter((m) => m.role !== "status" && m.role !== "assistant").length === 0 ? (
            <Button type="primary" onClick={() => void handlePostReviewStart()}>开始提取</Button>
          ) : (
            <Button type="primary" onClick={() => void handleSend()} disabled={!input.trim() || streaming}>
              发送
            </Button>
          )}
          {streaming
            ? <Button danger onClick={handleStop}>停止</Button>
            : <Button onClick={handleReset} disabled={messages.length <= 1}>清空</Button>
          }
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

// ── ExtractionPage (main) ─────────────────────────────────────────────────────

export default function ExtractionPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("extract");
  const [profile, setProfile] = useState<ExpertProfileData | null>(null);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [postReviewCtx, setPostReviewCtx] = useState<{ projectId: number; conversationId: number } | null>(null);

  useEffect(() => {
    const raw = window.sessionStorage.getItem("aika_post_review_ctx");
    if (raw) {
      try {
        const ctx = JSON.parse(raw) as { projectId: number; conversationId: number };
        window.sessionStorage.removeItem("aika_post_review_ctx");
        setPostReviewCtx(ctx);
        setActiveTab("extract");
      } catch { /* ignore */ }
    }
  }, []);

  useEffect(() => {
    getExpertProfile()
      .then((p) => {
        setProfile(p);
        if (!p.domains.length && !p.background) setProfileModalOpen(true);
      })
      .catch(() => setProfileModalOpen(true));
  }, []);

  const handleSaveProfile = async (data: ExpertProfileData) => {
    const saved = await putExpertProfile(data);
    setProfile(saved);
    message.success("专家背景已保存");
  };

  const tabItems: Array<{ key: ActiveTab; label: string; children: React.ReactNode }> = [
    {
      key: "extract",
      label: "专家答问",
      children: (
        <ExpertQATab
          postReviewCtx={activeTab === "extract" ? postReviewCtx : null}
        />
      ),
    },
    {
      key: "pending",
      label: "待批准规则",
      children: <PendingRulesTab />,
    },
  ];

  return (
    <div className="extraction-page">
      <div className="extraction-page-header">
        <Title level={4} style={{ margin: 0 }}>知识提取</Title>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {profile && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              领域：{profile.domains.length > 0 ? profile.domains.join("、") : "未设置"}
            </Text>
          )}
          <Button
            icon={<UserOutlined />}
            size="small"
            onClick={() => setProfileModalOpen(true)}
          >
            专家背景
          </Button>
        </div>
      </div>

      <div style={{ borderBottom: "1px solid var(--color-border, #e0e0d8)", marginBottom: 0 }}>
        <div style={{ display: "flex", gap: 0 }}>
          {tabItems.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                padding: "8px 20px",
                border: "none",
                borderBottom: activeTab === tab.key ? "2px solid #527c5e" : "2px solid transparent",
                background: "none",
                cursor: "pointer",
                fontWeight: activeTab === tab.key ? 600 : 400,
                color: activeTab === tab.key ? "#527c5e" : "#666",
                fontSize: 14,
                transition: "all 0.15s",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: "0 4px" }}>
        {tabItems.find((t) => t.key === activeTab)?.children}
      </div>

      <ExpertProfileModal
        open={profileModalOpen}
        profile={profile}
        onSave={handleSaveProfile}
        onClose={() => setProfileModalOpen(false)}
      />
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
