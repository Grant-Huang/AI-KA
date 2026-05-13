import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert, Badge, Button, Card, Divider, Empty, Input,
  Modal, Progress, Radio, Select, Space, Spin, Table, Tag,
  Tooltip, Typography, Upload, message,
} from "antd";
import {
  BulbOutlined, CheckCircleFilled, CheckOutlined, CloseOutlined,
  DeleteOutlined, FileTextOutlined, InboxOutlined, ReloadOutlined,
  UserOutlined, WarningOutlined,
} from "@ant-design/icons";
import type { ExpertProfileData, PendingRuleItem, ReviewQueueItem } from "./api";
import {
  approvePendingRule, deleteReviewQueueItem, getExpertProfile, getPendingRules,
  getReviewQueue, patchReviewQueueItem, postActiveExtractionStream,
  postDocExtractionStream, postExpertInterviewStream, postReviewExtractionStream,
  putExpertProfile, rejectPendingRule, uploadExtractionMaterial,
} from "./api";
import SimpleMarkdown from "./SimpleMarkdown";

const { Text, Title, Paragraph } = Typography;
const { TextArea } = Input;

// ── Constants ─────────────────────────────────────────────────────────────────

const STRATEGY_OPTIONS = [
  { value: "gap_based", label: "规则差距", desc: "LLM 对比现有规则与 Review Queue，识别空白" },
  { value: "fuzzy_signal", label: "模糊信号", desc: "澄清模糊印象，转化为清晰 IF-THEN 规则" },
  { value: "critical_incident", label: "关键事件", desc: "从真实案例倒推可复用规律" },
  { value: "reverse_validation", label: "反向验证", desc: "对现有规则做压力测试，探索边界" },
];

const CONFIDENCE_COLOR: Record<string, string> = { high: "green", medium: "orange", low: "red" };
const CONFIDENCE_LABEL: Record<string, string> = { high: "高", medium: "中", low: "低" };

const RQ_STATUS_COLOR: Record<string, string> = {
  pending_review: "default", in_review: "processing",
  approved: "success", rejected: "error", archived: "warning",
};
const RQ_STATUS_LABEL: Record<string, string> = {
  pending_review: "待审查", in_review: "审查中",
  approved: "已批准", rejected: "已拒绝", archived: "已归档",
};

// ── Types ─────────────────────────────────────────────────────────────────────

type ChatMsg = { role: "user" | "assistant" | "status"; content: string };
type MainTab = "workbench" | "pending";

// ── ChatArea ──────────────────────────────────────────────────────────────────

