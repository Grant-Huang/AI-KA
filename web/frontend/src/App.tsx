import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  Divider,
  Input,
  InputNumber,
  Modal,
  Radio,
  Select,
  Space,
  Spin,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  DownloadOutlined,
  ArrowUpOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  StopOutlined,
  PlusOutlined,
  CommentOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { apiJson, openConvertStream, postAnalyzeConversationStream, postAnalyzeStream, postFollowupConversationStream } from "./api";
import SimpleMarkdown from "./SimpleMarkdown";

const { Text } = Typography;

type Project = { id: number; name: string; root_path: string };
type Conversation = { id: number; analysis_type: string; title: string };
type FocusPoint = { id: string; name: string; prompt: string };
type LlmSettings = {
  text_provider: string;
  text_base_url: string;
  text_model: string;
  vl_model: string;
  vl_base_url: string;
  has_text_api_key?: boolean;
  has_vl_api_key?: boolean;
};
type FocusPreset = { id: string; name: string; focus_points: string[] };
type ChunkStrategy = "blank" | "structured";

type SettingsData = {
  focus_points: FocusPoint[];
  focus_presets?: FocusPreset[];
  chunk_limit: number;
  chunk_strategy?: ChunkStrategy;
  disable_image_parse?: boolean;
  llm_settings: LlmSettings;
  rules_md_error?: string | null;
};

type LogGroupKind = "system" | "business" | "error";
type LogGroup = {
  key: string;
  title: string;
  kind: LogGroupKind;
  collapsed: boolean;
  text: string;
};

type MilestoneStatus = "running" | "done" | "error";
type Milestone = {
  id: string;
  name: string;
  status: MilestoneStatus;
  detailKind: LogGroupKind;
  detailText: string;
};

type PipelineStep = "convert" | "index" | "analyze";

function tailEllipsis(s: string, tail: number = 50): string {
  const t = String(s || "");
  if (!t) return "";
  if (t.length <= tail + 3) return t;
  return "..." + t.slice(-tail);
}

function formatLocalDateTime(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const REDACTED_THINK_OPEN = /<(think|redacted_thinking)>/i;
const REDACTED_THINK_CLOSE = /<\/(think|redacted_thinking)>/i;

/** 与后端 _parse_focus_ids_from_recommended 一致：反引号块优先，支持中文 id */
function parseFocusIdsFromRecommended(raw: string): string[] {
  const t = String(raw || "");
  const out: string[] = [];
  const seen = new Set<string>();
  const pat = /`\s*focus:([^`]+?)\s*`|focus:([^\s+|`]+)/g;
  let m: RegExpExecArray | null;
  while ((m = pat.exec(t)) !== null) {
    const id = String(m[1] ?? m[2] ?? "").trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}

/** 拆分模型输出中的 thinking 围栏；闭合后 thinkComplete 为 true，用于自动折叠 */
function splitRedactedThinkingBlock(md: string): {
  before: string;
  think: string;
  after: string;
  thinkComplete: boolean;
} {
  const t = String(md || "");
  const openMatch = t.match(REDACTED_THINK_OPEN);
  if (!openMatch || openMatch.index === undefined) {
    return { before: t, think: "", after: "", thinkComplete: true };
  }
  const openIdx = openMatch.index;
  const openLen = openMatch[0].length;
  const afterOpen = t.slice(openIdx + openLen);
  const closeMatch = afterOpen.match(REDACTED_THINK_CLOSE);
  if (!closeMatch || closeMatch.index === undefined) {
    return { before: t.slice(0, openIdx), think: afterOpen, after: "", thinkComplete: false };
  }
  const closeIdx = closeMatch.index;
  const closeLen = closeMatch[0].length;
  return {
    before: t.slice(0, openIdx),
    think: afterOpen.slice(0, closeIdx),
    after: afterOpen.slice(closeIdx + closeLen),
    thinkComplete: true,
  };
}

/** 业务类里程碑正文：剥离 redacted_thinking，思考未结束时保持展开，闭合后默认折叠且可再展开 */
function BusinessMilestoneMarkdown({ markdown }: { markdown: string }) {
  const { before, think, after, thinkComplete } = useMemo(() => splitRedactedThinkingBlock(markdown), [markdown]);
  const [thinkOpen, setThinkOpen] = useState(false);

  useEffect(() => {
    if (!think) return;
    if (!thinkComplete) {
      setThinkOpen(true);
      return;
    }
    // 正文开始（或 think 块闭合）后默认折叠
    setThinkOpen(false);
  }, [think, thinkComplete, after]);

  if (!think) {
    return <SimpleMarkdown markdown={markdown || "（暂无内容）"} />;
  }

  const thinkExpanded = !thinkComplete || thinkOpen;

  return (
    <>
      {before.trim() ? <SimpleMarkdown markdown={before} /> : null}
      <details
        className="think-stream-details"
        open={thinkExpanded}
        onToggle={(e) => {
          if (!thinkComplete) return;
          setThinkOpen(e.currentTarget.open);
        }}
      >
        <summary className="think-stream-summary">
          {thinkComplete ? "思考过程（已输出完毕，默认收起）" : "思考过程（输出中…）"}
        </summary>
        <pre className="stream-render-think think-stream-body">{think}</pre>
      </details>
      {after.trim() ? <SimpleMarkdown markdown={after} /> : null}
    </>
  );
}

