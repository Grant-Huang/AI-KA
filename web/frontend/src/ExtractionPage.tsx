import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert, Badge, Button, Card, Divider, Empty, Input,
  Modal, Radio, Select, Space, Spin, Table, Tag,
  Tooltip, Typography, Upload, message,
} from "antd";

import {
  CheckOutlined, CloseOutlined, DeleteOutlined, InboxOutlined,
  ReloadOutlined, UserOutlined, WarningOutlined,
} from "@ant-design/icons";
import type {
  ExpertProfileData, PendingRuleItem, ReviewQueueItem,
} from "./api";
import {
  approvePendingRule, deleteReviewQueueItem, getExpertProfile,
  getPendingRules, getReviewQueue, patchReviewQueueItem, postActiveExtractionStream,
  postDocExtractionStream, putExpertProfile, rejectPendingRule, uploadExtractionMaterial,
} from "./api";
import SimpleMarkdown from "./SimpleMarkdown";

const { Text, Title, Paragraph } = Typography;
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
type ActiveTab = "queue" | "extract" | "upload" | "pending";

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

// ── ReviewQueueTab ────────────────────────────────────────────────────────────

function ReviewQueueTab({
  onStartExtraction,
}: {
  onStartExtraction: (item: ReviewQueueItem) => void;
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
          <Button
            type="link" size="small"
            onClick={() => onStartExtraction(row)}
            disabled={row.status === "approved" || row.status === "rejected"}
          >
            开始提取
          </Button>
          <Button
            type="link" size="small"
            onClick={() => handleStatus(row.id, row.status === "archived" ? "pending_review" : "archived")}
          >
            {row.status === "archived" ? "恢复" : "归档"}
          </Button>
          <Button
            type="link" size="small" danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(row.id)}
          />
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: "16px 0" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 12, gap: 8 }}>
        <Title level={5} style={{ margin: 0 }}>审查队列</Title>
        <Button icon={<ReloadOutlined />} size="small" onClick={load} loading={loading}>刷新</Button>
        <Text type="secondary" style={{ marginLeft: "auto", fontSize: 12 }}>
          按出现次数降序 — 高频线索优先提取
        </Text>
      </div>
      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      {!loading && items.length === 0 ? (
        <Empty
          description="暂无队列条目。完成一次项目审查后，LLM 会自动提取泛化知识线索到此队列。"
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
      {messages.length === 0 ? (
        <Text type="secondary" style={{ fontSize: 13 }}>
          选择策略并输入您的想法或问题，LLM 将开始提问。
        </Text>
      ) : (
        messages.map((msg, i) => (
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
              <SimpleMarkdown text={msg.content} />
            )}
          </div>
        ))
      )}
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

// ── ActiveExtractionTab ──────────────────────────────────────────────────────