function ChatArea({
  messages, streaming, satisfaction,
}: {
  messages: ChatMsg[];
  streaming: boolean;
  satisfaction?: number | null;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  return (
    <div style={{
      border: "1px solid var(--color-border, #e0e0d8)", borderRadius: 8,
      padding: "12px 14px", background: "var(--color-bg-card, #fff)",
      minHeight: 200, maxHeight: 420, overflowY: "auto",
    }}>
      {messages.length === 0 ? (
        <Text type="secondary" style={{ fontSize: 13 }}>
          选择策略并输入您的想法，LLM 将主动提问、逐步澄清规则。
        </Text>
      ) : messages.map((msg, i) => (
        <div
          key={i}
          style={{
            marginBottom: 10,
            padding: msg.role === "status" ? "4px 8px" : "8px 12px",
            borderRadius: 6,
            background: msg.role === "user"
              ? "rgba(82,124,94,0.08)"
              : msg.role === "status" ? "transparent" : "var(--color-bg-card,#fff)",
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
      {!streaming && satisfaction !== null && satisfaction !== undefined && (
        <div style={{ marginTop: 8 }}>
          <Progress
            percent={Math.round(satisfaction * 100)}
            size="small"
            status={satisfaction >= 0.85 ? "success" : "active"}
            format={(p) => `满意度 ${p}%`}
          />
        </div>
      )}
    </div>
  );
}

// ── OnboardingInterview ───────────────────────────────────────────────────────

function OnboardingInterview({
  rqTopics,
  onProfileSaved,
}: {
  rqTopics: string[];
  onProfileSaved: (profile: ExpertProfileData) => void;
}) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [started, setStarted] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const priorMessages = messages
    .filter((m) => m.role !== "status")
    .map((m) => ({ role: m.role as string, content: m.content }));

  const sendToInterview = async (text: string) => {
    if (streaming) return;
    const userMsg = text.trim();
    setInput("");
    if (userMsg) setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setStreaming(true);
    abortRef.current = new AbortController();
    try {
      await postExpertInterviewStream(
        { user_input: userMsg || "你好，请开始。", prior_messages: priorMessages, rq_topics: rqTopics },
        (ev) => {
          if (ev.type === "text") {
            const chunk = String(ev.text ?? "");
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (last?.role === "assistant") {
                return [...prev.slice(0, -1), { role: "assistant", content: last.content + chunk }];
              }
              return [...prev, { role: "assistant", content: chunk }];
            });
          } else if (ev.type === "profile_ready") {
            const p = ev.profile as { domains?: string[]; background?: string };
            const profile: ExpertProfileData = {
              domains: p.domains ?? [],
              background: p.background ?? "",
            };
            void putExpertProfile(profile)
              .then((saved) => {
                message.success("专家档案已保存，进入提取工作台…");
                onProfileSaved(saved);
              })
              .catch(() => {
                // Still proceed even if save fails
                onProfileSaved(profile);
              });
          }
        },
        abortRef.current.signal,
      );
    } catch (e) {
      if ((e as Error)?.name !== "AbortError") {
        message.error(`访谈失败: ${e instanceof Error ? e.message : String(e)}`);
      }
    } finally {
      setStreaming(false);
    }
  };

  const handleStart = () => {
    setStarted(true);
    void sendToInterview("");
  };

  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "32px 16px" }}>
      <div style={{ textAlign: "center", marginBottom: 24 }}>
        <BulbOutlined style={{ fontSize: 36, color: "#527c5e", marginBottom: 12 }} />
        <Title level={4} style={{ margin: 0 }}>欢迎来到知识提取工作台</Title>
        <Paragraph type="secondary" style={{ marginTop: 8 }}>
          在开始前，请让 AI 助理了解您的专业背景，以便优化提问策略。<br />
          只需 2-3 轮对话，之后可随时在右上角修改。
        </Paragraph>
      </div>

      {!started ? (
        <div style={{ textAlign: "center" }}>
          <Button type="primary" size="large" icon={<UserOutlined />} onClick={handleStart}>
            开始专家背景访谈
          </Button>
          <div style={{ marginTop: 12 }}>
            <Button type="link" size="small" onClick={() => onProfileSaved({ domains: [], background: "" })}>
              跳过，直接进入工作台
            </Button>
          </div>
        </div>
      ) : (
        <>
          <div style={{
            border: "1px solid var(--color-border,#e0e0d8)", borderRadius: 8,
            padding: "12px 14px", background: "#fafaf8",
            minHeight: 160, maxHeight: 360, overflowY: "auto", marginBottom: 12,
          }}>
            {messages.map((msg, i) => (
              <div
                key={i}
                style={{
                  marginBottom: 10,
                  padding: "8px 12px", borderRadius: 6,
                  background: msg.role === "user" ? "rgba(82,124,94,0.08)" : "#fff",
                  borderLeft: msg.role === "assistant" ? "3px solid rgba(82,124,94,0.4)" : "none",
                }}
              >
                {msg.role === "user" ? (
                  <Text>{msg.content}</Text>
                ) : (
                  <SimpleMarkdown markdown={msg.content} />
                )}
              </div>
            ))}
            {streaming && <div style={{ padding: 4 }}><Spin size="small" /><Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>思考中…</Text></div>}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void sendToInterview(input); } }}
              placeholder="回答 AI 的问题…（Enter 发送）"
              autoSize={{ minRows: 2, maxRows: 4 }}
              disabled={streaming}
              style={{ flex: 1 }}
            />
            <Button type="primary" onClick={() => void sendToInterview(input)} disabled={!input.trim() || streaming}>发送</Button>
          </div>
        </>
      )}
    </div>
  );
}