export default function App() {
  const TEXT_MODEL_OPTIONS = ["qwen3", "MiniMax-M2.5"];
  const VL_MODEL_OPTIONS = ["qwen3-vl-plus"];

  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pickedRootPath, setPickedRootPath] = useState<string>("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(null);
  const [newConversationOpen, setNewConversationOpen] = useState(false);
  const [chatsOpen, setChatsOpen] = useState(false);
  const [analysisTypeDraft, setAnalysisTypeDraft] = useState("KA");
  const [draftText, setDraftText] = useState("");

  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [finalMarkdown, setFinalMarkdown] = useState<string>("");

  const [chunkLimit, setChunkLimit] = useState(40);
  const [nativePickerAvailable, setNativePickerAvailable] = useState(true);
  const [pickLoading, setPickLoading] = useState(false);
  const [manualRootInput, setManualRootInput] = useState("");
  const [manualLoadLoading, setManualLoadLoading] = useState(false);
  const [manualPickOpen, setManualPickOpen] = useState(false);
  const [focusPoints, setFocusPoints] = useState<string[]>([]);
  const [focusDefs, setFocusDefs] = useState<FocusPoint[]>([]);
  const [focusPresets, setFocusPresets] = useState<FocusPreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState<string>("");
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineTaskBrief, setPipelineTaskBrief] = useState("");
  const [pipelineFailModal, setPipelineFailModal] = useState<{ step: PipelineStep; message: string } | null>(null);
  const [followupText, setFollowupText] = useState("");
  const [followupRunning, setFollowupRunning] = useState(false);
  const followupAbortRef = useRef<AbortController | null>(null);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpMarkdown, setHelpMarkdown] = useState<string>("");
  const [helpLoading, setHelpLoading] = useState(false);
  const [settingsDraft, setSettingsDraft] = useState<SettingsData>({
    focus_points: [],
    chunk_limit: 40,
    chunk_strategy: "blank",
    disable_image_parse: true,
    llm_settings: {
      text_provider: "openai_compatible",
      text_base_url: "https://api.minimax.io/v1",
      text_model: "MiniMax-M2.5",
      vl_model: "qwen3-vl-plus",
      vl_base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      has_text_api_key: false,
      has_vl_api_key: false,
    },
  });
  const [rulesMdError, setRulesMdError] = useState<string | null>(null);
  const [textApiKeyDraft, setTextApiKeyDraft] = useState("");
  const [textApiKeyTouched, setTextApiKeyTouched] = useState(false);
  const [vlApiKeyDraft, setVlApiKeyDraft] = useState("");
  const [vlApiKeyTouched, setVlApiKeyTouched] = useState(false);
  const [focusSelectedIndex, setFocusSelectedIndex] = useState(0);
  const [presetSelectedIndex, setPresetSelectedIndex] = useState(0);

  const chunkStrategyAtOpenRef = useRef<ChunkStrategy>("blank");
  const [milestoneOpenOverrides, setMilestoneOpenOverrides] = useState<Record<string, boolean>>({});
  const rulesFileInputRef = useRef<HTMLInputElement | null>(null);
  const stopConvertRef = useRef<(() => void) | null>(null);
  const stopAnalyzeRef = useRef<(() => void) | null>(null);
  const analyzeAbortRef = useRef<AbortController | null>(null);
  const terminatedRef = useRef(false);
  const deltaAccRef = useRef<string>(""); // accumulated model-output text used for dedup
  const currentStageKeyRef = useRef<string>("");
  const lastMilestoneIdRef = useRef<string>("");
  const pipelineStepRef = useRef<PipelineStep>("convert");

  const ensureMilestone = useCallback((id: string, name: string, detailKind: LogGroupKind) => {
    setMilestones((prev) => {
      if (prev.some((m) => m.id === id)) return prev;
      lastMilestoneIdRef.current = id;
      return [...prev, { id, name, status: "running", detailKind, detailText: "" }];
    });
  }, []);

  const appendMilestoneDetail = useCallback((id: string, chunk: string) => {
    const s = String(chunk || "");
    if (!s) return;
    setMilestones((prev) =>
      prev.map((m) => (m.id === id ? { ...m, detailText: m.detailText + s } : m)),
    );
  }, []);

  const setMilestoneStatus = useCallback((id: string, status: MilestoneStatus) => {
    setMilestones((prev) => prev.map((m) => (m.id === id ? { ...m, status } : m)));
    // 进行中用户展开会在 overrides 里记下 true；打勾完成时需强制折叠该小节
    if (status === "done" || status === "error") {
      setMilestoneOpenOverrides((prev) => ({ ...prev, [id]: false }));
    }
  }, []);

  const loadProjects = useCallback(async () => {
    const data = await apiJson<{ projects: Project[] }>("/api/v1/projects");
    setProjects(data.projects || []);
    setSelectedId((prev) => {
      if (data.projects?.length && prev == null) return data.projects[0].id;
      return prev;
    });
  }, []);

  const loadConversations = useCallback(
    async (projectId: number | null) => {
      if (projectId == null) {
        setConversations([]);
        setSelectedConversationId(null);
        return;
      }
      const data = await apiJson<{ conversations: Conversation[] }>(`/api/v1/projects/${projectId}/conversations?limit=50`);
      const items = data.conversations || [];
      setConversations(items);
      setSelectedConversationId((prev) => {
        if (prev != null && items.some((c) => c.id === prev)) return prev;
        return items.length ? items[0].id : null;
      });
    },
    [],
  );

  const loadSettings = useCallback(async (opts?: { snapshot_chunk_strategy?: boolean }) => {
    const data = await apiJson<SettingsData>("/api/v1/settings");
    const cs: ChunkStrategy = data.chunk_strategy === "structured" ? "structured" : "blank";
    const merged = { ...data, chunk_strategy: cs };
    if (opts?.snapshot_chunk_strategy) {
      chunkStrategyAtOpenRef.current = cs;
    }
    setChunkLimit(merged.chunk_limit);
    setFocusDefs(merged.focus_points);
    setFocusPresets(merged.focus_presets || []);
    setSettingsDraft(merged);
    setFocusSelectedIndex(0);
    setPresetSelectedIndex(0);
    setRulesMdError(merged.rules_md_error || null);
    setTextApiKeyDraft("");
    setTextApiKeyTouched(false);
    setVlApiKeyDraft("");
    setVlApiKeyTouched(false);
  }, []);

  useEffect(() => {
    loadProjects().catch((e) => message.error(String((e as Error).message)));
    loadSettings().catch((e) => message.error(String((e as Error).message)));
  }, [loadProjects, loadSettings]);

  useEffect(() => {
    loadConversations(selectedId).catch((e) => message.error(String((e as Error).message)));
  }, [selectedId, loadConversations]);

  useEffect(() => {
    if (!settingsOpen) return;
    // 每次打开设置时都从后端刷新，避免显示旧值/读错配置源时难以定位
    loadSettings({ snapshot_chunk_strategy: true }).catch((e) => message.error(String((e as Error).message)));
  }, [settingsOpen, loadSettings]);

  useEffect(() => {
    apiJson<{ native_folder_picker: boolean }>("/api/v1/fs/capabilities")
      .then((d) => setNativePickerAvailable(!!d.native_folder_picker))
      .catch(() => setNativePickerAvailable(false));
  }, []);

  useEffect(() => {
    if (!helpOpen) return;
    setHelpLoading(true);
    apiJson<{ markdown: string; source: string }>("/api/v1/helpme")
      .then((d) => setHelpMarkdown(d.markdown || ""))
      .catch((e) => setHelpMarkdown(`# 帮助加载失败\n\n${String((e as Error).message || e)}`))
      .finally(() => setHelpLoading(false));
  }, [helpOpen]);

  const selected = useMemo(() => projects.find((p) => p.id === selectedId) || null, [projects, selectedId]);

  const createConversation = useCallback(
    async (analysisType: string, title?: string) => {
      if (selectedId == null) {
        message.warning("请先选择或创建项目");
        return null;
      }
      const data = await apiJson<{ id: number; analysis_type: string; title: string }>(`/api/v1/projects/${selectedId}/conversations`, {
        method: "POST",
        body: JSON.stringify({ analysis_type: analysisType, title: title || "" }),
      });
      await loadConversations(selectedId);
      setSelectedConversationId(data.id);
      return data.id;
    },
    [selectedId, loadConversations],
  );

  const ensureProjectForPath = useCallback(
    async (path: string, nameHint?: string) => {
      const p = path.trim();
      if (!p) return;
      const data = await apiJson<{ id: number; name: string; root_path: string; created: boolean }>("/api/v1/projects/ensure", {
        method: "POST",
        body: JSON.stringify({ root_path: p, name: nameHint || "" }),
      });
      await loadProjects();
      setSelectedId(data.id);
      message.success(data.created ? `已自动创建项目：${data.name}` : `已加载项目：${data.name}`);
    },
    [loadProjects],
  );

  const detectAndLoadFromRoot = useCallback(
    async (rootPath: string) => {
      await ensureProjectForPath(rootPath);
    },
    [ensureProjectForPath],
  );

  const openProjectPicker = async () => {
    if (nativePickerAvailable) {
      await onPickDirectory();
      return;
    }
    setManualPickOpen(true);
  };

  const onPickDirectory = async () => {
    setPickLoading(true);
    try {
      const data = await apiJson<{ path: string }>("/api/v1/fs/pick-directory", { method: "POST" });
      setPickedRootPath(data.path);
      await detectAndLoadFromRoot(data.path);
    } catch (e) {
      message.error(String((e as Error).message));
    } finally {
      setPickLoading(false);
    }
  };

  const onLoadManualPath = async () => {
    const p = manualRootInput.trim();
    if (!p) {
      message.warning("请先填写项目根路径");
      return;
    }
    setManualLoadLoading(true);
    try {
      setPickedRootPath(p);
      await ensureProjectForPath(p);
    } catch (e) {
      message.error(String((e as Error).message));
    } finally {
      setManualLoadLoading(false);
    }
  };

  const saveSettings = async () => {
    if (!settingsDraft.focus_points.length) {
      message.warning("关注点不能为空");
      return;
    }
    try {
      const data = await apiJson<SettingsData>("/api/v1/settings", {
        method: "POST",
        body: JSON.stringify({
          ...settingsDraft,
          ...(textApiKeyTouched ? { llm_text_api_key: textApiKeyDraft } : {}),
          ...(vlApiKeyTouched ? { llm_vl_api_key: vlApiKeyDraft } : {}),
        }),
      });
      setChunkLimit(data.chunk_limit);
      setFocusDefs(data.focus_points);
      setFocusPresets(data.focus_presets || []);
      setSettingsDraft(data);
      setPresetSelectedIndex(0);
      setRulesMdError(data.rules_md_error || null);
      setTextApiKeyDraft("");
      setTextApiKeyTouched(false);
      setVlApiKeyDraft("");
      setVlApiKeyTouched(false);
      const savedCs: ChunkStrategy = data.chunk_strategy === "structured" ? "structured" : "blank";
      if (savedCs !== chunkStrategyAtOpenRef.current) {
        message.warning("分块策略已更新，请重新执行「索引与分块」（或全流程中的索引步骤），否则分析仍基于旧分块结果。");
      }
      setSettingsOpen(false);
      message.success("设置已保存");
    } catch (e) {
      message.error(String((e as Error).message));
    }
  };

  const updateSelectedFocusPrompt = (prompt: string) => {
    setSettingsDraft((s) => {
      if (!s.focus_points.length) return s;
      const idx = Math.max(0, Math.min(focusSelectedIndex, s.focus_points.length - 1));
      const next = [...s.focus_points];
      next[idx] = { ...next[idx], prompt };
      return { ...s, focus_points: next };
    });
  };

  const addPreset = () => {
    const id = `p_${Date.now().toString(36)}`;
    setSettingsDraft((s) => {
      const next = [...(s.focus_presets || [])];
      next.push({ id, name: "新预设", focus_points: [...focusPoints] });
      return { ...s, focus_presets: next };
    });
    setPresetSelectedIndex((_) => (settingsDraft.focus_presets || []).length);
  };

  const confirmDeleteSelectedPreset = () => {
    const arr = settingsDraft.focus_presets || [];
    if (!arr.length) {
      message.info("暂无可删除的预设");
      return;
    }
    const cur = arr[presetSelectedIndex];
    if (!cur) {
      message.info("未选择可删除的预设");
      return;
    }
    Modal.confirm({
      title: "确认删除预设",
      content: `将删除预设「${cur.name || cur.id}」，此操作不可撤销。`,
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: () => {
        deletePreset(presetSelectedIndex);
        message.success("预设已删除");
      },
    });
  };

  const deletePreset = (idx: number) => {
    setSettingsDraft((s) => {
      const arr = [...(s.focus_presets || [])];
      if (idx < 0 || idx >= arr.length) return s;
      arr.splice(idx, 1);
      return { ...s, focus_presets: arr };
    });
    setPresetSelectedIndex((i) => Math.max(0, Math.min(i, Math.max(0, (settingsDraft.focus_presets || []).length - 2))));
  };

  const updatePresetAt = (idx: number, patch: Partial<FocusPreset>) => {
    setSettingsDraft((s) => {
      const arr = [...(s.focus_presets || [])];
      if (idx < 0 || idx >= arr.length) return s;
      arr[idx] = { ...arr[idx], ...patch };
      return { ...s, focus_presets: arr };
    });
  };

  const onPickRulesFile = () => {
    rulesFileInputRef.current?.click();
  };

  const onRulesFileChosen = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    try {
      const text = await f.text();
      const check = await apiJson<{ focus_points: FocusPoint[]; count: number }>("/api/v1/settings/rules-md/validate", {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      Modal.confirm({
        title: "确认加载 rules.md",
        content: `检测通过：共 ${check.count} 个关注点。确认后将覆盖当前关注点并保存 rules.md。`,
        okText: "确认加载",
        cancelText: "取消",
        onOk: async () => {
          const data = await apiJson<SettingsData>("/api/v1/settings/rules-md/import", {
            method: "POST",
            body: JSON.stringify({ text }),
          });
          setChunkLimit(data.chunk_limit);
          setFocusDefs(data.focus_points);
          setFocusPresets(data.focus_presets || []);
          setSettingsDraft(data);
          setFocusSelectedIndex(0);
          setPresetSelectedIndex(0);
          setRulesMdError(data.rules_md_error || null);
          message.success("rules.md 已加载并保存");
        },
      });
    } catch (err) {
      message.error(String((err as Error).message));
    }
  };

  const appendAnalyzeDelta = useCallback(
    (piece: string) => {
      const p = String(piece || "");
      if (!p) return;
      const acc = deltaAccRef.current;
      if (acc && p.startsWith(acc)) {
        const delta = p.slice(acc.length);
        if (delta) {
          deltaAccRef.current += delta;
          appendMilestoneDetail(currentStageKeyRef.current || "stage:分析内容", delta);
        }
        return;
      }
      if (acc && acc.startsWith(p)) return;
      deltaAccRef.current += p;
      appendMilestoneDetail(currentStageKeyRef.current || "stage:分析内容", p);
    },
    [appendMilestoneDetail],
  );

  // 已移除首页「组合建议」入口，保留该函数会导致误导与无用代码

  const renderMilestoneDetail = (m: Milestone) => {
    const t = m.detailText || "";
    if (m.detailKind === "system") {
      return (
        <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}>
          {t}
        </pre>
      );
    }
    if (m.detailKind === "error") {
      return (
        <pre
          style={{
            margin: 0,
            whiteSpace: "pre-wrap",
            color: "#cf1322",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
          }}
        >
          {t}
        </pre>
      );
    }
    return <BusinessMilestoneMarkdown markdown={t} />;
  };

  const stopPipeline = () => {
    if (!pipelineRunning) return;
    terminatedRef.current = true;
    analyzeAbortRef.current?.abort();
    stopConvertRef.current?.();
    stopAnalyzeRef.current?.();
    analyzeAbortRef.current = null;
    stopConvertRef.current = null;
    stopAnalyzeRef.current = null;
    setPipelineRunning(false);
    ensureMilestone("sys:control", "系统调用", "system");
    appendMilestoneDetail("sys:control", "[info] 用户已终止流程。\n");
    setMilestoneStatus("sys:control", "done");
    message.info("流程已终止");
  };

  const sendFollowup = async () => {
    if (selectedId == null) {
      message.warning("请先选择或创建项目");
      return;
    }
    const convId = selectedConversationId;
    if (convId == null) {
      message.warning("请先创建或选择对话");
      return;
    }
    const q = followupText.trim();
    if (!q) {
      message.warning("请输入追问内容");
      return;
    }
    setFollowupRunning(true);
    const abort = new AbortController();
    followupAbortRef.current = abort;
    const mid = `followup:${Date.now().toString(36)}`;
    ensureMilestone(mid, "追问", "business");
    appendMilestoneDetail(mid, `用户：${q}\n\n`);
    try {
      await postFollowupConversationStream(
        selectedId,
        convId,
        { question: q },
        (ev) => {
          if (ev.type === "delta" && typeof ev.text === "string") {
            appendMilestoneDetail(mid, String(ev.text));
          }
          if (ev.type === "final" && typeof (ev as any).markdown === "string") {
            setMilestoneStatus(mid, "done");
          }
        },
        abort.signal,
      );
      setFollowupText("");
    } catch (e) {
      if ((e as Error)?.name === "AbortError") return;
      appendMilestoneDetail(mid, `\n\n[error] ${String((e as Error).message)}\n`);
      setMilestoneStatus(mid, "error");
      message.error(String((e as Error).message));
    } finally {
      followupAbortRef.current = null;
      setFollowupRunning(false);
    }
  };

  const runConvertPhase = async () => {
    if (selectedId == null) throw new Error("未选择项目");
    ensureMilestone("sys:convert", "文档转换", "system");
    setMilestones((prev) =>
      prev.map((m) => (m.id === "sys:convert" ? { ...m, status: "running" as MilestoneStatus } : m)),
    );
    appendMilestoneDetail("sys:convert", "【docs2md】开始转换…\n");
    await new Promise<void>((resolve, reject) => {
      const stop = openConvertStream(
        selectedId,
        (ev) => {
          if (ev.type === "log" && typeof ev.text === "string") {
            appendMilestoneDetail("sys:convert", ev.text + "\n");
          }
          if (ev.type === "complete") {
            stop();
            stopConvertRef.current = null;
            setMilestoneStatus("sys:convert", "done");
            resolve();
          }
          if (ev.type === "error") {
            stop();
            stopConvertRef.current = null;
            setMilestoneStatus("sys:convert", "error");
            reject(new Error(String(ev.message)));
          }
        },
        (e) => {
          stop();
          stopConvertRef.current = null;
          setMilestoneStatus("sys:convert", "error");
          reject(e);
        },
      );
      stopConvertRef.current = () => {
        stop();
        stopConvertRef.current = null;
        setMilestoneStatus("sys:convert", "done");
        resolve();
      };
    });
    if (terminatedRef.current) return;
    appendMilestoneDetail("sys:convert", "【docs2md】转换完成。\n");
    setMilestoneStatus("sys:convert", "done");
  };

  const runIndexPhase = async () => {
    if (selectedId == null) throw new Error("未选择项目");
    ensureMilestone("sys:index", "索引与分块", "system");
    setMilestones((prev) =>
      prev.map((m) => (m.id === "sys:index" ? { ...m, status: "running" as MilestoneStatus } : m)),
    );
    appendMilestoneDetail("sys:index", "【索引】正在将 Markdown 写入索引与分块…\n");
    const idx = await apiJson<{ indexed_documents: number }>(`/api/v1/projects/${selectedId}/index-md`, { method: "POST" });
    appendMilestoneDetail("sys:index", `【索引】完成，已索引 ${idx.indexed_documents} 个文档。\n`);
    setMilestoneStatus("sys:index", "done");
  };

  const runAnalyzePhase = async (focus_points: string[]) => {
    if (selectedId == null) throw new Error("未选择项目");
    if (!focus_points.length) throw new Error("请先选择预设");
    const convId = selectedConversationId ?? (await createConversation(analysisTypeDraft));
    if (convId == null) throw new Error("创建会话失败");
    currentStageKeyRef.current = "";
    deltaAccRef.current = "";
    const analyzeAbort = new AbortController();
    analyzeAbortRef.current = analyzeAbort;
    const fin = await new Promise<{ markdown: string }>((resolve, reject) => {
      let settled = false;
      const safeResolve = (v: { markdown: string }) => {
        if (settled) return;
        settled = true;
        analyzeAbortRef.current = null;
        resolve(v);
      };
      const safeReject = (e: Error) => {
        if (settled) return;
        settled = true;
        analyzeAbortRef.current = null;
        reject(e);
      };
      stopAnalyzeRef.current = () => {
        analyzeAbort.abort();
        safeResolve({ markdown: "" });
      };
      postAnalyzeConversationStream(
        selectedId,
        convId,
        { chunk_limit: chunkLimit, focus_points },
        (ev) => {
          if (ev.type === "delta" && typeof ev.text === "string") {
            appendAnalyzeDelta(ev.text);
          }
          if (ev.type === "stage" && typeof ev.name === "string" && typeof ev.state === "string") {
            const name = String(ev.name);
            const state = String(ev.state);
            const key = `stage:${name}`;
            const kind: LogGroupKind =
              name.includes("错误") ? "error" : name.includes("分析") || name.includes("呈现") ? "business" : "system";
            ensureMilestone(key, name, kind);
            currentStageKeyRef.current = key;
            if (state === "start") {
              const detail = typeof (ev as any).detail === "string" ? String((ev as any).detail) : "";
              if (detail) appendMilestoneDetail(key, `${detail}\n`);
            } else if (state === "end") {
              setMilestoneStatus(key, "done");
            }
          }
          if (ev.type === "final") {
            const md = typeof (ev as any).markdown === "string" ? String((ev as any).markdown) : "";
            safeResolve({ markdown: md });
          }
          if (ev.type === "error") {
            safeReject(new Error(String(ev.message)));
          }
        },
        analyzeAbort.signal,
      ).catch((e) => {
        if (settled) return;
        if ((e as Error)?.name === "AbortError") {
          safeResolve({ markdown: "" });
          return;
        }
        safeReject(e instanceof Error ? e : new Error(String(e)));
      });
    });
    if (terminatedRef.current) return;
    const md = fin.markdown || "";
    ensureMilestone("sys:complete", "流程状态", "system");
    appendMilestoneDetail("sys:complete", "已完成。\n");
    setMilestoneStatus("sys:complete", "done");
    setFinalMarkdown(md);
  };

  const runPipelineTryCatch = async (runBody: () => Promise<void>) => {
    try {
      await runBody();
    } catch (e) {
      if ((e as Error)?.name === "AbortError" || terminatedRef.current) return;
      const msg = String((e as Error).message);
      const stepFallback =
        pipelineStepRef.current === "convert"
          ? "sys:convert"
          : pipelineStepRef.current === "index"
            ? "sys:index"
            : "";
      const target = currentStageKeyRef.current || stepFallback || lastMilestoneIdRef.current || "sys:control";
      const targetLabel =
        target === "sys:convert"
          ? "文档转换"
          : target === "sys:index"
            ? "索引与分块"
            : target.startsWith("stage:")
              ? target.slice(6)
              : "系统调用";
      ensureMilestone(target, targetLabel, "error");
      appendMilestoneDetail(target, `[error] ${msg}\n`);
      setMilestoneStatus(target, "error");
      message.error(msg);
      setPipelineFailModal({ step: pipelineStepRef.current, message: msg });
    } finally {
      setPipelineTaskBrief("");
      setPipelineRunning(false);
      analyzeAbortRef.current = null;
      stopConvertRef.current = null;
      stopAnalyzeRef.current = null;
    }
  };

  const runFullPipeline = async () => {
    if (selectedId == null) {
      message.warning("请先选择或创建项目");
      return;
    }
    if (!selectedPresetId) {
      message.warning("请先选择预设");
      return;
    }
    const preset = focusPresets.find((p) => p.id === selectedPresetId);
    const presetFocusPoints = preset?.focus_points || [];
    if (!preset || presetFocusPoints.length === 0) {
      message.warning("预设无可用关注点，请检查 rules.md 预设配置");
      return;
    }
    setFocusPoints(presetFocusPoints);
    if (selectedConversationId == null) {
      const projName = selected?.name ? String(selected.name) : "当前项目";
      const title = `KA - ${projName} - ${preset.name} - ${formatLocalDateTime(new Date())}`;
      await createConversation("KA", title);
    }
    setPipelineFailModal(null);
    setPipelineRunning(true);
    terminatedRef.current = false;
    deltaAccRef.current = "";
    currentStageKeyRef.current = "";
    setMilestones([]);
    setMilestoneOpenOverrides({});
    setFinalMarkdown("");
    const projName = selected?.name ? String(selected.name) : "当前项目";
    const fpSample = presetFocusPoints.slice(0, 3).join("、");
    const fpRest = presetFocusPoints.length > 3 ? "等" : "";
    const taskBrief = `本次针对项目「${projName}」，将围绕${fpSample}${fpRest}共 ${presetFocusPoints.length} 项关注点开展关联审查。流程将顺序执行：① 文档转换（docs2md 将源文档转为 Markdown）；② 索引与分块（按设置中的分块策略建立可检索片段）；③ 模型分析（结合关注点生成结构化审查结论）。请关注下方各步骤日志；若您刚在设置中修改过分块策略，请务必重新执行索引后再解读分析结果，以免结论仍基于旧分块边界。`;
    setPipelineTaskBrief(taskBrief);
    await runPipelineTryCatch(async () => {
      pipelineStepRef.current = "convert";
      await runConvertPhase();
      if (terminatedRef.current) return;
      pipelineStepRef.current = "index";
      await runIndexPhase();
      if (terminatedRef.current) return;
      pipelineStepRef.current = "analyze";
      await runAnalyzePhase(presetFocusPoints);
      if (terminatedRef.current) return;
      message.success("全流程完成");
    });
  };

  const resumePipelineAfterFailure = async (mode: "convert_chain" | "index_chain" | "analyze_only" | "full") => {
    if (selectedId == null) {
      message.warning("请先选择或创建项目");
      return;
    }
    if (!selectedPresetId) {
      message.warning("请先选择预设");
      return;
    }
    const preset = focusPresets.find((p) => p.id === selectedPresetId);
    const presetFocusPoints = preset?.focus_points || [];
    if (!preset || presetFocusPoints.length === 0) {
      message.warning("预设无可用关注点，请检查 rules.md 预设配置");
      return;
    }
    setFocusPoints(presetFocusPoints);
    setPipelineFailModal(null);
    setPipelineRunning(true);
    terminatedRef.current = false;
    analyzeAbortRef.current?.abort();
    stopConvertRef.current?.();
    stopAnalyzeRef.current = null;
    analyzeAbortRef.current = null;
    stopConvertRef.current = null;
    const projName = selected?.name ? String(selected.name) : "当前项目";
    const fpSample = presetFocusPoints.slice(0, 3).join("、");
    const fpRest = presetFocusPoints.length > 3 ? "等" : "";
    const taskBrief = `本次针对项目「${projName}」，将围绕${fpSample}${fpRest}共 ${presetFocusPoints.length} 项关注点开展关联审查。流程将顺序执行：① 文档转换（docs2md 将源文档转为 Markdown）；② 索引与分块（按设置中的分块策略建立可检索片段）；③ 模型分析（结合关注点生成结构化审查结论）。请关注下方各步骤日志；若您刚在设置中修改过分块策略，请务必重新执行索引后再解读分析结果，以免结论仍基于旧分块边界。`;
    setPipelineTaskBrief(taskBrief);

    if (mode === "full") {
      deltaAccRef.current = "";
      currentStageKeyRef.current = "";
      setMilestones([]);
      setMilestoneOpenOverrides({});
      setFinalMarkdown("");
    } else if (mode === "convert_chain") {
      setMilestones((prev) =>
        prev
          .filter((m) => m.id === "sys:convert")
          .map((m) => ({
            ...m,
            status: "running" as MilestoneStatus,
            detailText: `${m.detailText}\n\n--- 重试文档转换 ---\n`,
          })),
      );
    } else if (mode === "index_chain") {
      setMilestones((prev) => {
        const c = prev.find((m) => m.id === "sys:convert" && m.status === "done");
        if (!c) return prev;
        return [
          { ...c },
          {
            id: "sys:index",
            name: "索引与分块",
            status: "running" as MilestoneStatus,
            detailKind: "system" as LogGroupKind,
            detailText: "【索引】重试…\n",
          },
        ];
      });
    } else if (mode === "analyze_only") {
      setFinalMarkdown("");
      deltaAccRef.current = "";
      currentStageKeyRef.current = "";
      setMilestones((prev) =>
        prev
          .filter((m) => m.id === "sys:convert" || m.id === "sys:index")
          .map((m) => ({ ...m, status: "done" as MilestoneStatus })),
      );
    }

    await runPipelineTryCatch(async () => {
      if (mode === "full") {
        pipelineStepRef.current = "convert";
        await runConvertPhase();
        if (terminatedRef.current) return;
        pipelineStepRef.current = "index";
        await runIndexPhase();
        if (terminatedRef.current) return;
        pipelineStepRef.current = "analyze";
        await runAnalyzePhase(presetFocusPoints);
      } else if (mode === "convert_chain") {
        pipelineStepRef.current = "convert";
        await runConvertPhase();
        if (terminatedRef.current) return;
        pipelineStepRef.current = "index";
        await runIndexPhase();
        if (terminatedRef.current) return;
        pipelineStepRef.current = "analyze";
        await runAnalyzePhase(presetFocusPoints);
      } else if (mode === "index_chain") {
        pipelineStepRef.current = "index";
        await runIndexPhase();
        if (terminatedRef.current) return;
        pipelineStepRef.current = "analyze";
        await runAnalyzePhase(presetFocusPoints);
      } else {
        pipelineStepRef.current = "analyze";
        await runAnalyzePhase(presetFocusPoints);
      }
      if (terminatedRef.current) return;
      message.success("流程已继续完成");
    });
  };

  const exportMarkdown = () => {
    if (!finalMarkdown.trim()) {
      message.warning("暂无可导出的 Markdown，请先完成分析");
      return;
    }
    const name = selected?.name ? String(selected.name).replace(/[^\w\u4e00-\u9fa5\-_.]+/g, "_") : "analysis";
    const filename = `${name}-analysis.md`;
    const blob = new Blob([finalMarkdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    message.success("已导出 Markdown");
  };

  const showMainOutput = useMemo(() => {
    if (chatsOpen) return false;
    if (pipelineRunning) return true;
    if (finalMarkdown.trim()) return true;
    if (milestones.length) return true;
    return false;
  }, [chatsOpen, pipelineRunning, finalMarkdown, milestones.length]);

  return (
    <div className="app-layout">
      <div className="side-nav">
        <Button
          type="text"
          className="side-nav-btn"
          icon={<PlusOutlined />}
          title="新对话"
          onClick={() => setNewConversationOpen(true)}
        />
        <Button
          type="text"
          className="side-nav-btn"
          icon={<CommentOutlined />}
          title="Chats"
          onClick={() => setChatsOpen(true)}
          disabled={selectedId == null}
        />
        <div className="side-nav-spacer" />
        <div className="side-nav-bottom">
          <Button type="text" className="side-nav-btn" icon={<QuestionCircleOutlined />} title="帮助" onClick={() => setHelpOpen(true)} />
          <Button type="text" className="side-nav-btn" icon={<SettingOutlined />} title="设置" onClick={() => setSettingsOpen(true)} />
          <Button type="text" className="side-nav-btn" icon={<UserOutlined />} title="用户" onClick={() => message.info("用户中心：占位")} />
        </div>
      </div>

      <div className="app-shell">
        <div className="main-surface">
          {rulesMdError ? (
            <Alert
              type="error"
              showIcon
              message={`rules.md 格式异常：${rulesMdError}`}
              description="系统已自动回退到 default_rules.md。请修复 rules.md 后刷新页面，或在设置页保存一次。"
              style={{ marginBottom: 10 }}
            />
          ) : null}

          {chatsOpen ? (
            <div style={{ maxWidth: 860, margin: "40px auto 0" }}>
              <Typography.Title level={3} style={{ marginTop: 0 }}>
                {`KA 业务关联审查 · 历史对话（${selected?.name || "未选择项目"}）`}
              </Typography.Title>
              <Text type="secondary">选择一条对话进入后，输入框将显示在底部。</Text>
              <Divider />
              {(conversations || []).length ? (
                <Space direction="vertical" style={{ width: "100%" }} size={8}>
                  {conversations.map((c) => (
                    <Button
                      key={c.id}
                      type={c.id === selectedConversationId ? "primary" : "default"}
                      onClick={() => {
                        setSelectedConversationId(c.id);
                        setChatsOpen(false);
                      }}
                      style={{ textAlign: "left" }}
                    >
                      {c.title || `${c.analysis_type} #${c.id}`}
                    </Button>
                  ))}
                </Space>
              ) : (
                <Text type="secondary">暂无历史对话</Text>
              )}
            </div>
          ) : null}

          {!chatsOpen && showMainOutput ? (
            <>
              <div style={{ marginTop: 12, marginBottom: 16 }}>
                {pipelineRunning ? <Text type="secondary">分析进行中…（可滚动查看实时输出）</Text> : null}
                {pipelineRunning && pipelineTaskBrief ? (
                  <Text style={{ display: "block", marginTop: 8, marginBottom: 10, fontSize: 12, color: "#374151", lineHeight: 1.65 }}>
                    {pipelineTaskBrief}
                  </Text>
                ) : null}
                <div className="raw-stream stream-log process-stream">
                  {milestones.length ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {milestones.map((m) => {
                        const showDetails = (m.detailText || "").trim().length > 0;
                        const done = m.status === "done";
                        const title = done ? `✓ ${m.name} >` : `${m.name} >`;
                        const titleColor = m.status === "error" ? "#cf1322" : "#374151";
                        const defaultOpen = m.status === "running";
                        const o = milestoneOpenOverrides[m.id];
                        const expanded = o !== undefined ? o : defaultOpen;
                        return (
                          <div key={m.id} style={{ fontSize: 12 }}>
                            {showDetails ? (
                              <details
                                style={{ marginTop: 0 }}
                                open={expanded}
                                onToggle={(ev) => {
                                  const el = ev.currentTarget;
                                  setMilestoneOpenOverrides((prev) => ({ ...prev, [m.id]: el.open }));
                                }}
                              >
                                <summary style={{ cursor: "pointer", listStyle: "none", color: titleColor }}>{title}</summary>
                                <div style={{ marginTop: 6, color: "#6b7280" }}>{renderMilestoneDetail(m)}</div>
                              </details>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
              </div>

              {finalMarkdown.trim() ? (
                <div style={{ marginTop: 10 }}>
                  <Space style={{ width: "100%", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <Text strong>结果</Text>
                    <Button icon={<DownloadOutlined />} onClick={exportMarkdown}>
                      导出 md
                    </Button>
                  </Space>
                  <Space.Compact style={{ width: "100%" }}>
                    <Input
                      placeholder="结果已生成，可继续追问…"
                      value={followupText}
                      onChange={(e) => setFollowupText(e.target.value)}
                      onPressEnter={() => void sendFollowup()}
                      disabled={followupRunning || selectedConversationId == null}
                    />
                    <Button
                      type="primary"
                      loading={followupRunning}
                      onClick={() => void sendFollowup()}
                      disabled={selectedConversationId == null}
                    >
                      追问
                    </Button>
                  </Space.Compact>
                  {selectedConversationId == null ? <Text type="secondary">（请先点击左侧「+」创建对话）</Text> : null}
                </div>
              ) : null}
            </>
          ) : null}

      <Modal
        title="流程中断"
        open={pipelineFailModal != null}
        onCancel={() => setPipelineFailModal(null)}
        footer={null}
        width={560}
        destroyOnClose
      >
        {pipelineFailModal ? (
          <Space direction="vertical" style={{ width: "100%" }} size={12}>
            <Text strong>
              失败阶段：
              {pipelineFailModal.step === "convert"
                ? "文档转换"
                : pipelineFailModal.step === "index"
                  ? "索引与分块"
                  : "模型分析"}
            </Text>
            <Text type="danger" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {pipelineFailModal.message}
            </Text>
            <Text type="secondary">排除故障后，可选择从哪一步继续：</Text>
            <Space wrap>
              {pipelineFailModal.step === "convert" ? (
                <>
                  <Button type="primary" onClick={() => void resumePipelineAfterFailure("convert_chain")}>
                    重试转换并继续（索引→分析）
                  </Button>
                  <Button onClick={() => void resumePipelineAfterFailure("full")}>全流程重来</Button>
                </>
              ) : null}
              {pipelineFailModal.step === "index" ? (
                <>
                  <Button type="primary" onClick={() => void resumePipelineAfterFailure("index_chain")}>
                    重试索引并继续分析
                  </Button>
                  <Button onClick={() => void resumePipelineAfterFailure("full")}>全流程重来</Button>
                </>
              ) : null}
              {pipelineFailModal.step === "analyze" ? (
                <>
                  <Button type="primary" onClick={() => void resumePipelineAfterFailure("analyze_only")}>
                    仅重试模型分析
                  </Button>
                  <Button onClick={() => void resumePipelineAfterFailure("index_chain")}>重试索引后再分析</Button>
                  <Button onClick={() => void resumePipelineAfterFailure("full")}>全流程重来</Button>
                </>
              ) : null}
            </Space>
          </Space>
        ) : null}
      </Modal>

      <Modal title="设置" open={settingsOpen} onOk={saveSettings} onCancel={() => setSettingsOpen(false)} width={860} okText="保存">
        <Space direction="vertical" style={{ width: "100%", fontSize: 12 }} size={12}>
          <div>
            <Space wrap align="center" style={{ marginTop: 4 }}>
              <Text strong>chunk 上限（全局）</Text>
              <InputNumber
                min={1}
                max={500}
                value={settingsDraft.chunk_limit}
                onChange={(v) => setSettingsDraft((s) => ({ ...s, chunk_limit: Math.max(1, Math.min(500, Number(v) || 40)) }))}
              />
              <Text strong>分块模式</Text>
              <Radio.Group
                value={settingsDraft.chunk_strategy === "structured" ? "structured" : "blank"}
                onChange={(e) =>
                  setSettingsDraft((s) => ({ ...s, chunk_strategy: e.target.value as ChunkStrategy }))
                }
              >
                <Radio value="blank">简单模式（空行分块）</Radio>
                <Radio value="structured">标题与结构感知模式（按标题/代码围栏）</Radio>
              </Radio.Group>
              <Checkbox checked={!!settingsDraft.disable_image_parse} onChange={(e) => setSettingsDraft((s) => ({ ...s, disable_image_parse: e.target.checked }))}>
                不解析文件中的图片
              </Checkbox>
            </Space>
          </div>
          <Divider style={{ margin: "8px 0" }} />
          <div>
            <Space style={{ width: "100%", justifyContent: "space-between" }}>
              <Text strong>关注点</Text>
              <Button size="small" onClick={onPickRulesFile}>
                加载 rules
              </Button>
            </Space>
            <input ref={rulesFileInputRef} type="file" accept=".md,text/markdown" style={{ display: "none" }} onChange={onRulesFileChosen} />
            <div style={{ display: "flex", gap: 12, marginTop: 8, alignItems: "stretch" }}>
              <div style={{ width: 280, border: "1px solid #d9dfd7", borderRadius: 8, padding: 8, minHeight: 320, maxHeight: 320, overflow: "auto", background: "#f7f9f6" }}>
                <Space direction="vertical" style={{ width: "100%" }} size={6}>
                  {settingsDraft.focus_points.map((fp, idx) => (
                    <Button
                      key={fp.id}
                      type="text"
                      className={idx === focusSelectedIndex ? "focus-chip focus-chip-active" : "focus-chip"}
                      style={{
                        textAlign: "left",
                        justifyContent: "flex-start",
                        width: "100%",
                        borderRadius: 14,
                        border: idx === focusSelectedIndex ? "1px solid #4f7f67" : "1px solid #d9dfd7",
                        background: idx === focusSelectedIndex ? "#dbeadf" : "#eef3ed",
                        color: idx === focusSelectedIndex ? "#2e5f49" : "#3e4a40",
                        fontWeight: idx === focusSelectedIndex ? 600 : 500,
                        boxShadow: idx === focusSelectedIndex ? "0 0 0 1px rgba(79,127,103,0.15)" : "none",
                      }}
                      onClick={() => setFocusSelectedIndex(idx)}
                    >
                      {fp.name || fp.id}
                    </Button>
                  ))}
                </Space>
              </div>
              <div style={{ flex: 1, border: "1px solid #d9dfd7", padding: 10, borderRadius: 8, minHeight: 320, maxHeight: 320, background: "#f7f9f6" }}>
                {settingsDraft.focus_points.length ? (
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <Input.TextArea
                      rows={12}
                      placeholder="该关注点对应的提示词（prompt）"
                      value={settingsDraft.focus_points[focusSelectedIndex]?.prompt}
                      onChange={(e) => updateSelectedFocusPrompt(e.target.value)}
                      style={{ minHeight: 290, maxHeight: 290 }}
                    />
                  </Space>
                ) : (
                  <Text type="secondary">rules.md 未提供可用关注点</Text>
                )}
              </div>
            </div>
          </div>
          <Divider style={{ margin: "8px 0" }} />
          <div>
            <Space style={{ width: "100%", justifyContent: "space-between" }}>
              <Text strong>组合预设</Text>
              <Space>
                <Button size="small" onClick={addPreset}>
                  新增预设
                </Button>
                <Button size="small" danger onClick={confirmDeleteSelectedPreset} disabled={(settingsDraft.focus_presets || []).length === 0}>
                  删除预设
                </Button>
              </Space>
            </Space>
            <div style={{ display: "flex", gap: 12, marginTop: 8, alignItems: "stretch" }}>
              <div
                style={{
                  width: 280,
                  border: "1px solid #d9dfd7",
                  borderRadius: 8,
                  padding: 8,
                  minHeight: 220,
                  maxHeight: 220,
                  overflow: "auto",
                  background: "#f7f9f6",
                }}
              >
                <Space direction="vertical" style={{ width: "100%" }} size={6}>
                  {(settingsDraft.focus_presets || []).map((p, idx) => (
                    <Button
                      key={p.id}
                      type="text"
                      className={idx === presetSelectedIndex ? "focus-chip focus-chip-active" : "focus-chip"}
                      style={{
                        textAlign: "left",
                        justifyContent: "flex-start",
                        width: "100%",
                        borderRadius: 14,
                        border: idx === presetSelectedIndex ? "1px solid #4f7f67" : "1px solid #d9dfd7",
                        background: idx === presetSelectedIndex ? "#dbeadf" : "#eef3ed",
                        color: idx === presetSelectedIndex ? "#2e5f49" : "#3e4a40",
                        fontWeight: idx === presetSelectedIndex ? 600 : 500,
                      }}
                      onClick={() => setPresetSelectedIndex(idx)}
                    >
                      <span>{p.name || p.id}</span>
                    </Button>
                  ))}
                  {(settingsDraft.focus_presets || []).length === 0 ? <Text type="secondary">暂无预设</Text> : null}
                </Space>
              </div>
              <div
                style={{
                  flex: 1,
                  border: "1px solid #d9dfd7",
                  padding: 10,
                  borderRadius: 8,
                  minHeight: 220,
                  maxHeight: 220,
                  background: "#f7f9f6",
                }}
              >
                {(settingsDraft.focus_presets || []).length ? (
                  <Space direction="vertical" style={{ width: "100%" }} size={8}>
                    <Input
                      addonBefore="名称"
                      value={(settingsDraft.focus_presets || [])[presetSelectedIndex]?.name}
                      onChange={(e) => updatePresetAt(presetSelectedIndex, { name: e.target.value })}
                    />
                    <Select
                      mode="multiple"
                      allowClear
                      placeholder="选择该预设包含的关注点"
                      style={{ width: "100%" }}
                      value={(settingsDraft.focus_presets || [])[presetSelectedIndex]?.focus_points || []}
                      options={(settingsDraft.focus_points || []).map((x) => ({ value: x.name, label: x.name }))}
                      onChange={(vals) => updatePresetAt(presetSelectedIndex, { focus_points: vals as string[] })}
                    />
                  </Space>
                ) : (
                  <Text type="secondary">新增一个预设后即可编辑</Text>
                )}
              </div>
            </div>
          </div>
          <Divider style={{ margin: "8px 0" }} />
          <div>
            <Text strong>Model</Text>
            <Space direction="vertical" style={{ width: "100%", marginTop: 8 }} size={8}>
              <div style={{ border: "1px solid #f0f0f0", borderRadius: 8, padding: 10 }}>
                <Text strong>文本大模型</Text>
                <Space wrap style={{ width: "100%", marginTop: 8 }}>
                  <Input
                    style={{ width: 220 }}
                    addonBefore="Provider"
                    placeholder="openai_compatible"
                    value={settingsDraft.llm_settings?.text_provider}
                    onChange={(e) =>
                      setSettingsDraft((s) => ({
                        ...s,
                        llm_settings: {
                          ...(s.llm_settings || {
                            text_provider: "openai_compatible",
                            text_base_url: "",
                            text_model: "qwen3",
                            vl_model: "qwen3-vl-plus",
                            vl_base_url: "",
                          }),
                          text_provider: e.target.value,
                        },
                      }))
                    }
                  />
                  <Input
                    style={{ width: 360 }}
                    addonBefore="Text Base URL"
                    placeholder="https://api.minimaxi.com/v1"
                    value={settingsDraft.llm_settings?.text_base_url}
                    onChange={(e) =>
                      setSettingsDraft((s) => ({
                        ...s,
                        llm_settings: {
                          ...(s.llm_settings || {
                            text_provider: "openai_compatible",
                            text_base_url: "",
                            text_model: "qwen3",
                            vl_model: "qwen3-vl-plus",
                            vl_base_url: "",
                          }),
                          text_base_url: e.target.value,
                        },
                      }))
                    }
                  />
                  <Select
                    mode="tags"
                    maxCount={1}
                    style={{ width: 280 }}
                    placeholder="选择或输入文本模型"
                    value={settingsDraft.llm_settings?.text_model ? [settingsDraft.llm_settings.text_model] : []}
                    allowClear
                    options={TEXT_MODEL_OPTIONS.map((m) => ({ value: m, label: m }))}
                    onChange={(vals) =>
                      setSettingsDraft((s) => ({
                        ...s,
                        llm_settings: { ...s.llm_settings, text_model: String(vals?.[0] || "") },
                      }))
                    }
                  />
                </Space>
                <Space wrap style={{ width: "100%", marginTop: 8 }}>
                  <Input.Password
                    style={{ width: 520 }}
                    addonBefore="文本 Key"
                    placeholder={settingsDraft.llm_settings?.has_text_api_key ? "已配置（如需更新请粘贴新 Key）" : "粘贴文本 API Key"}
                    value={textApiKeyDraft}
                    visibilityToggle={false}
                    autoComplete="off"
                    onChange={(e) => {
                      setTextApiKeyDraft(e.target.value);
                      setTextApiKeyTouched(true);
                    }}
                    onCopy={(e) => e.preventDefault()}
                    onCut={(e) => e.preventDefault()}
                    onKeyDown={(e) => {
                      const withMeta = e.metaKey || e.ctrlKey;
                      const k = e.key.toLowerCase();
                      if (withMeta && (k === "v" || k === "a")) return;
                      if (withMeta && (k === "c" || k === "x")) {
                        e.preventDefault();
                        return;
                      }
                      if (["backspace", "delete", "arrowleft", "arrowright", "tab", "enter"].includes(k)) return;
                      if (!withMeta && k.length === 1) {
                        e.preventDefault();
                      }
                    }}
                    onContextMenu={(e) => e.preventDefault()}
                  />
                  <Button
                    onClick={() => {
                      setTextApiKeyDraft("");
                      setTextApiKeyTouched(true);
                    }}
                  >
                    清空文本 Key
                  </Button>
                </Space>
              </div>

              <div style={{ border: "1px solid #f0f0f0", borderRadius: 8, padding: 10 }}>
                <Text strong>VL 大模型</Text>
                <Space wrap style={{ width: "100%", marginTop: 8 }}>
                  <Select
                    mode="tags"
                    maxCount={1}
                    style={{ width: 320 }}
                    placeholder="选择或输入 VL 模型"
                    value={settingsDraft.llm_settings?.vl_model ? [settingsDraft.llm_settings.vl_model] : []}
                    allowClear
                    options={VL_MODEL_OPTIONS.map((m) => ({ value: m, label: m }))}
                    onChange={(vals) =>
                      setSettingsDraft((s) => ({
                        ...s,
                        llm_settings: { ...s.llm_settings, vl_model: String(vals?.[0] || "") },
                      }))
                    }
                  />
                  <Input
                    style={{ width: 360 }}
                    addonBefore="VL Base URL"
                    placeholder="可选，未填则沿用文本 Base URL/环境配置"
                    value={settingsDraft.llm_settings?.vl_base_url}
                    onChange={(e) => setSettingsDraft((s) => ({ ...s, llm_settings: { ...s.llm_settings, vl_base_url: e.target.value } }))}
                  />
                </Space>
                <Space wrap style={{ width: "100%", marginTop: 8 }}>
                  <Input.Password
                    style={{ width: 520 }}
                    addonBefore="VL Key"
                    placeholder={settingsDraft.llm_settings?.has_vl_api_key ? "已配置（如需更新请粘贴新 Key）" : "粘贴 VL API Key"}
                    value={vlApiKeyDraft}
                    visibilityToggle={false}
                    autoComplete="off"
                    onChange={(e) => {
                      setVlApiKeyDraft(e.target.value);
                      setVlApiKeyTouched(true);
                    }}
                    onCopy={(e) => e.preventDefault()}
                    onCut={(e) => e.preventDefault()}
                    onKeyDown={(e) => {
                      const withMeta = e.metaKey || e.ctrlKey;
                      const k = e.key.toLowerCase();
                      if (withMeta && (k === "v" || k === "a")) return;
                      if (withMeta && (k === "c" || k === "x")) {
                        e.preventDefault();
                        return;
                      }
                      if (["backspace", "delete", "arrowleft", "arrowright", "tab", "enter"].includes(k)) return;
                      if (!withMeta && k.length === 1) {
                        e.preventDefault();
                      }
                    }}
                    onContextMenu={(e) => e.preventDefault()}
                  />
                  <Button
                    onClick={() => {
                      setVlApiKeyDraft("");
                      setVlApiKeyTouched(true);
                    }}
                  >
                    清空 VL Key
                  </Button>
                </Space>
              </div>
            </Space>
          </div>
        </Space>
      </Modal>

      <Modal title="帮助" open={helpOpen} onCancel={() => setHelpOpen(false)} footer={null} width={760} styles={{ body: { fontSize: 12 } }}>
        {helpLoading ? <Spin /> : <SimpleMarkdown markdown={helpMarkdown || "# 帮助\n\n暂无帮助内容。"} />}
      </Modal>
      <Modal
        title="新对话"
        open={newConversationOpen}
        onCancel={() => setNewConversationOpen(false)}
        okText="进入"
        onOk={() => {
          const title = `KA - ${formatLocalDateTime(new Date())}`;
          void createConversation(analysisTypeDraft, title).then(() => setNewConversationOpen(false));
        }}
        width={520}
      >
        <Space direction="vertical" style={{ width: "100%" }} size={10}>
          <Text type="secondary">选择分析功能（目前仅 KA）。</Text>
          <Select
            style={{ width: "100%" }}
            value={analysisTypeDraft}
            options={[{ value: "KA", label: "KA 业务关联审查" }]}
            onChange={(v) => setAnalysisTypeDraft(String(v || "KA"))}
          />
        </Space>
      </Modal>

      <Modal
        title="加载项目目录"
        open={manualPickOpen}
        onCancel={() => setManualPickOpen(false)}
        okText="加载"
        onOk={() => void onLoadManualPath().then(() => setManualPickOpen(false))}
        confirmLoading={manualLoadLoading}
        width={620}
      >
        <Space direction="vertical" style={{ width: "100%" }} size={10}>
          <Text type="secondary">请输入后端可见的项目根路径（容器内路径）。</Text>
          <Input
            value={manualRootInput}
            onChange={(e) => setManualRootInput(e.target.value)}
            onPressEnter={() => void onLoadManualPath().then(() => setManualPickOpen(false))}
          />
        </Space>
      </Modal>
        </div>
      </div>

      {!chatsOpen ? (
        <div className={`composer-overlay ${selectedConversationId ? "composer-overlay-bottom" : "composer-overlay-center"}`}>
          <div className="composer-overlay-inner">
            {!selectedConversationId ? (
              <div className="welcome">
                <div className="welcome-title">Welcome</div>
                <div className="welcome-subtitle">{selected?.name ? `，${selected.name}` : "，请先加载项目目录"}</div>
              </div>
            ) : null}
            <div className="composer">
              <Input.TextArea
                className="composer-textarea"
                rows={4}
                placeholder="I-KA 业务关联审查：选择项目目录与预设，一键完成转换、索引与审查，并可导出 Markdown。"
                value={draftText}
                onChange={(e) => setDraftText(e.target.value)}
              />
              <div className="composer-toolbar">
                <div className="composer-left">
                  <Select
                    className="composer-preset"
                    placeholder="选择预设（必选）"
                    value={selectedPresetId || undefined}
                    allowClear
                    options={focusPresets.map((p) => ({ value: p.id, label: p.name }))}
                    onChange={(v) => {
                      const id = String(v || "");
                      setSelectedPresetId(id);
                      const preset = focusPresets.find((p) => p.id === id);
                      if (preset) {
                        setFocusPoints(preset.focus_points || []);
                      } else {
                        setFocusPoints([]);
                      }
                    }}
                  />
                  <Button shape="circle" icon={<PlusOutlined />} loading={pickLoading} onClick={() => void openProjectPicker()} />
                  {pickedRootPath ? (
                    <span className="composer-path">{tailEllipsis(pickedRootPath, 50)}</span>
                  ) : (
                    <span className="composer-path">未加载项目目录</span>
                  )}
                </div>
                <div className="composer-right">
                  <Tooltip title={pipelineRunning ? "终止" : "开始"}>
                    <Button
                      className="composer-run"
                      shape="circle"
                      danger={pipelineRunning}
                      loading={pipelineRunning}
                      onClick={pipelineRunning ? stopPipeline : runFullPipeline}
                      disabled={selectedId == null || !selectedPresetId}
                      icon={pipelineRunning ? <StopOutlined className="composer-run-icon" /> : <ArrowUpOutlined className="composer-run-icon" />}
                    />
                  </Tooltip>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
