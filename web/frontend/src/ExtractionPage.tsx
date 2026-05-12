import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Badge, Button, Card, Divider, Empty, Input,
  Modal, Progress, Segmented, Select, Space, Spin, Steps, Table, Tag,
  Tooltip, Typography, Upload, message,
} from "antd";
import {
  CheckOutlined, CloseOutlined, DeleteOutlined, FileTextOutlined,
  InboxOutlined, MessageOutlined, ReloadOutlined, UnorderedListOutlined,
  UserOutlined, WarningOutlined,
} from "@ant-design/icons";
import type {
  ExpertProfileData, KnowledgeItem, PendingRuleItem, ReviewQueueItem,
} from "./api";
import {
  approvePendingRule, deleteReviewQueueItem, getExpertProfile,
  getPendingRules, getReviewQueue, patchKnowledgeItem, patchReviewQueueItem,
  postActiveExtractionStream, postDocExtractionStream, postReviewExtractionStream,
  putExpertProfile, rejectPendingRule, submitKnowledgeItem, uploadExtractionMaterial,
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

// Map focus_id prefixes to domain labels for dynamic suggestions
const FOCUS_ID_DOMAIN_MAP: Record<string, string> = {
  req: "需求分析", risk: "风险管理", gap: "项目管理",
  int: "系统集成", qa: "质量保证", sec: "安全合规",
  ops: "运维管理", pm: "项目管理", data: "数据分析",
  prod: "产品设计", proc: "供应链管理", cs: "客户服务",
};

const STRATEGY_OPTIONS = [
  { value: "gap_based", label: "规则差距", desc: "对比审查队列与现有规则，识别空白" },
  { value: "fuzzy_signal", label: "模糊信号", desc: "澄清模糊印象，转化为清晰规则" },
  { value: "critical_incident", label: "关键事件", desc: "从具体案例提炼可复用规律" },
  { value: "reverse_validation", label: "反向验证", desc: "验证或反驳现有规则的适用边界" },
];

const CONFIDENCE_COLOR: Record<string, string> = {
  high: "green", medium: "orange", low: "red",
};

// ── Types ────────────────────────────────────────────────────────────────────

type ChatMsg = { role: "user" | "assistant" | "status"; content: string };
type ActiveTab = "workbench" | "pending";
type StartMode = "queue" | "free" | "doc";
type KiItemState = {
  kid: string;
  item: KnowledgeItem;
  localStatus: "pending" | "approved" | "rejected" | "edited";
  editedTitle?: string;
  editedContent?: string;
};

// ── InlineKnowledgeCards ─────────────────────────────────────────────────────

function InlineKnowledgeCards({
  items,
  onUpdate,
}: {
  items: KiItemState[];
  onUpdate: (kid: string, updates: Partial<KiItemState>) => void;
}) {
  const [editTarget, setEditTarget] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editSaving, setEditSaving] = useState(false);
  const [actionKid, setActionKid] = useState<string | null>(null);

  if (items.length === 0) return null;

  const pendingCount = items.filter(
    (i) => i.localStatus === "pending" || i.localStatus === "edited",
  ).length;

  const handleApprove = async (kid: string) => {
    setActionKid(kid);
    try {
      await submitKnowledgeItem(kid);
      onUpdate(kid, { localStatus: "approved" });
      message.success("知识条目已确认，写入待批准规则");
    } catch (e) {
      message.error(`确认失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setActionKid(null);
    }
  };

  const handleReject = async (kid: string) => {
    setActionKid(kid);
    try {
      await patchKnowledgeItem(kid, { status: "rejected" });
      onUpdate(kid, { localStatus: "rejected" });
      message.success("已不采纳");
    } catch (e) {
      message.error(`操作失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setActionKid(null);
    }
  };

  const openEdit = (ki: KiItemState) => {
    setEditTarget(ki.kid);
    setEditTitle(ki.editedTitle ?? ki.item.title ?? "");
    setEditContent(ki.editedContent ?? ki.item.content ?? "");
  };

  const handleSaveEdit = async () => {
    if (!editTarget) return;
    setEditSaving(true);
    try {
      await patchKnowledgeItem(editTarget, { title: editTitle, content: editContent });
      onUpdate(editTarget, { localStatus: "edited", editedTitle: editTitle, editedContent: editContent });
      message.success("已保存修改");
      setEditTarget(null);
    } catch (e) {
      message.error(`保存失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setEditSaving(false);
    }
  };

  const CONF_LABEL: Record<string, string> = { high: "高", medium: "中", low: "低" };

  return (
    <div style={{ marginTop: 12 }}>
      <Divider orientation="left" plain style={{ fontSize: 12, color: "#888", margin: "8px 0" }}>
        生成的知识条目（{pendingCount} 条待处理 / 共 {items.length} 条）
      </Divider>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {items.map((ki) => {
          const title = ki.editedTitle ?? ki.item.title ?? "";
          const content = ki.editedContent ?? ki.item.content ?? "";
          const conf = ki.item.confidence ?? "medium";
          const focusId = ki.item.extraction_focus_id ?? "";
          const isPending = ki.localStatus === "pending" || ki.localStatus === "edited";

          return (
            <Card
              key={ki.kid}
              size="small"
              style={{
                borderLeft: `3px solid ${
                  ki.localStatus === "approved" ? "#52c41a"
                    : ki.localStatus === "rejected" ? "#ff4d4f"
                    : "#1677ff"
                }`,
                opacity: isPending ? 1 : 0.65,
                fontSize: 12,
              }}
              title={
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <Tag color={CONFIDENCE_COLOR[conf]} style={{ fontSize: 11 }}>
                    {CONF_LABEL[conf] ?? conf}置信
                  </Tag>
                  {focusId && <Tag style={{ fontSize: 11 }}>{focusId}</Tag>}
                  {ki.localStatus === "edited" && <Tag color="blue" style={{ fontSize: 11 }}>已修改</Tag>}
                  <Text style={{ fontSize: 13, fontWeight: 500 }}>{title}</Text>
                </div>
              }
              extra={
                isPending ? (
                  <Space size={4}>
                    <Button
                      size="small" type="primary" icon={<CheckOutlined />}
                      loading={actionKid === ki.kid}
                      onClick={() => void handleApprove(ki.kid)}
                    >
                      确认入库
                    </Button>
                    <Button size="small" onClick={() => openEdit(ki)}>修改</Button>
                    <Button
                      size="small" danger icon={<CloseOutlined />}
                      loading={actionKid === ki.kid}
                      onClick={() => void handleReject(ki.kid)}
                    >
                      不采纳
                    </Button>
                  </Space>
                ) : (
                  <Tag color={ki.localStatus === "approved" ? "success" : "error"}>
                    {ki.localStatus === "approved" ? "已确认" : "已不采纳"}
                  </Tag>
                )
              }
            >
              <Text style={{ fontSize: 12, whiteSpace: "pre-wrap", color: "#444" }}>
                {content.length > 220 ? content.slice(0, 220) + "…" : content}
              </Text>
            </Card>
          );
        })}
      </div>

      <Modal
        title="修改知识条目"
        open={!!editTarget}
        onCancel={() => setEditTarget(null)}
        onOk={() => void handleSaveEdit()}
        okText="保存修改"
        cancelText="取消"
        confirmLoading={editSaving}
        width={600}
      >
        <div style={{ marginBottom: 12 }}>
          <Text strong>标题</Text>
          <Input
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            style={{ marginTop: 4 }}
          />
        </div>
        <div>
          <Text strong>内容</Text>
          <TextArea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            rows={6}
            style={{ marginTop: 4 }}
          />
        </div>
      </Modal>
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
          选择开始方式后，LLM 将主动提问，您只需回答。
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
              <SimpleMarkdown markdown={msg.content} />
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

// ── ExpertOnboarding ─────────────────────────────────────────────────────────

function ExpertOnboarding({
  queueItems,
  onComplete,
}: {
  queueItems: ReviewQueueItem[];
  onComplete: (profile: ExpertProfileData) => void;
}) {
  const [currentStep, setCurrentStep] = useState(0);
  const [domains, setDomains] = useState<string[]>([]);
  const [background, setBackground] = useState("");
  const [saving, setSaving] = useState(false);

  // Derive domain suggestions from queue focus_ids
  const suggestedOptions = useMemo(() => {
    const fromQueue = [...new Set(
      queueItems.map((x) => {
        const prefix = x.focus_id.split("-")[0].split("_")[0].toLowerCase();
        return FOCUS_ID_DOMAIN_MAP[prefix] ?? null;
      }).filter(Boolean),
    )] as string[];
    const merged = [...new Set([...fromQueue, ...DOMAIN_OPTIONS])];
    return merged.slice(0, 12);
  }, [queueItems]);

  const handleComplete = async () => {
    setSaving(true);
    try {
      const saved = await putExpertProfile({ domains, background });
      message.success("专家画像已保存，开始知识提取！");
      onComplete(saved);
    } catch (e) {
      message.error(`保存失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const steps = [
    {
      title: "专业领域",
      description: "选择擅长领域",
    },
    {
      title: "工作背景",
      description: "简述经验与专长",
    },
    {
      title: "确认画像",
      description: "开始知识提取",
    },
  ];

  return (
    <div style={{
      maxWidth: 600, margin: "0 auto", padding: "32px 24px",
    }}>
      <div style={{ textAlign: "center", marginBottom: 32 }}>
        <Title level={3} style={{ margin: 0, color: "#527c5e" }}>欢迎使用知识提取</Title>
        <Paragraph type="secondary" style={{ marginTop: 8 }}>
          请花 2 分钟完成专家画像，LLM 将据此优化提问策略，让每次提取更高效。
        </Paragraph>
        {queueItems.length > 0 && (
          <Alert
            type="info"
            style={{ marginTop: 12, textAlign: "left" }}
            message={
              <span>
                当前审查队列有 <strong>{queueItems.length}</strong> 条线索，
                涉及关注点：{[...new Set(queueItems.map((x) => x.focus_id))].slice(0, 5).join("、")}
                {queueItems.length > 5 ? " 等" : ""}。
                领域建议已根据队列内容动态生成。
              </span>
            }
          />
        )}
      </div>

      <Steps current={currentStep} items={steps} style={{ marginBottom: 32 }} size="small" />

      {currentStep === 0 && (
        <Card title="您擅长哪些业务领域？" size="small">
          <Paragraph type="secondary" style={{ fontSize: 13 }}>
            多选，LLM 将优先在这些领域提问；选择越精准，知识提取越有针对性。
          </Paragraph>
          <Select
            mode="multiple"
            value={domains}
            onChange={setDomains}
            options={suggestedOptions.map((d) => ({ value: d, label: d }))}
            placeholder="从列表选择，或直接输入自定义领域..."
            style={{ width: "100%", marginBottom: 16 }}
            allowClear
          />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button
              type="primary"
              onClick={() => setCurrentStep(1)}
              disabled={domains.length === 0}
            >
              下一步
            </Button>
          </div>
        </Card>
      )}

      {currentStep === 1 && (
        <Card title="工作背景（可选）" size="small">
          <Paragraph type="secondary" style={{ fontSize: 13 }}>
            描述您的工作年限、典型项目类型、最常遇到的挑战等，帮助 LLM 更好地理解您的视角。
          </Paragraph>
          <TextArea
            value={background}
            onChange={(e) => setBackground(e.target.value)}
            placeholder="例：10 年 IT 项目管理经验，主要负责制造业 MES 系统实施，熟悉固定总价合同风险管理…（可跳过）"
            rows={5}
            showCount
            maxLength={500}
            style={{ marginBottom: 16 }}
          />
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <Button onClick={() => setCurrentStep(0)}>上一步</Button>
            <Button type="primary" onClick={() => setCurrentStep(2)}>
              下一步
            </Button>
          </div>
        </Card>
      )}

      {currentStep === 2 && (
        <Card title="确认专家画像" size="small">
          <div style={{ marginBottom: 16 }}>
            <Text strong>擅长领域：</Text>
            <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 6 }}>
              {domains.map((d) => (
                <Tag key={d} color="green">{d}</Tag>
              ))}
            </div>
          </div>
          {background && (
            <div style={{ marginBottom: 16 }}>
              <Text strong>工作背景：</Text>
              <Paragraph style={{ marginTop: 4, fontSize: 13, color: "#555" }}>{background}</Paragraph>
            </div>
          )}
          <Alert
            type="success"
            message="画像保存后可随时在右上角「专家画像」按钮中修改。"
            style={{ marginBottom: 16 }}
          />
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <Button onClick={() => setCurrentStep(1)}>上一步</Button>
            <Button type="primary" loading={saving} onClick={() => void handleComplete()}>
              保存并开始提取
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

// ── WorkbenchTab ─────────────────────────────────────────────────────────────

function WorkbenchTab({
  initialRQItem,
  postReviewCtx,
}: {
  initialRQItem: ReviewQueueItem | null;
  postReviewCtx: { projectId: number; conversationId: number } | null;
}) {
  const isPostReview = postReviewCtx != null;

  const [startMode, setStartMode] = useState<StartMode>(
    isPostReview ? "free" : initialRQItem ? "queue" : "free",
  );

  // Mode-specific state
  const [strategy, setStrategy] = useState("gap_based");
  const [rqItem, setRqItem] = useState<ReviewQueueItem | null>(initialRQItem);
  const [rqItems, setRqItems] = useState<ReviewQueueItem[]>([]);
  const [materialId, setMaterialId] = useState<string | null>(null);
  const [docName, setDocName] = useState("");
  const [uploading, setUploading] = useState(false);

  // Shared conversation state
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [roundNumber, setRoundNumber] = useState(1);
  const [newKiItems, setNewKiItems] = useState<KiItemState[]>([]);
  const [satisfaction, setSatisfaction] = useState<number | null>(null);
  const [itemComplete, setItemComplete] = useState(false);
  const [coachHint, setCoachHint] = useState<{
    whisper: string;
    expert_type_signal?: string;
    coverage_gaps?: string[];
    current_momentum?: string;
    flag?: string | null;
  } | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    getReviewQueue().then(({ items }) => setRqItems(items)).catch(() => {});
  }, []);

  useEffect(() => {
    if (initialRQItem) {
      setRqItem(initialRQItem);
      setStartMode("queue");
    }
  }, [initialRQItem]);

  useEffect(() => {
    if (isPostReview) {
      setStartMode("free");
      setMessages([{
        role: "status",
        content: `已关联审查会话（项目 #${postReviewCtx!.projectId}，会话 #${postReviewCtx!.conversationId}）。请描述本次审查的遗漏或补充发现。`,
      }]);
    }
  }, [isPostReview, postReviewCtx]);

  const priorMessages = messages
    .filter((m) => m.role !== "status")
    .map((m) => ({ role: m.role as string, content: m.content }));

  const handleModeChange = (mode: StartMode) => {
    setStartMode(mode);
    setMessages([]);
    setRoundNumber(1);
    setNewKiItems([]);
    setSatisfaction(null);
    setItemComplete(false);
    setCoachHint(null);
  };

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const res = await uploadExtractionMaterial(file);
      setMaterialId(res.material_id);
      setDocName(res.original_name);
      setMessages([]);
      setNewKiItems([]);
      message.success(`已上传「${res.original_name}」，可开始提取。`);
    } catch (e) {
      message.error(`上传失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(false);
    }
  };

  const handleSend = async (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || streaming) return;
    if (startMode === "doc" && !materialId) {
      message.warning("请先上传文档");
      return;
    }
    if (overrideText === undefined) setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setStreaming(true);
    setItemComplete(false);
    abortRef.current = new AbortController();
    let assistantText = "";

    const handleEvent = (ev: Record<string, unknown>) => {
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
        const item = (ev as any).item as KnowledgeItem | undefined;
        if (kid && item) {
          setNewKiItems((prev) =>
            prev.some((x) => x.kid === kid)
              ? prev
              : [...prev, { kid, item, localStatus: "pending" }],
          );
        }
      } else if (ev.type === "clarify") {
        const clarify = (ev as any).clarify as { questions?: string[] } | undefined;
        if (clarify?.questions?.length) {
          const qs = clarify.questions.map((q: string, i: number) => `${i + 1}. ${q}`).join("\n");
          setMessages((prev) => [...prev, { role: "status", content: `💡 建议追问方向：\n${qs}` }]);
        }
      } else if (ev.type === "coach_hint") {
        const hint = ev as any;
        if (hint.whisper) {
          setCoachHint({
            whisper: String(hint.whisper),
            expert_type_signal: hint.expert_type_signal ? String(hint.expert_type_signal) : undefined,
            coverage_gaps: Array.isArray(hint.coverage_gaps) ? hint.coverage_gaps.map(String) : undefined,
            current_momentum: hint.current_momentum ? String(hint.current_momentum) : undefined,
            flag: hint.flag ? String(hint.flag) : null,
          });
        }
      } else if (ev.type === "final") {
        const sat = (ev as any).satisfaction as number | null;
        const autoAdv = Boolean((ev as any).auto_advance);
        const kiCount = Number((ev as any).new_ki_count ?? 0);
        if (sat !== null) setSatisfaction(sat);
        if (autoAdv) setItemComplete(true);
        let msg = "";
        if (kiCount > 0) msg += `✓ 生成 ${kiCount} 条知识条目，请在下方审批。`;
        if (autoAdv) msg += "  本条知识已完整提炼。";
        else if (sat !== null && sat < 0.85) msg += `  当前满意度 ${Math.round(sat * 100)}%，可继续追问。`;
        if (msg) setMessages((prev) => [...prev, { role: "status", content: msg }]);
        setRoundNumber((n) => n + 1);
      }
    };

    try {
      if (isPostReview) {
        await postReviewExtractionStream(
          postReviewCtx!.projectId,
          postReviewCtx!.conversationId,
          { user_input: text, prior_messages: priorMessages },
          handleEvent as any,
          abortRef.current.signal,
        );
      } else if (startMode === "doc") {
        await postDocExtractionStream(
          { material_id: materialId!, user_input: text, strategy: "gap_based", prior_messages: priorMessages },
          handleEvent as any,
          abortRef.current.signal,
        );
      } else {
        await postActiveExtractionStream(
          {
            user_input: text,
            strategy,
            review_queue_item_id: startMode === "queue" ? (rqItem?.id ?? null) : null,
            prior_messages: priorMessages,
            round_number: roundNumber,
          },
          handleEvent as any,
          abortRef.current.signal,
        );
      }
    } catch (e) {
      if ((e as Error)?.name !== "AbortError") {
        message.error(`提取失败: ${e instanceof Error ? e.message : String(e)}`);
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
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
    setNewKiItems([]);
    setSatisfaction(null);
    setItemComplete(false);
    setCoachHint(null);
  };

  const handleKiUpdate = (kid: string, updates: Partial<KiItemState>) => {
    setNewKiItems((prev) => prev.map((x) => (x.kid === kid ? { ...x, ...updates } : x)));
  };

  const canSend = input.trim().length > 0 && !streaming
    && (startMode !== "doc" || materialId != null);

  return (
    <div style={{ padding: "16px 0" }}>
      {/* Post-review context banner */}
      {isPostReview && (
        <Card size="small" style={{ marginBottom: 16, background: "#f0f9f2", borderColor: "#b7eb8f" }}>
          <Text strong style={{ color: "#389e0d" }}>审查后提取模式</Text>
          <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
            项目 #{postReviewCtx!.projectId} · 会话 #{postReviewCtx!.conversationId}
          </Text>
          <div style={{ marginTop: 4, fontSize: 12, color: "#555" }}>
            描述本次审查的遗漏或补充发现，LLM 将帮您提炼为可复用规则。
          </div>
        </Card>
      )}

      {/* Mode selector */}
      {!isPostReview && (
        <div style={{ marginBottom: 16 }}>
          <Segmented
            value={startMode}
            onChange={(v) => handleModeChange(v as StartMode)}
            options={[
              { label: "从审查队列", value: "queue", icon: <UnorderedListOutlined /> },
              { label: "自由提取", value: "free", icon: <MessageOutlined /> },
              { label: "文档澄清", value: "doc", icon: <FileTextOutlined /> },
            ]}
          />
        </div>
      )}

      {/* Mode-specific config */}
      {!isPostReview && (
        <div style={{ marginBottom: 16 }}>
          {startMode === "queue" && (
            <Card size="small">
              <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-start" }}>
                <div style={{ flex: 1, minWidth: 220 }}>
                  <Text strong style={{ fontSize: 13 }}>关联审查队列条目</Text>
                  <Select
                    value={rqItem?.id ?? null}
                    onChange={(val) => setRqItem(rqItems.find((x) => x.id === val) ?? null)}
                    placeholder="选择一条知识线索开始…"
                    style={{ width: "100%", marginTop: 6 }}
                    allowClear
                    onClear={() => setRqItem(null)}
                    options={rqItems
                      .filter((x) => x.status !== "rejected" && x.status !== "archived")
                      .map((x) => ({
                        value: x.id,
                        label: `[${x.focus_id}] ${x.suggestion.slice(0, 45)}… (×${x.occurrences})`,
                      }))}
                  />
                  {rqItem && (
                    <div style={{ marginTop: 8, padding: "6px 8px", background: "#f5f5f5", borderRadius: 4, fontSize: 12 }}>
                      <Text type="secondary">{rqItem.suggestion}</Text>
                    </div>
                  )}
                </div>
                <div style={{ minWidth: 180 }}>
                  <Text strong style={{ fontSize: 13 }}>提取策略</Text>
                  <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
                    {STRATEGY_OPTIONS.slice(0, 2).map((opt) => (
                      <label key={opt.value} style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 13 }}>
                        <input
                          type="radio"
                          name="strategy-q"
                          value={opt.value}
                          checked={strategy === opt.value}
                          onChange={() => setStrategy(opt.value)}
                        />
                        <span>{opt.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
              <div style={{ marginTop: 8, fontSize: 12, color: "#999" }}>
                第 {roundNumber} 轮 · 满意度 ≥ 85% 后自动生成知识条目
              </div>
            </Card>
          )}

          {startMode === "free" && (
            <Card size="small">
              <Text strong style={{ fontSize: 13 }}>提取策略</Text>
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                {STRATEGY_OPTIONS.map((opt) => (
                  <label key={opt.value} style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="strategy-f"
                      value={opt.value}
                      checked={strategy === opt.value}
                      onChange={() => setStrategy(opt.value)}
                    />
                    <span style={{ fontWeight: 500, fontSize: 13 }}>{opt.label}</span>
                    <span style={{ fontSize: 11, color: "#888" }}>{opt.desc}</span>
                  </label>
                ))}
              </div>
              <div style={{ marginTop: 8, fontSize: 12, color: "#999" }}>
                第 {roundNumber} 轮 · 满意度 ≥ 85% 后自动生成知识条目
              </div>
            </Card>
          )}

          {startMode === "doc" && !materialId && (
            <Upload.Dragger
              accept=".md,.txt,.docx,.pdf"
              beforeUpload={(file) => { void handleUpload(file); return false; }}
              showUploadList={false}
              disabled={uploading}
            >
              <p className="ant-upload-drag-icon">
                {uploading ? <Spin /> : <InboxOutlined style={{ fontSize: 32, color: "#527c5e" }} />}
              </p>
              <p>拖拽或点击上传规则文档（.md / .txt / .docx / .pdf）</p>
              <p style={{ fontSize: 12, color: "#888" }}>上传后 LLM 将基于文档内容做知识澄清</p>
            </Upload.Dragger>
          )}

          {startMode === "doc" && materialId && (
            <Alert
              type="info"
              message={
                <span>
                  已加载文档：<strong>{docName}</strong>
                  <Button
                    type="link"
                    size="small"
                    style={{ fontSize: 12, padding: "0 4px" }}
                    onClick={() => { setMaterialId(null); setDocName(""); handleReset(); }}
                  >
                    更换文档
                  </Button>
                </span>
              }
            />
          )}
        </div>
      )}

      {/* Chat area (shown when doc is uploaded or other modes) */}
      {(startMode !== "doc" || materialId || isPostReview) && (
        <>
          <ChatArea messages={messages} streaming={streaming} />

          {/* Satisfaction progress bar */}
          {satisfaction !== null && (
            <div style={{ marginTop: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
                <Text style={{ fontSize: 12, color: "#888" }}>满意度进度</Text>
                <Text style={{ fontSize: 12, fontWeight: 600, color: satisfaction >= 0.85 ? "#52c41a" : "#fa8c16" }}>
                  {Math.round(satisfaction * 100)}%
                </Text>
                {satisfaction >= 0.85 && (
                  <Tag color="success" style={{ fontSize: 11 }}>已达标</Tag>
                )}
              </div>
              <Progress
                percent={Math.round(satisfaction * 100)}
                size="small"
                strokeColor={satisfaction >= 0.85 ? "#52c41a" : "#fa8c16"}
                showInfo={false}
              />
            </div>
          )}

          {/* Item completion notification */}
          {itemComplete && (
            <Alert
              type="success"
              style={{ marginTop: 8, fontSize: 13 }}
              message="本条知识已完整提炼 ✓ 可在下方审批，然后继续下一条或结束本次会话。"
              closable
              onClose={() => setItemComplete(false)}
            />
          )}

          {/* Coach hint banner */}
          {coachHint && (
            <div style={{
              marginTop: 8, padding: "8px 12px",
              background: "#f6ffed", border: "1px solid #b7eb8f", borderRadius: 6,
              display: "flex", alignItems: "flex-start", gap: 8,
            }}>
              <div style={{ flex: 1 }}>
                <Text style={{ fontSize: 11, color: "#52c41a", fontWeight: 600 }}>
                  🎯 场边教练提示（第 {roundNumber - 1} 轮）
                  {coachHint.expert_type_signal && (
                    <Text type="secondary" style={{ fontSize: 11, fontWeight: 400, marginLeft: 6 }}>
                      {coachHint.expert_type_signal}
                    </Text>
                  )}
                  {coachHint.current_momentum && coachHint.current_momentum !== "good" && (
                    <Tag
                      color={coachHint.current_momentum === "stuck" ? "error" : "warning"}
                      style={{ fontSize: 10, marginLeft: 6 }}
                    >
                      {coachHint.current_momentum === "stuck" ? "对话停滞" : "势头减弱"}
                    </Tag>
                  )}
                  {coachHint.flag && (
                    <Tag color="warning" style={{ fontSize: 10, marginLeft: 6 }}>⚠ {coachHint.flag}</Tag>
                  )}
                </Text>
                <div style={{ marginTop: 2 }}>
                  <Text style={{ fontSize: 12 }}>{coachHint.whisper}</Text>
                </div>
                {coachHint.coverage_gaps && coachHint.coverage_gaps.length > 0 && (
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      未覆盖：{coachHint.coverage_gaps.join("、")}
                    </Text>
                  </div>
                )}
              </div>
              <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                <Button
                  size="small"
                  type="link"
                  style={{ fontSize: 11, padding: "0 4px" }}
                  onClick={() => { setInput(coachHint.whisper); setCoachHint(null); }}
                >
                  采纳建议
                </Button>
                <Button
                  size="small"
                  type="text"
                  style={{ fontSize: 11, padding: "0 4px", color: "#999" }}
                  onClick={() => setCoachHint(null)}
                >
                  忽略
                </Button>
              </div>
            </div>
          )}

          <InlineKnowledgeCards items={newKiItems} onUpdate={handleKiUpdate} />

          {/* Input area */}
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
              placeholder={
                isPostReview
                  ? "描述遗漏的问题或补充发现（Shift+Enter 换行）"
                  : startMode === "doc"
                    ? "输入问题或直接发送「开始提取」（Shift+Enter 换行）"
                    : "输入您的想法或回答 LLM 的问题（Shift+Enter 换行）"
              }
              autoSize={{ minRows: 2, maxRows: 6 }}
              disabled={streaming}
              style={{ flex: 1 }}
            />
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {/* Auto-start button for post-review or doc mode with no messages yet */}
              {!streaming && messages.filter((m) => m.role !== "status").length === 0
                && (isPostReview || startMode === "doc") ? (
                <Button
                  type="primary"
                  onClick={() => void handleSend(
                    isPostReview
                      ? "请开始分析，帮我识别可以提炼的知识"
                      : "请开始分析文档并提取知识",
                  )}
                >
                  {isPostReview ? "开始提取" : "一键提取"}
                </Button>
              ) : (
                <Button
                  type="primary"
                  onClick={() => void handleSend()}
                  disabled={!canSend}
                >
                  发送
                </Button>
              )}
              {streaming ? (
                <Button danger onClick={handleStop}>停止</Button>
              ) : (
                <Button
                  onClick={handleReset}
                  disabled={messages.length === 0 && newKiItems.length === 0}
                >
                  清空
                </Button>
              )}
            </div>
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
          <span style={{ cursor: "pointer", color: "#666" }}>
            {v.slice(0, 80)}{v.length > 80 ? "…" : ""}
          </span>
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
          description="暂无待批准规则。通过提取工作台生成知识条目后，它们会出现在此处。"
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
  const [activeTab, setActiveTab] = useState<ActiveTab>("workbench");
  const [profile, setProfile] = useState<ExpertProfileData | null>(null);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [profileLoading, setProfileLoading] = useState(true);
  const [initialRQItem, setInitialRQItem] = useState<ReviewQueueItem | null>(null);
  const [postReviewCtx, setPostReviewCtx] = useState<{ projectId: number; conversationId: number } | null>(null);
  const [queueItemsForOnboarding, setQueueItemsForOnboarding] = useState<ReviewQueueItem[]>([]);

  // Profile modal edit state
  const [editDomains, setEditDomains] = useState<string[]>([]);
  const [editBackground, setEditBackground] = useState("");
  const [editSaving, setEditSaving] = useState(false);

  useEffect(() => {
    // Check sessionStorage for post-review context
    const rawCtx = window.sessionStorage.getItem("aika_post_review_ctx");
    if (rawCtx) {
      try {
        const ctx = JSON.parse(rawCtx) as { projectId: number; conversationId: number };
        window.sessionStorage.removeItem("aika_post_review_ctx");
        setPostReviewCtx(ctx);
      } catch { /* ignore */ }
    }

    // Check sessionStorage for initial RQ item (from review queue drawer)
    const rawRQ = window.sessionStorage.getItem("aika_initial_rq_item");
    if (rawRQ) {
      try {
        const item = JSON.parse(rawRQ) as ReviewQueueItem;
        window.sessionStorage.removeItem("aika_initial_rq_item");
        setInitialRQItem(item);
      } catch { /* ignore */ }
    }
  }, []);

  useEffect(() => {
    setProfileLoading(true);
    Promise.all([
      getExpertProfile().catch(() => null),
      getReviewQueue().catch(() => ({ items: [] })),
    ]).then(([p, q]) => {
      if (!p || (!p.domains.length && !p.background)) {
        // No profile — show onboarding
        setQueueItemsForOnboarding((q as { items: ReviewQueueItem[] }).items);
        setShowOnboarding(true);
      } else {
        setProfile(p);
      }
    }).finally(() => setProfileLoading(false));
  }, []);

  const handleOnboardingComplete = (p: ExpertProfileData) => {
    setProfile(p);
    setShowOnboarding(false);
  };

  const openProfileEdit = () => {
    setEditDomains(profile?.domains ?? []);
    setEditBackground(profile?.background ?? "");
    setProfileModalOpen(true);
  };

  const handleSaveProfile = async () => {
    setEditSaving(true);
    try {
      const saved = await putExpertProfile({ domains: editDomains, background: editBackground });
      setProfile(saved);
      setProfileModalOpen(false);
      message.success("专家画像已更新");
    } catch (e) {
      message.error(`保存失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setEditSaving(false);
    }
  };

  const tabItems: { key: ActiveTab; label: string }[] = [
    { key: "workbench", label: "提取工作台" },
    { key: "pending", label: "待批准规则" },
  ];

  if (profileLoading) {
    return (
      <div className="extraction-page">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 300 }}>
          <Spin tip="加载中…" />
        </div>
      </div>
    );
  }

  if (showOnboarding) {
    return (
      <div className="extraction-page">
        <div className="extraction-page-header">
          <Title level={4} style={{ margin: 0 }}>知识提取</Title>
        </div>
        <div style={{ overflowY: "auto", flex: 1 }}>
          <ExpertOnboarding
            queueItems={queueItemsForOnboarding}
            onComplete={handleOnboardingComplete}
          />
        </div>
      </div>
    );
  }

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
            onClick={openProfileEdit}
          >
            专家画像
          </Button>
        </div>
      </div>

      {/* Tab bar */}
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

      {/* Tab content */}
      <div style={{ overflowY: "auto", flex: 1 }}>
        <div style={{ padding: "0 20px", display: activeTab === "workbench" ? "block" : "none" }}>
          <WorkbenchTab
            initialRQItem={activeTab === "workbench" ? initialRQItem : null}
            postReviewCtx={activeTab === "workbench" ? postReviewCtx : null}
          />
        </div>
        <div style={{ padding: "0 20px", display: activeTab === "pending" ? "block" : "none" }}>
          <PendingRulesTab />
        </div>
      </div>

      {/* Profile edit modal */}
      <Modal
        title="编辑专家画像"
        open={profileModalOpen}
        onCancel={() => setProfileModalOpen(false)}
        onOk={() => void handleSaveProfile()}
        okText="保存"
        cancelText="取消"
        confirmLoading={editSaving}
        width={480}
      >
        <div style={{ marginBottom: 16 }}>
          <Text strong>擅长领域（多选）</Text>
          <Select
            mode="multiple"
            value={editDomains}
            onChange={setEditDomains}
            options={DOMAIN_OPTIONS.map((d) => ({ value: d, label: d }))}
            placeholder="选择领域…"
            style={{ width: "100%", marginTop: 6 }}
            allowClear
          />
        </div>
        <div>
          <Text strong>背景描述</Text>
          <TextArea
            value={editBackground}
            onChange={(e) => setEditBackground(e.target.value)}
            placeholder="简要描述您的工作经验与专长（可选）"
            rows={4}
            showCount
            maxLength={500}
            style={{ marginTop: 6 }}
          />
        </div>
      </Modal>
    </div>
  );
}