// ── WorkbenchTab ──────────────────────────────────────────────────────────────

function WorkbenchTab({
  initialRQItem,
  postReviewCtx,
}: {
  initialRQItem: ReviewQueueItem | null;
  postReviewCtx: { projectId: number; conversationId: number } | null;
}) {
  const [strategy, setStrategy] = useState("gap_based");
  const [rqItem, setRqItem] = useState<ReviewQueueItem | null>(initialRQItem);
  const [rqItems, setRqItems] = useState<ReviewQueueItem[]>([]);

  // Document upload state
  const [showUpload, setShowUpload] = useState(false);
  const [materialId, setMaterialId] = useState<string | null>(null);
  const [docName, setDocName] = useState("");
  const [uploading, setUploading] = useState(false);

  // Chat state
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [roundNumber, setRoundNumber] = useState(1);
  const [newKiIds, setNewKiIds] = useState<string[]>([]);
  const [lastSatisfaction, setLastSatisfaction] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const isPostReview = postReviewCtx != null;
  const isDocMode = materialId != null;

  useEffect(() => {
    if (initialRQItem) { setRqItem(initialRQItem); setMessages([]); setRoundNumber(1); }
  }, [initialRQItem]);

  useEffect(() => {
    if (postReviewCtx) {
      setMessages([{
        role: "status",
        content: `已关联审查对话（项目 #${postReviewCtx.projectId}，会话 #${postReviewCtx.conversationId}）。请描述本次审查遗漏的问题，或直接点击「开始提取」。`,
      }]);
      setRoundNumber(1);
    }
  }, [postReviewCtx]);

  useEffect(() => {
    getReviewQueue().then(({ items }) => setRqItems(items)).catch(() => {});
  }, []);

  const priorMessages = messages
    .filter((m) => m.role !== "status")
    .map((m) => ({ role: m.role as string, content: m.content }));

  const appendChunk = (chunk: string) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last?.role === "assistant") return [...prev.slice(0, -1), { role: "assistant", content: last.content + chunk }];
      return [...prev, { role: "assistant", content: chunk }];
    });
  };

  const handleSend = async (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || streaming) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setStreaming(true);
    abortRef.current = new AbortController();

    try {
      if (isPostReview) {
        await postReviewExtractionStream(
          postReviewCtx!.projectId, postReviewCtx!.conversationId,
          { user_input: text, prior_messages: priorMessages },
          (ev) => {
            if (ev.type === "text") appendChunk(String(ev.text ?? ""));
            else if (ev.type === "ki") { const kid = String((ev as Record<string, unknown>).kid ?? ""); if (kid) setNewKiIds((p) => p.includes(kid) ? p : [...p, kid]); }
            else if (ev.type === "final") { const cnt = Number((ev as Record<string, unknown>).new_ki_count ?? 0); if (cnt > 0) setMessages((p) => [...p, { role: "status", content: `✓ 生成 ${cnt} 条知识条目。` }]); }
          },
          abortRef.current.signal,
        );
      } else if (isDocMode) {
        await postDocExtractionStream(
          { material_id: materialId!, user_input: text, strategy, prior_messages: priorMessages },
          (ev) => {
            if (ev.type === "text") appendChunk(String(ev.text ?? ""));
            else if (ev.type === "status") setMessages((p) => [...p, { role: "status", content: String((ev as Record<string, unknown>).msg ?? "") }]);
            else if (ev.type === "ki") { const kid = String((ev as Record<string, unknown>).kid ?? ""); if (kid) setNewKiIds((p) => p.includes(kid) ? p : [...p, kid]); }
            else if (ev.type === "final") {
              const cnt = Number((ev as Record<string, unknown>).new_ki_count ?? 0);
              const sat = (ev as Record<string, unknown>).satisfaction as number | null;
              setLastSatisfaction(sat ?? null);
              if (cnt > 0) setMessages((p) => [...p, { role: "status", content: `✓ 生成 ${cnt} 条知识条目，已进入「待批准规则」。` }]);
            }
          },
          abortRef.current.signal,
        );
      } else {
        await postActiveExtractionStream(
          { user_input: text, strategy, review_queue_item_id: rqItem?.id ?? null, prior_messages: priorMessages, round_number: roundNumber },
          (ev) => {
            if (ev.type === "text") appendChunk(String(ev.text ?? ""));
            else if (ev.type === "status") setMessages((p) => [...p, { role: "status", content: String((ev as Record<string, unknown>).msg ?? "") }]);
            else if (ev.type === "ki") { const kid = String((ev as Record<string, unknown>).kid ?? ""); if (kid) setNewKiIds((p) => p.includes(kid) ? p : [...p, kid]); }
            else if (ev.type === "clarify") {
              const cl = (ev as Record<string, unknown>).clarify as { questions?: string[] } | undefined;
              if (cl?.questions?.length) setMessages((p) => [...p, { role: "status", content: `💡 建议追问：\n${cl.questions!.map((q, i) => `${i + 1}. ${q}`).join("\n")}` }]);
            } else if (ev.type === "final") {
              const sat = (ev as Record<string, unknown>).satisfaction as number | null;
              const autoAdv = Boolean((ev as Record<string, unknown>).auto_advance);
              const cnt = Number((ev as Record<string, unknown>).new_ki_count ?? 0);
              setLastSatisfaction(sat ?? null);
              let msg = "";
              if (cnt > 0) msg += `✓ 生成 ${cnt} 条知识条目，已进入「待批准规则」。`;
              if (autoAdv) msg += "  满意度已达标，可提取下一条。";
              else if (sat !== null) msg += `  当前满意度 ${Math.round(sat * 100)}%，可继续追问。`;
              if (msg) setMessages((p) => [...p, { role: "status", content: msg }]);
              setRoundNumber((n) => n + 1);
            }
          },
          abortRef.current.signal,
        );
      }
    } catch (e) {
      if ((e as Error)?.name !== "AbortError") message.error(`提取失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setStreaming(false);
    }
  };

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const res = await uploadExtractionMaterial(file);
      setMaterialId(res.material_id);
      setDocName(res.original_name);
      setMessages([]);
      setNewKiIds([]);
      setLastSatisfaction(null);
      message.success(`已上传「${res.original_name}」，可开始提取。`);
    } catch (e) {
      message.error(`上传失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(false);
    }
    return false;
  };

  const handleReset = () => {
    abortRef.current?.abort();
    setStreaming(false);
    setMessages([]);
    setRoundNumber(1);
    setNewKiIds([]);
    setLastSatisfaction(null);
    setMaterialId(null);
    setDocName("");
  };

  return (
    <div style={{ padding: "16px 0" }}>
      {/* Post-review mode banner */}
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

      {/* Controls row (hidden in post-review mode) */}
      {!isPostReview && (
        <div style={{ display: "flex", gap: 12, marginBottom: 14, flexWrap: "wrap", alignItems: "flex-start" }}>
          {/* Strategy */}
          <Card size="small" style={{ flex: "0 0 auto", minWidth: 240 }}>
            <Text strong style={{ display: "block", marginBottom: 8 }}>提取策略</Text>
            <Radio.Group
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as string)}
              style={{ display: "flex", flexDirection: "column", gap: 5 }}
            >
              {STRATEGY_OPTIONS.map((opt) => (
                <Radio key={opt.value} value={opt.value}>
                  <span style={{ fontWeight: 500 }}>{opt.label}</span>{" "}
                  <span style={{ fontSize: 11, color: "#888" }}>{opt.desc}</span>
                </Radio>
              ))}
            </Radio.Group>
          </Card>

          {/* RQ item + upload */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10, minWidth: 200 }}>
            <Card size="small">
              <Text strong style={{ display: "block", marginBottom: 6 }}>关联 Review Queue 条目（可选）</Text>
              <Select
                value={rqItem?.id ?? null}
                onChange={(val) => setRqItem(rqItems.find((x) => x.id === val) ?? null)}
                placeholder="选择候选线索…"
                style={{ width: "100%" }}
                allowClear onClear={() => setRqItem(null)}
                options={rqItems
                  .filter((x) => x.status !== "rejected" && x.status !== "archived")
                  .map((x) => ({ value: x.id, label: `[${x.focus_id}] ${x.suggestion.slice(0, 50)}… ×${x.occurrences}` }))}
              />
              {rqItem && (
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 6 }}>{rqItem.suggestion}</Text>
              )}
            </Card>

            {/* Document upload toggle */}
            {!isDocMode && (
              <div>
                <Button
                  type="link" size="small" icon={<FileTextOutlined />}
                  onClick={() => setShowUpload((v) => !v)}
                  style={{ padding: 0 }}
                >
                  {showUpload ? "收起文档上传" : "上传规则文档（可选）"}
                </Button>
                {showUpload && (
                  <Upload.Dragger
                    accept=".md,.txt,.docx,.pdf"
                    beforeUpload={(file) => { void handleUpload(file); return false; }}
                    showUploadList={false}
                    disabled={uploading}
                    style={{ marginTop: 8 }}
                  >
                    <p className="ant-upload-drag-icon">
                      {uploading ? <Spin /> : <InboxOutlined style={{ fontSize: 28, color: "#527c5e" }} />}
                    </p>
                    <p style={{ fontSize: 13 }}>拖拽或点击上传（.md / .txt / .docx / .pdf）</p>
                    <p style={{ fontSize: 12, color: "#888" }}>LLM 将基于文档内容做知识澄清</p>
                  </Upload.Dragger>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Doc loaded banner */}
      {isDocMode && (
        <Alert
          type="info"
          icon={<FileTextOutlined />}
          message={
            <span>
              已加载文档：<strong>{docName}</strong>
              <Button type="link" size="small" onClick={handleReset} style={{ marginLeft: 8 }}>移除</Button>
            </span>
          }
          style={{ marginBottom: 12 }}
        />
      )}

      {/* KI completion banner */}
      {newKiIds.length > 0 && (
        <Alert
          type="success"
          icon={<CheckCircleFilled />}
          message={
            <span>
              已生成 <strong>{newKiIds.length}</strong> 条知识条目，请切换到「待批准规则」审批后写入规则库。
            </span>
          }
          style={{ marginBottom: 12 }}
          closable
          onClose={() => setNewKiIds([])}
        />
      )}

      {/* Chat area with satisfaction */}
      <ChatArea messages={messages} streaming={streaming} satisfaction={lastSatisfaction} />

      {/* Input row */}
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void handleSend(); } }}
          placeholder={
            isPostReview
              ? "描述遗漏的问题或补充发现…（Shift+Enter 换行）"
              : isDocMode
              ? "输入问题，或点击「一键开始」让 AI 自动分析…"
              : "输入您的想法或回答 LLM 的问题…（Shift+Enter 换行）"
          }
          autoSize={{ minRows: 2, maxRows: 6 }}
          disabled={streaming}
          style={{ flex: 1 }}
        />
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {/* First-message shortcut buttons */}
          {!streaming && messages.filter((m) => m.role !== "status").length === 0 && (
            isPostReview ? (
              <Button type="primary" onClick={() => void handleSend("请开始分析，帮我识别可以提炼的知识")}>
                开始提取
              </Button>
            ) : isDocMode ? (
              <Button type="primary" onClick={() => void handleSend("请开始分析文档并提取知识")}>
                一键开始
              </Button>
            ) : (
              <Button type="primary" onClick={() => void handleSend(input || "请基于当前 Review Queue 和审查域，开始提问")} disabled={streaming}>
                开始
              </Button>
            )
          )}
          {(messages.filter((m) => m.role !== "status").length > 0 || input.trim()) && (
            <Button type="primary" onClick={() => void handleSend()} disabled={!input.trim() || streaming}>
              发送
            </Button>
          )}
          {streaming ? (
            <Button danger onClick={() => { abortRef.current?.abort(); setStreaming(false); }}>停止</Button>
          ) : (
            <Button onClick={handleReset} disabled={messages.length === 0 && !materialId}>清空</Button>
          )}
        </div>
      </div>

      {/* Round indicator */}
      {!isPostReview && !isDocMode && (
        <div style={{ marginTop: 6 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            第 {roundNumber} 轮 · 满意度 ≥ 85% 或最多 5 轮后自动生成知识条目
          </Text>
        </div>
      )}
    </div>
  );
}