function ActiveExtractionTab({ initialRQItem }: { initialRQItem: ReviewQueueItem | null }) {
  const [strategy, setStrategy] = useState("gap_based");
  const [rqItem, setRqItem] = useState<ReviewQueueItem | null>(initialRQItem);
  const [rqItems, setRqItems] = useState<ReviewQueueItem[]>([]);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [roundNumber, setRoundNumber] = useState(1);
  const [newKiIds, setNewKiIds] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (initialRQItem) {
      setRqItem(initialRQItem);
      setMessages([]);
      setRoundNumber(1);
    }
  }, [initialRQItem]);

  useEffect(() => {
    getReviewQueue().then(({ items }) => setRqItems(items)).catch(() => {});
  }, []);

  const priorMessages = messages
    .filter((m) => m.role !== "status")
    .map((m) => ({ role: m.role as string, content: m.content }));

  const handleSend = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setStreaming(true);

    abortRef.current = new AbortController();
    let assistantText = "";

    try {
      await postActiveExtractionStream(
        {
          user_input: text,
          strategy,
          review_queue_item_id: rqItem?.id ?? null,
          prior_messages: priorMessages,
          round_number: roundNumber,
        },
        (ev) => {
          if (ev.type === "status") {
            setMessages((prev) => [...prev, { role: "status", content: String(ev.msg ?? "") }]);
          } else if (ev.type === "text") {
            const chunk = String(ev.text ?? "");
            assistantText += chunk;
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
        abortRef.current.signal,
      );
    } catch (e) {
      if ((e as Error)?.name !== "AbortError") {
        message.error(`提取失败: ${e instanceof Error ? e.message : String(e)}`);
      }
    } finally {
      setStreaming(false);
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
    setStreaming(false);
  };

  const handleReset = () => {
    handleStop();
    setMessages([]);
    setRoundNumber(1);
    setNewKiIds([]);
  };

  return (
    <div style={{ padding: "16px 0" }}>
      <div style={{ display: "flex", gap: 16, marginBottom: 16, flexWrap: "wrap" }}>
        {/* Strategy */}
        <Card size="small" style={{ flex: "0 0 auto", minWidth: 260 }}>
          <div style={{ marginBottom: 8 }}>
            <Text strong>提取策略</Text>
          </div>
          <Radio.Group
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            style={{ display: "flex", flexDirection: "column", gap: 6 }}
          >
            {STRATEGY_OPTIONS.map((opt) => (
              <Radio key={opt.value} value={opt.value}>
                <span style={{ fontWeight: 500 }}>{opt.label}</span>
                <br />
                <span style={{ fontSize: 11, color: "#888" }}>{opt.desc}</span>
              </Radio>
            ))}
          </Radio.Group>
        </Card>
        {/* RQ Item selector */}
        <Card size="small" style={{ flex: 1, minWidth: 200 }}>
          <div style={{ marginBottom: 8 }}>
            <Text strong>关联队列条目（可选）</Text>
          </div>
          <Select
            value={rqItem?.id ?? null}
            onChange={(val) => setRqItem(rqItems.find((x) => x.id === val) ?? null)}
            placeholder="选择 Review Queue 条目..."
            style={{ width: "100%" }}
            allowClear
            onClear={() => setRqItem(null)}
            options={rqItems
              .filter((x) => x.status !== "rejected" && x.status !== "archived")
              .map((x) => ({
                value: x.id,
                label: `[${x.focus_id}] ${x.suggestion.slice(0, 50)}… (×${x.occurrences})`,
              }))}
          />
          {rqItem && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {rqItem.suggestion}
              </Text>
            </div>
          )}
          <div style={{ marginTop: 12 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              第 {roundNumber} 轮 · 满意度 ≥ 85% 或最多 5 轮后自动生成知识条目
            </Text>
          </div>
        </Card>
      </div>

      {newKiIds.length > 0 && (
        <Alert
          type="success"
          message={`已生成 ${newKiIds.length} 条知识条目，请到「待批准规则」页面审批后写入规则库。`}
          style={{ marginBottom: 12 }}
          closable
        />
      )}

      <ChatArea messages={messages} streaming={streaming} />

      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
          placeholder="输入您的想法或回答 LLM 的问题（Shift+Enter 换行）"
          autoSize={{ minRows: 2, maxRows: 6 }}
          disabled={streaming}
          style={{ flex: 1 }}
        />
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <Button
            type="primary"
            onClick={handleSend}
            disabled={!input.trim() || streaming}
          >
            发送
          </Button>
          {streaming ? (
            <Button danger onClick={handleStop}>停止</Button>
          ) : (
            <Button onClick={handleReset} disabled={messages.length === 0}>清空</Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── DocUploadTab ─────────────────────────────────────────────────────────────

function DocUploadTab() {
  const [materialId, setMaterialId] = useState<string | null>(null);
  const [docName, setDocName] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [newKiIds, setNewKiIds] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const res = await uploadExtractionMaterial(file);
      setMaterialId(res.material_id);
      setDocName(res.original_name);
      setMessages([]);
      setNewKiIds([]);
      message.success(`已上传「${res.original_name}」，可开始提取。`);
    } catch (e) {
      message.error(`上传失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(false);
    }
    return false; // prevent antd default upload
  };

  const sendText = async (text: string) => {
    if (!materialId || streaming || !text.trim()) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setStreaming(true);
    abortRef.current = new AbortController();
    const currentPrior = messages
      .filter((m) => m.role !== "status")
      .map((m) => ({ role: m.role as string, content: m.content }));

    try {
      await postDocExtractionStream(
        { material_id: materialId, user_input: text, strategy: "gap_based", prior_messages: currentPrior },
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
          } else if (ev.type === "final") {
            const kiCount = Number((ev as any).new_ki_count ?? 0);
            if (kiCount > 0) {
              setMessages((prev) => [
                ...prev,
                { role: "status", content: `✓ 生成 ${kiCount} 条知识条目，已发送到「待批准规则」。` },
              ]);
            }
          }
        },
        abortRef.current.signal,
      );
    } catch (e) {
      if ((e as Error)?.name !== "AbortError") {
        message.error(`提取失败: ${e instanceof Error ? e.message : String(e)}`);
      }
    } finally {
      setStreaming(false);
    }
  };

  const handleSend = () => sendText(input.trim());

  return (
    <div style={{ padding: "16px 0" }}>
      <Upload.Dragger
        accept=".md,.txt,.docx,.pdf"
        beforeUpload={(file) => { void handleUpload(file); return false; }}
        showUploadList={false}
        disabled={uploading}
        style={{ marginBottom: 16 }}
      >
        <p className="ant-upload-drag-icon">
          {uploading ? <Spin /> : <InboxOutlined style={{ fontSize: 32, color: "#527c5e" }} />}
        </p>
        <p>拖拽或点击上传规则文档（.md / .txt / .docx / .pdf）</p>
        <p style={{ fontSize: 12, color: "#888" }}>上传后 LLM 将基于文档内容做知识澄清</p>
      </Upload.Dragger>

      {materialId && (
        <>
          <Alert
            type="info"
            message={`已加载文档：${docName}（material_id: ${materialId}）`}
            style={{ marginBottom: 12 }}
          />
          {newKiIds.length > 0 && (
            <Alert
              type="success"
              message={`已生成 ${newKiIds.length} 条知识条目，请到「待批准规则」页面审批。`}
              style={{ marginBottom: 12 }}
              closable
            />
          )}
          <ChatArea messages={messages} streaming={streaming} />
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void handleSend(); }
              }}
              placeholder="输入问题或直接发送「开始提取」（Shift+Enter 换行）"
              autoSize={{ minRows: 2, maxRows: 6 }}
              disabled={streaming || !materialId}
              style={{ flex: 1 }}
            />
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <Button type="primary" onClick={handleSend} disabled={!input.trim() || streaming}>发送</Button>
              {streaming && <Button danger onClick={() => { abortRef.current?.abort(); setStreaming(false); }}>停止</Button>}
            </div>
          </div>
          <div style={{ marginTop: 8 }}>
            <Button
              size="small"
              onClick={() => void sendText("请开始分析文档并提取知识")}
              disabled={streaming || !materialId}
            >
              一键开始提取
            </Button>
          </div>
        </>
      )}
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
            onClick={() => handleApprove(row.id)}
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
          description="暂无待批准规则。通过主动提取或文档上传生成知识条目后，它们会出现在此处。"
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
        onOk={handleReject}
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
  const [activeTab, setActiveTab] = useState<ActiveTab>("queue");
  const [profile, setProfile] = useState<ExpertProfileData | null>(null);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [rqItemForExtraction, setRqItemForExtraction] = useState<ReviewQueueItem | null>(null);

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

  const handleStartExtraction = (item: ReviewQueueItem) => {
    setRqItemForExtraction(item);
    setActiveTab("extract");
  };

  const tabItems = [
    {
      key: "queue",
      label: `审查队列`,
      children: <ReviewQueueTab onStartExtraction={handleStartExtraction} />,
    },
    {
      key: "extract",
      label: "主动提取",
      children: <ActiveExtractionTab initialRQItem={activeTab === "extract" ? rqItemForExtraction : null} />,
    },
    {
      key: "upload",
      label: "文档上传",
      children: <DocUploadTab />,
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

      <div
        style={{
          borderBottom: "1px solid var(--color-border, #e0e0d8)",
          marginBottom: 0,
        }}
      >
        <div
          style={{
            display: "flex",
            gap: 0,
            borderBottom: "none",
          }}
        >
          {tabItems.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key as ActiveTab)}
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