// ── PendingRulesTab ───────────────────────────────────────────────────────────

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

  const columns = [
    {
      title: "标题",
      key: "title",
      render: (_: unknown, row: PendingRuleItem) => (
        <div>
          <div style={{ fontWeight: 500 }}>{row.title}</div>
          <Tag style={{ marginTop: 4 }} color="blue">{row.extraction_focus_id}</Tag>
        </div>
      ),
    },
    {
      title: "内容摘要",
      dataIndex: "content",
      ellipsis: true,
      render: (v: string) => (
        <Tooltip title={<div style={{ maxWidth: 360, whiteSpace: "pre-wrap" }}>{v}</div>} placement="left">
          <span style={{ cursor: "pointer", color: "#555", fontSize: 13 }}>
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
        <Tag color={CONFIDENCE_COLOR[v] || "default"}>
          {CONFIDENCE_LABEL[v] || v}
        </Tag>
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
      width: 140,
      render: (_: unknown, row: PendingRuleItem) => (
        <Space size={4}>
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
        <Button icon={<ReloadOutlined />} size="small" onClick={() => void load()} loading={loading}>刷新</Button>
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

// ── ReviewQueuePanel (exported for use in App.tsx) ────────────────────────────

export function ReviewQueuePanel({
  onStartExtraction,
}: {
  onStartExtraction?: (item: ReviewQueueItem) => void;
}) {
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { items: data } = await getReviewQueue();
      setItems(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleDelete = async (id: string) => {
    try {
      await deleteReviewQueueItem(id);
      setItems((prev) => prev.filter((x) => x.id !== id));
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

  const columns = [
    {
      title: "关注点",
      dataIndex: "focus_id",
      width: 90,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: "知识线索",
      dataIndex: "suggestion",
      ellipsis: true,
      render: (v: string) => <Tooltip title={v}><span style={{ fontSize: 13 }}>{v}</span></Tooltip>,
    },
    {
      title: "次",
      dataIndex: "occurrences",
      width: 50,
      align: "center" as const,
      render: (v: number) => (
        <Badge count={v} color={v >= 3 ? "red" : v >= 2 ? "orange" : "blue"} showZero />
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 80,
      render: (v: string) => <Tag color={RQ_STATUS_COLOR[v] || "default"} style={{ fontSize: 11 }}>{RQ_STATUS_LABEL[v] || v}</Tag>,
    },
    {
      title: "操作",
      width: 140,
      render: (_: unknown, row: ReviewQueueItem) => (
        <Space size={2}>
          {onStartExtraction && (
            <Button
              type="link" size="small"
              onClick={() => onStartExtraction(row)}
              disabled={row.status === "approved" || row.status === "rejected"}
            >
              提取
            </Button>
          )}
          <Button type="link" size="small" onClick={() => void handleStatus(row.id, row.status === "archived" ? "pending_review" : "archived")}>
            {row.status === "archived" ? "恢复" : "归档"}
          </Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => void handleDelete(row.id)} />
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8, gap: 6 }}>
        <Text strong style={{ fontSize: 13 }}>审查队列</Text>
        <Button icon={<ReloadOutlined />} size="small" onClick={() => void load()} loading={loading} />
        <Text type="secondary" style={{ marginLeft: "auto", fontSize: 11 }}>高频线索优先</Text>
      </div>
      {items.length === 0 && !loading ? (
        <Empty
          description="暂无队列条目。完成项目审查后，LLM 将自动提取泛化知识线索。"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ padding: "20px 0" }}
        />
      ) : (
        <Table
          dataSource={items}
          columns={columns}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ pageSize: 10, showSizeChanger: false }}
        />
      )}
    </div>
  );
}

// ── ExtractionPage (main) ─────────────────────────────────────────────────────

export default function ExtractionPage() {
  const [activeTab, setActiveTab] = useState<MainTab>("workbench");
  const [profile, setProfile] = useState<ExpertProfileData | null>(null);
  const [profileLoaded, setProfileLoaded] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [rqItemForExtraction, setRqItemForExtraction] = useState<ReviewQueueItem | null>(null);
  const [postReviewCtx, setPostReviewCtx] = useState<{ projectId: number; conversationId: number } | null>(null);
  const [rqTopics, setRqTopics] = useState<string[]>([]);

  // Pull post-review context from sessionStorage
  useEffect(() => {
    const raw = window.sessionStorage.getItem("aika_post_review_ctx");
    if (raw) {
      try {
        const ctx = JSON.parse(raw) as { projectId: number; conversationId: number };
        window.sessionStorage.removeItem("aika_post_review_ctx");
        setPostReviewCtx(ctx);
        setActiveTab("workbench");
      } catch { /* ignore */ }
    }
  }, []);

  // Load expert profile; trigger onboarding if empty
  useEffect(() => {
    getExpertProfile()
      .then((p) => {
        setProfile(p);
        setProfileLoaded(true);
        if (!p.domains.length && !p.background) {
          setShowOnboarding(true);
        }
      })
      .catch(() => {
        setProfileLoaded(true);
        setShowOnboarding(true);
      });
  }, []);

  // Load RQ topics for onboarding suggestions
  useEffect(() => {
    if (showOnboarding) {
      getReviewQueue()
        .then(({ items }) => {
          const topics = [...new Set(items.map((x) => x.focus_id).filter(Boolean))].slice(0, 8);
          setRqTopics(topics);
        })
        .catch(() => {});
    }
  }, [showOnboarding]);

  const handleProfileSaved = (p: ExpertProfileData) => {
    setProfile(p);
    setShowOnboarding(false);
  };

  const tabItems: { key: MainTab; label: string }[] = [
    { key: "workbench", label: "提取工作台" },
    { key: "pending", label: "待批准规则" },
  ];

  const domains = profile?.domains ?? [];

  return (
    <div className="extraction-page">
      <div className="extraction-page-header">
        <Title level={4} style={{ margin: 0 }}>知识提取</Title>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {profileLoaded && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              领域：{domains.length > 0 ? domains.join("、") : "未设置"}
            </Text>
          )}
          <Button
            icon={<UserOutlined />}
            size="small"
            onClick={() => setShowOnboarding(true)}
          >
            专家背景
          </Button>
        </div>
      </div>

      {/* Onboarding overlay */}
      {showOnboarding && (
        <div style={{
          position: "absolute", inset: 0, background: "var(--color-bg, #f5f5f0)",
          zIndex: 10, overflowY: "auto",
        }}>
          <OnboardingInterview rqTopics={rqTopics} onProfileSaved={handleProfileSaved} />
        </div>
      )}

      {/* Tabs */}
      <div style={{ borderBottom: "1px solid var(--color-border,#e0e0d8)", marginBottom: 0 }}>
        <div style={{ display: "flex" }}>
          {tabItems.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                padding: "8px 20px", border: "none",
                borderBottom: activeTab === tab.key ? "2px solid #527c5e" : "2px solid transparent",
                background: "none", cursor: "pointer",
                fontWeight: activeTab === tab.key ? 600 : 400,
                color: activeTab === tab.key ? "#527c5e" : "#666",
                fontSize: 14, transition: "all 0.15s",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: "0 4px" }}>
        {activeTab === "workbench" && (
          <WorkbenchTab
            initialRQItem={rqItemForExtraction}
            postReviewCtx={postReviewCtx}
          />
        )}
        {activeTab === "pending" && <PendingRulesTab />}
      </div>

      {/* Hidden: keep rqItemForExtraction setter accessible */}
      {rqItemForExtraction && (
        <div style={{ display: "none" }} data-rq-item={rqItemForExtraction.id} />
      )}
    </div>
  );
}
