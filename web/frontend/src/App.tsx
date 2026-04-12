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
  Tabs,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  CopyOutlined,
  DownloadOutlined,
  LikeOutlined,
  DislikeOutlined,
  RedoOutlined,
  ArrowUpOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  StopOutlined,
  PlusOutlined,
  CheckOutlined,
  MinusOutlined,
  CloseOutlined,
  CommentOutlined,
  UserOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  apiJson,
  getConversationDetail,
  getPresetHistory,
  openConvertStream,
  postAnalyzeConversationStream,
  postAnalyzeStream,
  postFollowupConversationStream,
} from "./api";
import { parseHelpmeMarkdown } from "./helpTabs";
import SimpleMarkdown from "./SimpleMarkdown";

const { Text, Title } = Typography;

type Project = { id: number; name: string; root_path: string };
type Conversation = {
  id: number;
  analysis_type: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  preset_id?: string | null;
};

type PipelineGateResult = { kind: "cancel" } | { kind: "ok"; convId: number };

type PresetGateState =
  | ({ kind: "mismatch" } & { resolve: (r: PipelineGateResult) => void })
  | ({
      kind: "history";
      latest: { id: number; title: string; updated_at?: string };
      canReuseCurrent: boolean;
      currentConvId: number | null;
    } & { resolve: (r: PipelineGateResult) => void })
  | ({
      kind: "nohist";
      canUseCurrent: boolean;
      snapConvId: number | null;
    } & { resolve: (r: PipelineGateResult) => void });

/** 将 SQLite / ISO 时间格式化为与全流程标题一致的时间串 */
function formatConversationTime(isoSql: string | undefined): string {
  if (!isoSql?.trim()) return "";
  const t = isoSql.trim().replace(" ", "T");
  const d = new Date(t);
  if (!Number.isNaN(d.getTime())) {
    return formatLocalDateTime(d);
  }
  return isoSql.trim();
}

/**
 * 会话列表双行：第一行项目/评审，第二行时间（优先解析标题末尾日期，否则用 updated_at）
 */
function conversationListDisplay(c: Conversation): { headline: string; subline: string } {
  const title = (c.title || "").trim();
  const timeFromApi = formatConversationTime(c.updated_at);
  const parts = title
    .split(/\s*-\s*/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.length >= 4 && /^KA$/i.test(parts[0]!)) {
    const projectName = parts[1] ?? "";
    const preset = parts[2] ?? "";
    const maybeTime = parts[3] ?? "";
    if (/^\d{4}-\d{2}-\d{2}/.test(maybeTime)) {
      const headline = [projectName, preset].filter(Boolean).join(" · ");
      return { headline: headline || title, subline: maybeTime };
    }
  }
  if (parts.length >= 2) {
    const last = parts[parts.length - 1]!;
    if (/^\d{4}-\d{2}-\d{2}/.test(last)) {
      return { headline: parts.slice(0, -1).join(" · "), subline: last };
    }
  }
  return { headline: title || `对话 #${c.id}`, subline: timeFromApi };
}
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
type FocusPreset = {
  id: string;
  name: string;
  focus_points: string[];
  /** 来自「组合使用建议」/设置；非空则替代系统提示中对应默认段落 */
  review_role?: string;
  review_goals_principles?: string;
  output_requirements?: string;
};
type ChunkStrategy = "blank" | "structured";
type MdIndexMode = "incremental" | "full";

type FocusComboTipRow = {
  stage: string;
  recommended: string;
  review_role?: string;
  review_goals_principles?: string;
  output_requirements?: string;
};

type SettingsData = {
  focus_points: FocusPoint[];
  focus_presets?: FocusPreset[];
  chunk_limit: number;
  chunk_strategy?: ChunkStrategy;
  disable_image_parse?: boolean;
  /** md_out 索引：incremental 仅新文件或内容变化；full 清空后全量重建 */
  md_index_mode?: MdIndexMode;
  llm_settings: LlmSettings;
  rules_md_error?: string | null;
  /** 后端实际解析 rules 的路径（用于排查「预设不显示」是否读错目录） */
  repo_root?: string;
  /** 当前唯一使用的规则文件名，由环境变量 AIKA_RULES_FILENAME 指定，默认 rules.md */
  rules_filename?: string;
  rules_md_path?: string;
  focus_combo_tips?: FocusComboTipRow[];
  /** rules.md 中「目的：」行解析出的主输入框功能提示（无则前端用默认占位） */
  rules_composer_hint?: string | null;
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

function formatLocalDateTime(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const REREVIEW_PATTERN_RES = [
  /重新审查/g,
  /再审查/g,
  /重新分析/g,
  /全量重审/g,
  /再跑一遍/g,
  /从头审/g,
  /从头查/g,
  /从头分析/g,
];

function detectRereviewIntent(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  return REREVIEW_PATTERN_RES.some((re) => {
    re.lastIndex = 0;
    return re.test(t);
  });
}

function hasSubstantiveBeyondRereviewKeywords(text: string): boolean {
  let s = text.trim();
  for (const re of REREVIEW_PATTERN_RES) {
    re.lastIndex = 0;
    s = s.replace(re, " ");
  }
  s = s.replace(/\s+/g, " ").trim();
  return s.length >= 4;
}

/** 与后端 analysis_runs.focus_points_json 一致：按关注点展示名称比对（顺序无关、去空） */
function focusPointNamesComparable(a: string[], b: string[]): boolean {
  const norm = (xs: string[]) =>
    [...xs]
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
      .sort((x, y) => x.localeCompare(y, "zh-CN"));
  const aa = norm(a);
  const bb = norm(b);
  if (aa.length !== bb.length) return false;
  return aa.every((v, i) => v === bb[i]);
}

/**
 * 路径展示：前半段可缩为 …/父路径，**最后一级目录名绝不截断**（用于与 CSS 分栏配合）。
 */
function splitPathPrefixAndBasename(path: string, maxTotal = 52): { prefix: string; basename: string; full: string } {
  const raw = String(path || "").trim();
  if (!raw) return { prefix: "", basename: "", full: "" };
  const norm = raw.replace(/[/\\]+$/, "");
  const segs = norm.split(/[/\\]/).filter((x) => x.length > 0);
  if (segs.length === 0) return { prefix: "", basename: raw, full: raw };
  const basename = segs[segs.length - 1]!;
  if (segs.length === 1) return { prefix: "", basename, full: raw };
  const parent = segs.slice(0, -1).join("/");
  const combined = `${parent}/${basename}`;
  if (combined.length <= maxTotal) return { prefix: parent, basename, full: raw };
  const head = "...";
  let tail = parent;
  while (tail.length > 0) {
    const cand = `${head}/${tail}/${basename}`;
    if (cand.length <= maxTotal) return { prefix: `${head}/${tail}`, basename, full: raw };
    const i = tail.indexOf("/");
    tail = i < 0 ? "" : tail.slice(i + 1);
  }
  return { prefix: head, basename, full: raw };
}

/** 简报/欢迎语等：优先用 root_path 最后一级（目录名或文件名），无有效路径时退回数据库中的项目名 */
function displayProjectSubject(selected: Project | null | undefined): string {
  const raw = String(selected?.root_path || "").trim();
  if (raw) {
    const noTrail = raw.replace(/[/\\]+$/, "");
    const segs = noTrail.split(/[/\\]/);
    const last = segs[segs.length - 1];
    if (last) return last;
  }
  const n = selected?.name?.trim();
  return n || "当前项目";
}

const DEFAULT_COMPOSER_PLACEHOLDER =
  "我今天可以为您做什么？";

const COMPOSER_DISCLAIMER = "本系统基于AI内核，可能会犯错，请仔细核查结果";

const REDACTED_THINK_OPEN = /<(think|thinking|redacted_thinking)>/i;
const REDACTED_THINK_CLOSE = /<\/(think|thinking|redacted_thinking)>/i;

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

function normFocusId(s: string): string {
  return s.normalize("NFKC").trim();
}

/** 与后端 _slugify_id（评审节点→预设 id）对齐 */
function slugifyPresetStage(stage: string): string {
  const t = stage.replace(/\*+/g, "").trim();
  let x = t.replace(/\s+/g, "_");
  x = x.replace(/[^\w\u4e00-\u9fff\-]+/gi, "_");
  x = x.replace(/_+/g, "_").replace(/^_|_$/g, "");
  return (x || "preset").toLowerCase();
}

/**
 * 当后端未返回 focus_presets（或旧版 bug）但已有 focus_combo_tips 时，在前端推导预设，
 * 与 _derive_focus_presets_from_combo_tips 行为一致，避免首页「选择预设」为空。
 */
function deriveFocusPresetsFromComboTips(tips: FocusComboTipRow[], focusPoints: FocusPoint[]): FocusPreset[] {
  if (!tips.length || !focusPoints.length) return [];
  const idToName = new Map<string, string>();
  for (const fp of focusPoints) {
    const pid = normFocusId(String(fp.id ?? ""));
    const name = String(fp.name ?? "").trim();
    if (pid && name) idToName.set(pid, name);
  }
  const out: FocusPreset[] = [];
  const seen = new Set<string>();
  for (const row of tips) {
    const stage = String(row.stage ?? "").replace(/\*+/g, "").trim();
    const recommended = String(row.recommended ?? "").trim();
    if (!stage || !recommended) continue;
    const ids = parseFocusIdsFromRecommended(recommended);
    const names = ids.map((fid) => idToName.get(normFocusId(fid))).filter((n): n is string => !!n);
    if (!names.length) continue;
    const pid = `rules_${slugifyPresetStage(stage)}`;
    if (seen.has(pid)) continue;
    seen.add(pid);
    const pr: FocusPreset = { id: pid, name: stage, focus_points: names };
    const rr = String(row.review_role ?? "").trim();
    const rg = String(row.review_goals_principles ?? "").trim();
    const ro = String(row.output_requirements ?? "").trim();
    if (rr) pr.review_role = rr;
    if (rg) pr.review_goals_principles = rg;
    if (ro) pr.output_requirements = ro;
    out.push(pr);
  }
  return out;
}

/** 后端已返回 focus_presets 时直接用；为空则用组合表在前端推导（兼容旧后端 / 偶发空数组） */
function withDerivedFocusPresets(d: SettingsData): SettingsData {
  const raw = d.focus_presets || [];
  if (raw.length > 0) return { ...d, focus_presets: raw };
  const derived = deriveFocusPresetsFromComboTips(d.focus_combo_tips || [], d.focus_points || []);
  return { ...d, focus_presets: derived };
}

const STAGE_FRAGMENT_INDEX = "stage:片段与来源索引";

/** 拆分模型输出中的 thinking 围栏；闭合后 thinkComplete 为 true，用于折叠态 */
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

/**
 * 将最终 Markdown 拆成「思考段（含围栏）」与「对外报告正文」：报告放在里程碑外单独展示。
 */
function splitReportFromAnalysis(md: string): { analysisPart: string; reportPart: string } {
  const t = String(md || "").trim();
  if (!t) return { analysisPart: "", reportPart: "" };
  const closeRe = /<\/(?:think|thinking|redacted_thinking)>/i;
  const closeM = t.match(closeRe);
  if (closeM && closeM.index !== undefined) {
    const endIdx = closeM.index + closeM[0].length;
    return {
      analysisPart: t.slice(0, endIdx).trim(),
      reportPart: t.slice(endIdx).trim(),
    };
  }
  if (/<(think|thinking|redacted_thinking)>/i.test(t)) {
    return { analysisPart: t, reportPart: "" };
  }
  return { analysisPart: "", reportPart: t };
}

/** 「思考分析」里程碑正文：有围栏则只显示围栏内；正文已在下方 final-report 时本小节不再重复提示 */
function effectiveMilestoneBody(
  m: Milestone,
  reportSplit: { analysisPart: string; reportPart: string },
): string {
  const isAnalysis =
    m.id === "stage:思考分析" || m.id === "stage:分析思考" || m.id === "stage:分析内容";
  if (!isAnalysis) return m.detailText || "";
  if (!reportSplit.reportPart.trim()) {
    return m.detailText || "";
  }
  const ap = reportSplit.analysisPart.trim();
  if (ap) return ap;
  /* 无 thinking 围栏时全文作为报告在下方展示，此处留空即可 */
  return "";
}

/** 业务里程碑 Markdown：仅将围栏内 thinking 包在 details 中，前后文与正式段落不折叠 */
function BusinessMilestoneMarkdown({ markdown }: { markdown: string }) {
  const { before, think, after, thinkComplete } = useMemo(() => splitRedactedThinkingBlock(markdown), [markdown]);
  if (!think) {
    return <SimpleMarkdown markdown={markdown || ""} />;
  }
  return (
    <>
      {before.trim() ? <SimpleMarkdown markdown={before} /> : null}
      <details className="milestone-thinking-details" open={!thinkComplete}>
        <summary className="milestone-thinking-summary">思考过程</summary>
        <div className="stream-render-text milestone-analysis-think-stream">{think}</div>
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
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(null);
  const [newConversationOpen, setNewConversationOpen] = useState(false);
  const [chatsOpen, setChatsOpen] = useState(false);
  const [chatSearchQuery, setChatSearchQuery] = useState("");
  const [analysisTypeDraft, setAnalysisTypeDraft] = useState("KA");
  const [draftText, setDraftText] = useState("");
  /** 为 true 后不再显示 rules「目的：」占位，直至 rules_composer_hint 从服务端变化 */
  const [composerHintDismissed, setComposerHintDismissed] = useState(false);
  const prevRulesComposerHintRef = useRef<string | undefined>(undefined);

  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [finalMarkdown, setFinalMarkdown] = useState<string>("");
  /** 解析完成后下发的「每行一个片段」索引全文，用于单独下载；审查结论 finalMarkdown 不含此段 */
  const [fragmentIndexMd, setFragmentIndexMd] = useState("");
  const reportSplit = useMemo(() => splitReportFromAnalysis(finalMarkdown), [finalMarkdown]);

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
  const [presetGate, setPresetGate] = useState<PresetGateState | null>(null);
  const [resultFeedback, setResultFeedback] = useState<"like" | "dislike" | null>(null);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpMarkdown, setHelpMarkdown] = useState<string>("");
  const [helpLoading, setHelpLoading] = useState(false);
  const [settingsDraft, setSettingsDraft] = useState<SettingsData>({
    focus_points: [],
    chunk_limit: 40,
    chunk_strategy: "blank",
    disable_image_parse: true,
    md_index_mode: "incremental",
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
  /** 设置弹窗主 Tab：用于页脚仅在「规则」时显示加载/路径 */
  const [settingsTabKey, setSettingsTabKey] = useState<"doc" | "rules" | "models">("doc");
  /** 规则内子 Tab：切换离开「预设组合」时取消「新增预设」草稿 */
  const [rulesInnerTabKey, setRulesInnerTabKey] = useState<"focus_points" | "presets">("focus_points");
  /** 正在新建预设：名称/关注点/三文案来自 presetCreateDraft，直至确认或取消 */
  const [presetCreating, setPresetCreating] = useState(false);
  const [presetCreateDraft, setPresetCreateDraft] = useState({
    name: "",
    focus_points: [] as string[],
    review_role: "",
    review_goals_principles: "",
    output_requirements: "",
  });

  const chunkStrategyAtOpenRef = useRef<ChunkStrategy>("blank");
  const [milestoneOpenOverrides, setMilestoneOpenOverrides] = useState<Record<string, boolean>>({});
  const rulesFileInputRef = useRef<HTMLInputElement | null>(null);
  const stopConvertRef = useRef<(() => void) | null>(null);
  const stopAnalyzeRef = useRef<(() => void) | null>(null);
  const analyzeAbortRef = useRef<AbortController | null>(null);
  const indexAbortRef = useRef<AbortController | null>(null);
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
  }, []);

  const loadConversations = useCallback(
    async (projectId: number | null) => {
      if (projectId == null) {
        setConversations([]);
        setSelectedConversationId(null);
        return;
      }
      try {
        const data = await apiJson<{ conversations?: Conversation[] }>(`/api/v1/projects/${projectId}/conversations?limit=50`);
        const items = data?.conversations ?? [];
        setConversations(items);
        setSelectedConversationId((prev) => {
          if (prev != null && items.some((c) => c.id === prev)) return prev;
          return items.length ? items[0].id : null;
        });
      } catch {
        setConversations([]);
        setSelectedConversationId(null);
      }
    },
    [],
  );

  const loadSettings = useCallback(async (opts?: { snapshot_chunk_strategy?: boolean }) => {
    const data = await apiJson<SettingsData>("/api/v1/settings");
    const cs: ChunkStrategy = data.chunk_strategy === "structured" ? "structured" : "blank";
    if (opts?.snapshot_chunk_strategy) {
      chunkStrategyAtOpenRef.current = cs;
    }
    const mim: MdIndexMode = data.md_index_mode === "full" ? "full" : "incremental";
    const merged = withDerivedFocusPresets({ ...data, chunk_strategy: cs, md_index_mode: mim });
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

  /** rules 中的「目的：」文案变化时，重新显示为输入框占位提示 */
  useEffect(() => {
    const h = (settingsDraft.rules_composer_hint ?? "").trim();
    if (prevRulesComposerHintRef.current !== h) {
      prevRulesComposerHintRef.current = h;
      setComposerHintDismissed(false);
    }
  }, [settingsDraft.rules_composer_hint]);

  /** 主输入框一旦有内容，不再使用「目的：」占位 */
  useEffect(() => {
    if (draftText.trim()) setComposerHintDismissed(true);
  }, [draftText]);

  /** 预设列表或当前选中变化时：不默认选中任何预设；仅当用户已选且仍存在时同步关注点，否则清空 */
  useEffect(() => {
    if (!focusPresets.length) {
      setSelectedPresetId("");
      setFocusPoints([]);
      return;
    }
    if (selectedPresetId && focusPresets.some((p) => p.id === selectedPresetId)) {
      const p = focusPresets.find((x) => x.id === selectedPresetId)!;
      setFocusPoints(p.focus_points || []);
      return;
    }
    setSelectedPresetId("");
    setFocusPoints([]);
  }, [focusPresets, selectedPresetId]);

  useEffect(() => {
    loadConversations(selectedId).catch((e) => message.error(String((e as Error).message)));
  }, [selectedId, loadConversations]);

  /** 项目列表变化后，若当前选中 id 已不存在则清空（不自动改选其它项目） */
  useEffect(() => {
    if (selectedId != null && !projects.some((p) => p.id === selectedId)) {
      setSelectedId(null);
    }
  }, [projects, selectedId]);

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

  useEffect(() => {
    if (!chatsOpen) setChatSearchQuery("");
  }, [chatsOpen]);

  const selected = useMemo(() => projects.find((p) => p.id === selectedId) || null, [projects, selectedId]);

  const helpTabsParsed = useMemo(() => parseHelpmeMarkdown(helpMarkdown), [helpMarkdown]);

  const createConversation = useCallback(
    async (analysisType: string, title?: string, presetId?: string | null) => {
      if (selectedId == null) {
        message.warning("请先选择或创建项目");
        return null;
      }
      const body: Record<string, unknown> = { analysis_type: analysisType, title: title || "" };
      const pid = (presetId ?? "").trim();
      if (pid) body.preset_id = pid;
      const data = await apiJson<{ id: number; analysis_type: string; title: string }>(`/api/v1/projects/${selectedId}/conversations`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      await loadConversations(selectedId);
      setSelectedConversationId(data.id);
      return data.id;
    },
    [selectedId, loadConversations],
  );

  const createFreshConversationForPreset = useCallback(async () => {
    if (selectedId == null || !selectedPresetId) return null;
    const preset = focusPresets.find((p) => p.id === selectedPresetId);
    if (!preset) return null;
    const projName = displayProjectSubject(selected);
    const title = `KA - ${projName} - ${preset.name} - ${formatLocalDateTime(new Date())}`;
    return createConversation("KA", title, selectedPresetId);
  }, [selectedId, selectedPresetId, focusPresets, selected, createConversation]);

  const prepareConversationForPipeline = useCallback(async (): Promise<number | null> => {
    if (selectedId == null || !selectedPresetId) return null;
    const projectId = selectedId;
    const presetId = selectedPresetId;

    let convId = selectedConversationId;
    let detail: Awaited<ReturnType<typeof getConversationDetail>> | null = null;

    if (convId != null) {
      detail = await getConversationDetail(projectId, convId);
      const bound = detail.preset_id?.trim();
      if (bound && bound !== presetId) {
        const r = await new Promise<PipelineGateResult>((resolve) => setPresetGate({ kind: "mismatch", resolve }));
        if (r.kind === "cancel") return null;
        convId = r.convId;
        detail = await getConversationDetail(projectId, convId);
      }
    }

    const hist = await getPresetHistory(projectId, presetId);

    if (hist.has_reviewed_history && hist.latest_conversation && hist.latest_conversation.id !== convId) {
      const latest = hist.latest_conversation;
      const canReuse =
        convId != null &&
        detail !== null &&
        !detail.has_analysis_run &&
        (!(detail.preset_id ?? "").trim() || detail.preset_id === presetId);

      const r = await new Promise<PipelineGateResult>((resolve) =>
        setPresetGate({
          kind: "history",
          latest,
          canReuseCurrent: canReuse,
          currentConvId: convId,
          resolve,
        }),
      );
      if (r.kind === "cancel") return null;
      convId = r.convId;
      detail = await getConversationDetail(projectId, convId);
    }

    if (!hist.has_reviewed_history) {
      const canUse =
        convId != null &&
        detail !== null &&
        !detail.has_analysis_run &&
        (!(detail.preset_id ?? "").trim() || detail.preset_id === presetId);

      const snapConvId = convId;
      const r = await new Promise<PipelineGateResult>((resolve) =>
        setPresetGate({ kind: "nohist", canUseCurrent: canUse, snapConvId, resolve }),
      );
      if (r.kind === "cancel") return null;
      convId = r.convId;
      detail = convId != null ? await getConversationDetail(projectId, convId) : null;
    }

    if (convId == null) {
      return createFreshConversationForPreset();
    }

    return convId;
  }, [selectedId, selectedConversationId, selectedPresetId, createFreshConversationForPreset]);

  const checkPresetChangeAgainstConversation = useCallback(
    async (nextPresetId: string, previousPresetId: string) => {
      if (selectedId == null || selectedConversationId == null || !nextPresetId) return;
      const d = await getConversationDetail(selectedId, selectedConversationId);
      const bound = d.preset_id?.trim();
      if (!bound || bound === nextPresetId) return;
      const r = await new Promise<PipelineGateResult>((resolve) => setPresetGate({ kind: "mismatch", resolve }));
      if (r.kind === "cancel") {
        setSelectedPresetId(previousPresetId);
        const p = focusPresets.find((x) => x.id === previousPresetId);
        setFocusPoints(p?.focus_points ?? []);
        return;
      }
      setSelectedConversationId(r.convId);
      await loadConversations(selectedId);
    },
    [selectedId, selectedConversationId, focusPresets, loadConversations],
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
      const patched = withDerivedFocusPresets(data);
      setChunkLimit(patched.chunk_limit);
      setFocusDefs(patched.focus_points);
      setFocusPresets(patched.focus_presets || []);
      setSettingsDraft(patched);
      setPresetSelectedIndex(0);
      setRulesMdError(patched.rules_md_error || null);
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

  useEffect(() => {
    if (!settingsOpen) {
      setPresetCreating(false);
      return;
    }
    setSettingsTabKey("doc");
    setRulesInnerTabKey("focus_points");
    setPresetCreating(false);
  }, [settingsOpen]);

  const startCreatePreset = () => {
    setPresetCreating(true);
    setPresetCreateDraft({
      name: "",
      focus_points: [],
      review_role: "",
      review_goals_principles: "",
      output_requirements: "",
    });
  };

  const cancelCreatePreset = () => {
    setPresetCreating(false);
  };

  const commitCreatePreset = () => {
    const name = presetCreateDraft.name.trim();
    if (!name) {
      message.warning("请填写预设名称");
      return;
    }
    if (!presetCreateDraft.focus_points.length) {
      message.warning("请至少选择一个关注点");
      return;
    }
    const id = `p_${Date.now().toString(36)}`;
    const newPreset: FocusPreset = {
      id,
      name,
      focus_points: [...presetCreateDraft.focus_points],
    };
    const rr = presetCreateDraft.review_role.trim();
    const rg = presetCreateDraft.review_goals_principles.trim();
    const ro = presetCreateDraft.output_requirements.trim();
    if (rr) newPreset.review_role = rr;
    if (rg) newPreset.review_goals_principles = rg;
    if (ro) newPreset.output_requirements = ro;

    let newIdx = 0;
    setSettingsDraft((s) => {
      const arr = [...(s.focus_presets || [])];
      newIdx = arr.length;
      arr.push(newPreset);
      return { ...s, focus_presets: arr };
    });
    setPresetSelectedIndex(newIdx);
    setPresetCreating(false);
    message.success("已新增预设");
  };

  const confirmDeletePresetAt = (idx: number) => {
    const arr = settingsDraft.focus_presets || [];
    const cur = arr[idx];
    if (!cur) return;
    Modal.confirm({
      title: "确认删除预设",
      content: `将删除预设「${cur.name || cur.id}」，此操作不可撤销。`,
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: () => {
        deletePreset(idx);
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
    setPresetCreating(false);
    setPresetSelectedIndex((prev) => {
      if (idx === prev) return Math.max(0, prev - 1);
      if (prev > idx) return prev - 1;
      return prev;
    });
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
          const patched = withDerivedFocusPresets(data);
          setChunkLimit(patched.chunk_limit);
          setFocusDefs(patched.focus_points);
          setFocusPresets(patched.focus_presets || []);
          setSettingsDraft(patched);
          setFocusSelectedIndex(0);
          setPresetSelectedIndex(0);
          setRulesMdError(patched.rules_md_error || null);
          setSelectedPresetId("");
          setFocusPoints([]);
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
          appendMilestoneDetail(currentStageKeyRef.current || "stage:思考分析", delta);
        }
        return;
      }
      if (acc && acc.startsWith(p)) return;
      deltaAccRef.current += p;
      appendMilestoneDetail(currentStageKeyRef.current || "stage:思考分析", p);
    },
    [appendMilestoneDetail],
  );

  // 已移除首页「组合建议」入口，保留该函数会导致误导与无用代码

  const renderMilestoneDetail = useCallback(
    (m: Milestone) => {
      const t = effectiveMilestoneBody(m, reportSplit);
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
    },
    [reportSplit],
  );

  const stopPipeline = () => {
    if (!pipelineRunning) return;
    terminatedRef.current = true;
    analyzeAbortRef.current?.abort();
    indexAbortRef.current?.abort();
    stopConvertRef.current?.();
    stopAnalyzeRef.current?.();
    analyzeAbortRef.current = null;
    indexAbortRef.current = null;
    stopConvertRef.current = null;
    stopAnalyzeRef.current = null;
    setPipelineRunning(false);
    ensureMilestone("sys:control", "流程控制", "system");
    appendMilestoneDetail("sys:control", "[info] 用户已终止流程。\n");
    setMilestoneStatus("sys:control", "done");
    message.info("流程已终止");
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
    const ac = new AbortController();
    indexAbortRef.current = ac;
    try {
      const idx = await apiJson<{ indexed_documents: number }>(`/api/v1/projects/${selectedId}/index-md`, {
        method: "POST",
        signal: ac.signal,
      });
      appendMilestoneDetail("sys:index", `【索引】完成，已索引 ${idx.indexed_documents} 个文档。\n`);
      setMilestoneStatus("sys:index", "done");
    } catch (e) {
      if ((e as Error)?.name === "AbortError" || ac.signal.aborted) {
        appendMilestoneDetail("sys:index", "【索引】已中止。\n");
        setMilestoneStatus("sys:index", "done");
        throw new DOMException("Aborted", "AbortError");
      }
      throw e;
    } finally {
      if (indexAbortRef.current === ac) indexAbortRef.current = null;
    }
  };

  const runAnalyzePhase = async (
    focus_points: string[],
    opts?: { convId?: number; incremental_user_notes?: string | null },
  ) => {
    if (selectedId == null) throw new Error("未选择项目");
    if (!focus_points.length) throw new Error("请先选择预设");
    const convId =
      opts?.convId ?? selectedConversationId ?? (await createConversation(analysisTypeDraft, undefined, selectedPresetId || null));
    if (convId == null) throw new Error("创建会话失败");
    currentStageKeyRef.current = "";
    deltaAccRef.current = "";
    const analyzeAbort = new AbortController();
    analyzeAbortRef.current = analyzeAbort;
    const inc = (opts?.incremental_user_notes ?? "").trim();
    const preset = focusPresets.find((p) => p.id === selectedPresetId);
    const analyzeBody: {
      chunk_limit: number;
      focus_points: string[];
      incremental_user_notes?: string;
      review_role?: string;
      review_goals_principles?: string;
      output_requirements?: string;
    } = {
      chunk_limit: chunkLimit,
      focus_points,
    };
    if (inc) analyzeBody.incremental_user_notes = inc;
    const pr = (preset?.review_role ?? "").trim();
    if (pr) analyzeBody.review_role = pr;
    const pg = (preset?.review_goals_principles ?? "").trim();
    if (pg) analyzeBody.review_goals_principles = pg;
    const po = (preset?.output_requirements ?? "").trim();
    if (po) analyzeBody.output_requirements = po;
    setFragmentIndexMd("");
    setMilestones((prev) => prev.filter((m) => m.id !== STAGE_FRAGMENT_INDEX));

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
        analyzeBody,
        (ev) => {
          if (ev.type === "delta" && typeof ev.text === "string") {
            appendAnalyzeDelta(ev.text);
          }
          if (ev.type === "chunk_index" && typeof (ev as { markdown?: string }).markdown === "string") {
            const md = String((ev as { markdown: string }).markdown);
            setFragmentIndexMd(md);
            const key = STAGE_FRAGMENT_INDEX;
            ensureMilestone(key, "片段与来源索引", "business");
            setMilestones((prev) =>
              prev.map((m) => (m.id === key ? { ...m, detailText: md } : m)),
            );
          }
          if (ev.type === "stage" && typeof ev.name === "string" && typeof ev.state === "string") {
            const name = String(ev.name);
            const state = String(ev.state);
            const key = `stage:${name}`;
            const kind: LogGroupKind =
              name.includes("错误")
                ? "error"
                : name.includes("片段") ||
                    name.includes("分析") ||
                    name.includes("呈现") ||
                    name.includes("追问")
                  ? "business"
                  : "system";
            ensureMilestone(key, name, kind);
            currentStageKeyRef.current = key;
            if (state === "start") {
              const detail = typeof (ev as any).detail === "string" ? String((ev as any).detail) : "";
              const d = detail.trim();
              if (d && !/^model=/i.test(d)) appendMilestoneDetail(key, `${detail}\n`);
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
    setFinalMarkdown(md);
  };

  const runFollowupPhase = async (question: string, convId: number) => {
    if (selectedId == null) throw new Error("未选择项目");
    currentStageKeyRef.current = "";
    deltaAccRef.current = "";
    const analyzeAbort = new AbortController();
    analyzeAbortRef.current = analyzeAbort;
    setFragmentIndexMd("");
    setMilestones((prev) => prev.filter((m) => m.id !== STAGE_FRAGMENT_INDEX));

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
      postFollowupConversationStream(
        selectedId,
        convId,
        { question },
        (ev) => {
          if (ev.type === "delta" && typeof ev.text === "string") {
            appendAnalyzeDelta(ev.text);
          }
          if (ev.type === "chunk_index" && typeof (ev as { markdown?: string }).markdown === "string") {
            const md = String((ev as { markdown: string }).markdown);
            setFragmentIndexMd(md);
            const key = STAGE_FRAGMENT_INDEX;
            ensureMilestone(key, "片段与来源索引", "business");
            setMilestones((prev) =>
              prev.map((m) => (m.id === key ? { ...m, detailText: md } : m)),
            );
          }
          if (ev.type === "stage" && typeof ev.name === "string" && typeof ev.state === "string") {
            const name = String(ev.name);
            const state = String(ev.state);
            const key = `stage:${name}`;
            const kind: LogGroupKind =
              name.includes("错误")
                ? "error"
                : name.includes("片段") ||
                    name.includes("分析") ||
                    name.includes("呈现") ||
                    name.includes("追问")
                  ? "business"
                  : "system";
            ensureMilestone(key, name, kind);
            currentStageKeyRef.current = key;
            if (state === "start") {
              const detail = typeof (ev as any).detail === "string" ? String((ev as any).detail) : "";
              const d = detail.trim();
              if (d && !/^model=/i.test(d)) appendMilestoneDetail(key, `${detail}\n`);
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
              : "流程控制";
      ensureMilestone(target, targetLabel, "error");
      appendMilestoneDetail(target, `[error] ${msg}\n`);
      setMilestoneStatus(target, "error");
      message.error(msg);
      setPipelineFailModal({ step: pipelineStepRef.current, message: msg });
    } finally {
      setPipelineRunning(false);
      analyzeAbortRef.current = null;
      indexAbortRef.current = null;
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

    const prepared = await prepareConversationForPipeline();
    if (prepared == null) return;
    const convId = prepared;
    setSelectedConversationId(convId);

    const convDetail = await getConversationDetail(selectedId, convId);
    const draft = draftText.trim();
    const wantRereview = detectRereviewIntent(draft);
    const lastAnalysisNames = convDetail.last_analysis_focus_points ?? [];
    const presetMatchesLastAnalysis = focusPointNamesComparable(presetFocusPoints, lastAnalysisNames);

    if (convDetail.has_analysis_run) {
      /* 预设组合（关注点集合）与上轮 analyze 不一致时，上轮结论不能作为追问依据，须重新全文审查 */
      if (!presetMatchesLastAnalysis) {
        setPipelineFailModal(null);
        setComposerHintDismissed(true);
        setPipelineRunning(true);
        terminatedRef.current = false;
        deltaAccRef.current = "";
        currentStageKeyRef.current = "";
        setFinalMarkdown("");
        setFragmentIndexMd("");
        setResultFeedback(null);
        if (!draft) {
          setPipelineTaskBrief(
            `当前预设组合与历史审查不一致，将针对新预设重新审查（跳过文档转换与索引）。`,
          );
          await runPipelineTryCatch(async () => {
            pipelineStepRef.current = "analyze";
            await runAnalyzePhase(presetFocusPoints, { convId });
            if (terminatedRef.current) return;
            message.success("审查完成");
          });
          return;
        }
        setPipelineTaskBrief(
          `当前预设组合与历史审查不一致，将结合您的说明针对新预设重新审查（跳过文档转换与索引）。`,
        );
        await runPipelineTryCatch(async () => {
          pipelineStepRef.current = "analyze";
          await runAnalyzePhase(presetFocusPoints, { convId, incremental_user_notes: draft });
          if (terminatedRef.current) return;
          message.success("审查完成");
        });
        return;
      }

      if (!draft) {
        message.warning("当前会话已有审查结果。请输入追问内容，或说明需重新审查的增量信息。");
        return;
      }
      if (wantRereview && !hasSubstantiveBeyondRereviewKeywords(draft)) {
        message.warning("重新审查请补充具体增量信息或变更说明。");
        return;
      }

      setPipelineFailModal(null);
      setComposerHintDismissed(true);
      setPipelineRunning(true);
      terminatedRef.current = false;
      deltaAccRef.current = "";
      currentStageKeyRef.current = "";
      setFinalMarkdown("");
      setFragmentIndexMd("");
      setResultFeedback(null);

      if (!wantRereview) {
        setPipelineTaskBrief(
          `会话「${convDetail.title}」已有审查结论，本次将基于分块与历史对话进行追问（不重复文档转换与索引）。`,
        );
        await runPipelineTryCatch(async () => {
          pipelineStepRef.current = "analyze";
          await runFollowupPhase(draft, convId);
          if (terminatedRef.current) return;
          message.success("追问完成");
        });
        return;
      }

      setPipelineTaskBrief(`将沿用已索引分块，并结合您的补充说明重新审查（跳过文档转换与索引）。`);
      await runPipelineTryCatch(async () => {
        pipelineStepRef.current = "analyze";
        await runAnalyzePhase(presetFocusPoints, { convId, incremental_user_notes: draft });
        if (terminatedRef.current) return;
        message.success("重新审查完成");
      });
      return;
    }

    setPipelineFailModal(null);
    setComposerHintDismissed(true);
    setPipelineRunning(true);
    terminatedRef.current = false;
    deltaAccRef.current = "";
    currentStageKeyRef.current = "";
    setMilestones([]);
    setMilestoneOpenOverrides({});
    setFinalMarkdown("");
    setFragmentIndexMd("");
    setResultFeedback(null);
    const projName = displayProjectSubject(selected);
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
      await runAnalyzePhase(presetFocusPoints, { convId });
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
    setComposerHintDismissed(true);
    setPipelineRunning(true);
    terminatedRef.current = false;
    analyzeAbortRef.current?.abort();
    indexAbortRef.current?.abort();
    stopConvertRef.current?.();
    stopAnalyzeRef.current = null;
    analyzeAbortRef.current = null;
    indexAbortRef.current = null;
    stopConvertRef.current = null;
    const projName = displayProjectSubject(selected);
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
      setFragmentIndexMd("");
      setResultFeedback(null);
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
      setResultFeedback(null);
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

  const downloadFragmentIndexMd = useCallback(() => {
    const t = fragmentIndexMd.trim();
    if (!t) {
      message.warning("暂无片段索引，请先完成「解析文档」阶段");
      return;
    }
    const name = displayProjectSubject(selected).replace(/[^\w\u4e00-\u9fa5\-_.]+/g, "_") || "fragments";
    const filename = `${name}-片段索引.md`;
    const blob = new Blob([t], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    message.success("已下载片段索引");
  }, [fragmentIndexMd, selected]);

  const copyFinalMarkdown = async () => {
    const text = finalMarkdown.trim();
    if (!text) {
      message.warning("暂无可复制的内容");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      message.success("已复制到剪贴板");
    } catch {
      message.error("复制失败，请检查浏览器权限");
    }
  };

  const exportMarkdown = () => {
    const text = finalMarkdown.trim();
    if (!text) {
      message.warning("暂无可导出的 Markdown，请先完成分析");
      return;
    }
    const name = displayProjectSubject(selected).replace(/[^\w\u4e00-\u9fa5\-_.]+/g, "_") || "analysis";
    const filename = `${name}-analysis.md`;
    const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
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

  const composerTextPlaceholder = useMemo(() => {
    if (composerHintDismissed) return DEFAULT_COMPOSER_PLACEHOLDER;
    const h = (settingsDraft.rules_composer_hint ?? "").trim();
    return h || DEFAULT_COMPOSER_PLACEHOLDER;
  }, [composerHintDismissed, settingsDraft.rules_composer_hint]);

  const filteredConversations = useMemo(() => {
    const q = chatSearchQuery.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((c) => {
      const { headline, subline } = conversationListDisplay(c);
      const hay = `${headline} ${subline} ${c.title || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [conversations, chatSearchQuery]);

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
              message="规则文件无法加载"
              description={
                <>
                  <div>{rulesMdError}</div>
                  <div style={{ marginTop: 8 }}>
                    不会自动读取 default_rules.md。可将仓库根目录的 default_rules.md 复制为当前活动规则文件，或调用 POST
                    /api/v1/settings/rules-md/restore-default-template 从模板恢复后刷新。
                  </div>
                </>
              }
              style={{ marginBottom: 10 }}
            />
          ) : null}

          {chatsOpen ? (
            <div className="chat-history-page">
              <div className="chat-history-toolbar">
                <Title level={4} className="chat-history-title">
                  会话历史
                </Title>
                <Button type="default" icon={<PlusOutlined />} onClick={() => setNewConversationOpen(true)}>
                  新对话
                </Button>
              </div>
              <Input
                allowClear
                className="chat-history-search"
                placeholder="搜索会话…"
                prefix={<SearchOutlined />}
                value={chatSearchQuery}
                onChange={(e) => setChatSearchQuery(e.target.value)}
              />
              {selected ? (
                <Text type="secondary" className="chat-history-project-hint">
                  当前项目：{displayProjectSubject(selected)}
                </Text>
              ) : (
                <Text type="secondary" className="chat-history-project-hint">
                  请先选择或加载项目后再查看会话。
                </Text>
              )}
              <div className="chat-history-list" role="list">
                {selectedId == null ? (
                  <Text type="secondary">暂无项目，请从侧栏加载目录。</Text>
                ) : filteredConversations.length ? (
                  filteredConversations.map((c) => {
                    const { headline, subline } = conversationListDisplay(c);
                    const active = c.id === selectedConversationId;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        role="listitem"
                        className={`chat-history-item${active ? " chat-history-item--active" : ""}`}
                        onClick={() => {
                          setSelectedConversationId(c.id);
                          setChatsOpen(false);
                        }}
                      >
                        <div className="chat-history-item-title">{headline}</div>
                        {subline ? <div className="chat-history-item-time">{subline}</div> : null}
                      </button>
                    );
                  })
                ) : (
                  <Text type="secondary">{conversations.length ? "无匹配会话" : "暂无历史对话"}</Text>
                )}
              </div>
            </div>
          ) : null}

          {!chatsOpen && showMainOutput ? (
            <>
              <div className="pipeline-output-panel pipeline-output-panel--footer-clear">
                {pipelineTaskBrief ? (
                  <div className="pipeline-output-intro">
                    <div className="pipeline-task-brief">{pipelineTaskBrief}</div>
                  </div>
                ) : null}
                <div className="raw-stream stream-log process-stream">
                  {milestones.length ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {milestones
                        .filter((m) => m.id !== "sys:complete")
                        .flatMap((m) => {
                          const isAnalysisMilestone =
                            m.id === "stage:思考分析" ||
                            m.id === "stage:分析思考" ||
                            m.id === "stage:分析内容";
                          const effectiveText = effectiveMilestoneBody(m, reportSplit);
                          const showDetails = effectiveText.trim().length > 0;
                          const done = m.status === "done";
                          const running = m.status === "running";
                          const lead = done ? "✓ " : running ? "→ " : "　";
                          const displayName = m.id === "stage:分析内容" ? "思考分析" : m.name;
                          const title = `${lead}${displayName} >`;
                          const titleColor = m.status === "error" ? "#cf1322" : "#374151";
                          const defaultOpen = m.status === "running";
                          const o = milestoneOpenOverrides[m.id];
                          const expanded = o !== undefined ? o : defaultOpen;

                          const milestoneBlock = (
                            <div key={m.id} style={{ fontSize: 12 }}>
                              {isAnalysisMilestone ? (
                                showDetails ? (
                                  <>
                                    <div style={{ color: titleColor, fontWeight: 550, marginBottom: 4 }}>{title}</div>
                                    <div style={{ marginTop: 0, color: "#6b7280" }}>{renderMilestoneDetail(m)}</div>
                                  </>
                                ) : null
                              ) : showDetails ? (
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

                          if (m.id === STAGE_FRAGMENT_INDEX && fragmentIndexMd.trim()) {
                            return [
                              milestoneBlock,
                              <div key={`${m.id}-frag-md-btn`} className="fragment-index-download-bar">
                                <Button type="default" size="small" icon={<DownloadOutlined />} onClick={downloadFragmentIndexMd}>
                                  片段索引.md
                                </Button>
                              </div>,
                            ];
                          }
                          return [milestoneBlock];
                        })}
                    </div>
                  ) : null}
                </div>
                {!pipelineRunning && reportSplit.reportPart.trim() ? (
                  <div className="pipeline-final-report">
                    <SimpleMarkdown markdown={reportSplit.reportPart} />
                  </div>
                ) : null}
                {!pipelineRunning && finalMarkdown.trim() ? (
                  <div className="result-actions-below-stream" aria-label="结果操作">
                    <div className="result-export-row">
                      <Button
                        type="default"
                        size="small"
                        className="result-export-md-btn"
                        icon={<DownloadOutlined />}
                        onClick={exportMarkdown}
                      >
                        导出 md
                      </Button>
                    </div>
                    <div className="result-actions-bar-divider" aria-hidden="true" />
                    <div className="result-output-actions">
                      <Space size={4}>
                        <Button type="text" size="small" icon={<CopyOutlined />} onClick={() => void copyFinalMarkdown()} title="复制" />
                        <Button
                          type="text"
                          size="small"
                          icon={<LikeOutlined />}
                          className={resultFeedback === "like" ? "result-feedback-like" : undefined}
                          onClick={() => setResultFeedback((f) => (f === "like" ? null : "like"))}
                          title="有用"
                        />
                        <Button
                          type="text"
                          size="small"
                          icon={<DislikeOutlined />}
                          className={resultFeedback === "dislike" ? "result-feedback-dislike" : undefined}
                          onClick={() => setResultFeedback((f) => (f === "dislike" ? null : "dislike"))}
                          title="无用"
                        />
                        <Button
                          type="text"
                          size="small"
                          icon={<RedoOutlined />}
                          onClick={() => void runFullPipeline()}
                          disabled={pipelineRunning || selectedId == null || !selectedPresetId}
                          title="重新执行全流程"
                        />
                      </Space>
                    </div>
                  </div>
                ) : null}
              </div>
            </>
          ) : null}

      <Modal
        title="会话与预设不一致"
        open={presetGate?.kind === "mismatch"}
        onCancel={() => {
          if (presetGate?.kind !== "mismatch") return;
          presetGate.resolve({ kind: "cancel" });
          setPresetGate(null);
        }}
        footer={null}
        width={560}
        destroyOnClose
      >
        {presetGate?.kind === "mismatch" ? (
          <Space direction="vertical" style={{ width: "100%" }} size={12}>
            <Text type="secondary">
              当前会话已绑定其它预设组合，不宜在同一对话中混用。可切换到该预设下最近一条带审查结果的会话，或新建会话。
            </Text>
            <Space wrap>
              <Button
                onClick={() => {
                  const g = presetGate;
                  if (g?.kind !== "mismatch" || selectedId == null) return;
                  void (async () => {
                    const h = await getPresetHistory(selectedId, selectedPresetId);
                    const id = h.latest_conversation?.id;
                    if (id == null) {
                      message.warning("该预设下暂无带审查结果的会话");
                      return;
                    }
                    setSelectedConversationId(id);
                    g.resolve({ kind: "ok", convId: id });
                    setPresetGate(null);
                  })();
                }}
              >
                切换到最近审查会话
              </Button>
              <Button
                type="primary"
                onClick={() => {
                  const g = presetGate;
                  if (g?.kind !== "mismatch") return;
                  void (async () => {
                    const id = await createFreshConversationForPreset();
                    if (id == null) return;
                    g.resolve({ kind: "ok", convId: id });
                    setPresetGate(null);
                  })();
                }}
              >
                新建会话
              </Button>
              <Button
                onClick={() => {
                  if (presetGate?.kind !== "mismatch") return;
                  presetGate.resolve({ kind: "cancel" });
                  setPresetGate(null);
                }}
              >
                取消
              </Button>
            </Space>
          </Space>
        ) : null}
      </Modal>

      <Modal
        title="该预设已有审查历史"
        open={presetGate?.kind === "history"}
        onCancel={() => {
          if (presetGate?.kind !== "history") return;
          presetGate.resolve({ kind: "cancel" });
          setPresetGate(null);
        }}
        footer={null}
        width={560}
        destroyOnClose
      >
        {presetGate?.kind === "history" ? (
          <Space direction="vertical" style={{ width: "100%" }} size={12}>
            <Text type="secondary">
              存在该预设的审查历史。最近一条：「{presetGate.latest.title}」
              {presetGate.latest.updated_at ? `（${formatConversationTime(presetGate.latest.updated_at)}）` : ""}
            </Text>
            <Space wrap>
              <Button
                type="primary"
                onClick={() => {
                  if (presetGate?.kind !== "history") return;
                  const id = presetGate.latest.id;
                  setSelectedConversationId(id);
                  presetGate.resolve({ kind: "ok", convId: id });
                  setPresetGate(null);
                }}
              >
                切换到该会话
              </Button>
              {presetGate.canReuseCurrent && presetGate.currentConvId != null ? (
                <Button
                  onClick={() => {
                    if (presetGate?.kind !== "history" || presetGate.currentConvId == null) return;
                    presetGate.resolve({ kind: "ok", convId: presetGate.currentConvId });
                    setPresetGate(null);
                  }}
                >
                  仍使用当前会话
                </Button>
              ) : null}
              <Button
                onClick={() => {
                  if (presetGate?.kind !== "history") return;
                  presetGate.resolve({ kind: "cancel" });
                  setPresetGate(null);
                }}
              >
                取消
              </Button>
            </Space>
          </Space>
        ) : null}
      </Modal>

      <Modal
        title="暂无该预设的审查记录"
        open={presetGate?.kind === "nohist"}
        onCancel={() => {
          if (presetGate?.kind !== "nohist") return;
          presetGate.resolve({ kind: "cancel" });
          setPresetGate(null);
        }}
        footer={null}
        width={520}
        destroyOnClose
      >
        {presetGate?.kind === "nohist" ? (
          <Space direction="vertical" style={{ width: "100%" }} size={12}>
            <Text type="secondary">当前项目下尚未有该预设组合产生的审查结果。是否新建会话后再运行全流程？</Text>
            <Space wrap>
              <Button
                type="primary"
                onClick={() => {
                  const g = presetGate;
                  if (g?.kind !== "nohist") return;
                  void (async () => {
                    const id = await createFreshConversationForPreset();
                    if (id == null) return;
                    g.resolve({ kind: "ok", convId: id });
                    setPresetGate(null);
                  })();
                }}
              >
                新建会话并继续
              </Button>
              {presetGate.canUseCurrent && presetGate.snapConvId != null ? (
                <Button
                  onClick={() => {
                    if (presetGate?.kind !== "nohist" || presetGate.snapConvId == null) return;
                    presetGate.resolve({ kind: "ok", convId: presetGate.snapConvId });
                    setPresetGate(null);
                  }}
                >
                  使用当前会话
                </Button>
              ) : null}
              <Button
                onClick={() => {
                  if (presetGate?.kind !== "nohist") return;
                  presetGate.resolve({ kind: "cancel" });
                  setPresetGate(null);
                }}
              >
                取消
              </Button>
            </Space>
          </Space>
        ) : null}
      </Modal>

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

      <Modal
        title="设置"
        open={settingsOpen}
        onOk={saveSettings}
        onCancel={() => setSettingsOpen(false)}
        width={880}
        centered
        okText="保存"
        styles={{ body: { maxHeight: "min(480px, calc(100vh - 200px))", overflowY: "auto", paddingBlock: 12 } }}
        footer={(_, { OkBtn, CancelBtn }) => (
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
              width: "100%",
              flexWrap: "wrap",
            }}
          >
            <div
              style={{
                flex: "1 1 200px",
                minWidth: 0,
                textAlign: "left",
                display: "flex",
                alignItems: "center",
                gap: 10,
                flexWrap: "wrap",
              }}
            >
              {settingsTabKey === "rules" ? (
                <>
                  <Button size="small" onClick={onPickRulesFile}>
                    加载 rules
                  </Button>
                  {settingsDraft.rules_md_path ? (
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      当前规则文件：
                      <Text code style={{ fontSize: 11, wordBreak: "break-all" }}>
                        {settingsDraft.rules_md_path}
                      </Text>
                    </Text>
                  ) : null}
                </>
              ) : (
                <span />
              )}
            </div>
            <Space>
              <CancelBtn />
              <OkBtn />
            </Space>
          </div>
        )}
      >
        <Tabs
          activeKey={settingsTabKey}
          onChange={(k) => setSettingsTabKey(k as "doc" | "rules" | "models")}
          items={[
            {
              key: "doc",
              label: "文档",
              children: (
                <div style={{ fontSize: 12, paddingTop: 4 }}>
                  <Text strong style={{ display: "block", marginBottom: 8 }}>
                    文档分块
                  </Text>
                  <Space direction="vertical" size={10} style={{ width: "100%" }}>
                    <div>
                      <Text type="secondary" style={{ display: "block", marginBottom: 6 }}>
                        chunk 上限（全局）
                      </Text>
                      <InputNumber
                        min={1}
                        max={500}
                        value={settingsDraft.chunk_limit}
                        onChange={(v) => setSettingsDraft((s) => ({ ...s, chunk_limit: Math.max(1, Math.min(500, Number(v) || 40)) }))}
                      />
                    </div>
                    <div>
                      <Text type="secondary" style={{ display: "block", marginBottom: 6 }}>
                        分块模式
                      </Text>
                      <Radio.Group
                        value={settingsDraft.chunk_strategy === "structured" ? "structured" : "blank"}
                        onChange={(e) =>
                          setSettingsDraft((s) => ({ ...s, chunk_strategy: e.target.value as ChunkStrategy }))
                        }
                      >
                        <Space direction="vertical" size={4}>
                          <Radio value="blank">简单模式（空行分块）</Radio>
                          <Radio value="structured">标题与结构感知模式（按标题/代码围栏）</Radio>
                        </Space>
                      </Radio.Group>
                    </div>
                  </Space>
                  <Text type="secondary" style={{ display: "block", marginTop: 10 }}>
                    修改分块策略后须重新执行索引，否则分析仍基于旧分块。
                  </Text>

                  <Divider style={{ margin: "14px 0" }} />

                  <Text strong style={{ display: "block", marginBottom: 8 }}>
                    图片解析
                  </Text>
                  <Checkbox
                    checked={!!settingsDraft.disable_image_parse}
                    onChange={(e) => setSettingsDraft((s) => ({ ...s, disable_image_parse: e.target.checked }))}
                  >
                    不解析文件中的图片（docs2md 转换时跳过 VL 解析）
                  </Checkbox>

                  <Divider style={{ margin: "14px 0" }} />

                  <Text strong style={{ display: "block", marginBottom: 8 }}>
                    文件更新（索引 md_out）
                  </Text>
                  <Radio.Group
                    value={settingsDraft.md_index_mode === "full" ? "full" : "incremental"}
                    onChange={(e) =>
                      setSettingsDraft((s) => ({ ...s, md_index_mode: e.target.value as MdIndexMode }))
                    }
                  >
                    <Space direction="vertical" size={6}>
                      <Radio value="incremental">只解析新文件与内容有变化的文件（默认，较快）</Radio>
                      <Radio value="full">强制全部解析（清空本项目文档索引后全量重建）</Radio>
                    </Space>
                  </Radio.Group>
                </div>
              ),
            },
            {
              key: "rules",
              label: "规则",
              children: (
                <div style={{ fontSize: 12, paddingTop: 4 }}>
                  {(settingsDraft.focus_presets || []).length === 0 ? (
                    <Alert
                      type={
                        (settingsDraft.focus_combo_tips || []).length > 0
                          ? "warning"
                          : rulesMdError
                            ? "error"
                            : "info"
                      }
                      showIcon
                      style={{ marginBottom: 10 }}
                      message={
                        (settingsDraft.focus_combo_tips || []).length > 0
                          ? "已解析「组合使用建议」表格，但未能生成预设"
                          : rulesMdError
                            ? "规则文件解析异常（关注点也可能不完整）；请查看页顶错误条"
                            : "未识别到「组合使用建议」表格"
                      }
                      description={
                        (settingsDraft.focus_combo_tips || []).length > 0
                          ? "通常是因为表格中的 `focus:id` 与关注点 id 不一致（含全角符号差异）。请与 `### focus:…` 中 id 完全一致。若规则文件能解析关注点却仍报错，请重启后端以加载最新选源逻辑。"
                          : "请在活动规则文件内包含「组合使用建议」：须为固定五列表（评审节点、推荐组合的关注点、审查角色、审查目标与原则、输出要求），二级标题须含「组合使用建议」。"
                      }
                    />
                  ) : null}
                  <input ref={rulesFileInputRef} type="file" accept=".md,text/markdown" style={{ display: "none" }} onChange={onRulesFileChosen} />
                  <Tabs
                    size="small"
                    activeKey={rulesInnerTabKey}
                    onChange={(k) => {
                      const key = k as "focus_points" | "presets";
                      setRulesInnerTabKey(key);
                      if (key !== "presets") setPresetCreating(false);
                    }}
                    items={[
                      {
                        key: "focus_points",
                        label: "关注点",
                        children: (
                          <div style={{ display: "flex", gap: 12, marginTop: 4, alignItems: "stretch" }}>
                            <div
                              style={{
                                width: 280,
                                border: "1px solid #d9dfd7",
                                borderRadius: 8,
                                padding: 8,
                                minHeight: 200,
                                maxHeight: 240,
                                overflow: "auto",
                                background: "#f7f9f6",
                              }}
                            >
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
                            <div style={{ flex: 1, border: "1px solid #d9dfd7", padding: 10, borderRadius: 8, minHeight: 200, maxHeight: 240, background: "#f7f9f6" }}>
                              {settingsDraft.focus_points.length ? (
                                <Space direction="vertical" style={{ width: "100%" }}>
                                  <Input.TextArea
                                    rows={8}
                                    placeholder="该关注点对应的提示词（prompt）"
                                    value={settingsDraft.focus_points[focusSelectedIndex]?.prompt}
                                    onChange={(e) => updateSelectedFocusPrompt(e.target.value)}
                                    style={{ minHeight: 180, maxHeight: 200, resize: "none" }}
                                  />
                                </Space>
                              ) : (
                                <Text type="secondary">rules.md 未提供可用关注点</Text>
                              )}
                            </div>
                          </div>
                        ),
                      },
                      {
                        key: "presets",
                        label: "预设组合",
                        children: (() => {
                          const presetsArr = settingsDraft.focus_presets || [];
                          const n = presetsArr.length;
                          const idxSafe = n > 0 ? Math.min(Math.max(0, presetSelectedIndex), n - 1) : 0;
                          const editing = presetCreating;
                          const nameVal = editing ? presetCreateDraft.name : presetsArr[idxSafe]?.name ?? "";
                          const focusVal = editing ? presetCreateDraft.focus_points : presetsArr[idxSafe]?.focus_points ?? [];
                          const roleVal = editing ? presetCreateDraft.review_role : presetsArr[idxSafe]?.review_role ?? "";
                          const goalsVal = editing ? presetCreateDraft.review_goals_principles : presetsArr[idxSafe]?.review_goals_principles ?? "";
                          const outVal = editing ? presetCreateDraft.output_requirements : presetsArr[idxSafe]?.output_requirements ?? "";
                          const showRightFields = editing || n > 0;
                          const activeRow = (i: number) => i === idxSafe && !presetCreating;

                          return (
                            <div style={{ marginTop: 4 }}>
                              <div style={{ display: "flex", gap: 12, alignItems: "stretch" }}>
                                <div
                                  style={{
                                    width: 300,
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: 8,
                                    minHeight: 0,
                                  }}
                                >
                                  <div
                                    style={{
                                      border: "1px solid #d9dfd7",
                                      borderRadius: 8,
                                      padding: 8,
                                      maxHeight: 160,
                                      overflow: "auto",
                                      background: "#f7f9f6",
                                      flexShrink: 0,
                                    }}
                                  >
                                    <Space direction="vertical" style={{ width: "100%" }} size={6}>
                                      {presetsArr.map((p, idx) => (
                                        <div
                                          key={p.id}
                                          style={{
                                            display: "flex",
                                            alignItems: "center",
                                            gap: 4,
                                            width: "100%",
                                          }}
                                        >
                                          <Button
                                            type="text"
                                            className={activeRow(idx) ? "focus-chip focus-chip-active" : "focus-chip"}
                                            style={{
                                              textAlign: "left",
                                              justifyContent: "flex-start",
                                              flex: 1,
                                              minWidth: 0,
                                              borderRadius: 14,
                                              border: activeRow(idx) ? "1px solid #4f7f67" : "1px solid #d9dfd7",
                                              background: activeRow(idx) ? "#dbeadf" : "#eef3ed",
                                              color: activeRow(idx) ? "#2e5f49" : "#3e4a40",
                                              fontWeight: activeRow(idx) ? 600 : 500,
                                            }}
                                            onClick={() => {
                                              setPresetCreating(false);
                                              setPresetSelectedIndex(idx);
                                            }}
                                          >
                                            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name || p.id}</span>
                                          </Button>
                                          <Button
                                            type="text"
                                            size="small"
                                            danger
                                            icon={<CloseOutlined />}
                                            aria-label={`删除预设 ${p.name || p.id}`}
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              confirmDeletePresetAt(idx);
                                            }}
                                          />
                                        </div>
                                      ))}
                                      {presetsArr.length === 0 ? (
                                        <Text type="secondary">暂无预设（若 rules 含五列表「组合使用建议」，导入或保存后将生成）</Text>
                                      ) : null}
                                    </Space>
                                  </div>

                                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                    <Text type="secondary" style={{ flexShrink: 0, fontSize: 12 }}>
                                      名称
                                    </Text>
                                    <Input
                                      placeholder={presetCreating ? "新预设名称" : "选中预设名称"}
                                      value={nameVal}
                                      onChange={(e) => {
                                        const v = e.target.value;
                                        if (presetCreating) {
                                          setPresetCreateDraft((d) => ({ ...d, name: v }));
                                        } else if (n > 0) {
                                          updatePresetAt(idxSafe, { name: v });
                                        }
                                      }}
                                      disabled={!presetCreating && n === 0}
                                      style={{ flex: 1, minWidth: 0 }}
                                    />
                                    {!presetCreating ? (
                                      <Tooltip title="新增预设：点击后清空名称与右侧三字段，填写后点勾确认">
                                        <Button type="default" size="small" icon={<PlusOutlined />} aria-label="新增预设" onClick={startCreatePreset} />
                                      </Tooltip>
                                    ) : (
                                      <Space size={0}>
                                        <Tooltip title="取消新增，不保存草稿">
                                          <Button size="small" icon={<MinusOutlined />} aria-label="取消新增" onClick={cancelCreatePreset} />
                                        </Tooltip>
                                        <Tooltip title="确认新增（需名称与非空关注点）">
                                          <Button
                                            type="primary"
                                            size="small"
                                            icon={<CheckOutlined />}
                                            aria-label="确认新增"
                                            disabled={!presetCreateDraft.name.trim()}
                                            onClick={commitCreatePreset}
                                          />
                                        </Tooltip>
                                      </Space>
                                    )}
                                  </div>

                                  {presetCreating || n > 0 ? (
                                    <Select
                                      mode="multiple"
                                      allowClear
                                      placeholder="选择该预设包含的关注点"
                                      style={{ width: "100%" }}
                                      value={focusVal}
                                      options={(settingsDraft.focus_points || []).map((x) => ({ value: x.name, label: x.name }))}
                                      onChange={(vals) => {
                                        const v = vals as string[];
                                        if (presetCreating) {
                                          setPresetCreateDraft((d) => ({ ...d, focus_points: v }));
                                        } else if (n > 0) {
                                          updatePresetAt(idxSafe, { focus_points: v });
                                        }
                                      }}
                                    />
                                  ) : null}
                                </div>

                                <div
                                  style={{
                                    flex: 1,
                                    border: "1px solid #d9dfd7",
                                    padding: 10,
                                    borderRadius: 8,
                                    minHeight: 260,
                                    background: "#f7f9f6",
                                    display: "flex",
                                    flexDirection: "column",
                                  }}
                                >
                                  {showRightFields ? (
                                    <Space direction="vertical" style={{ width: "100%" }} size={8}>
                                      <div>
                                        <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                                          审查角色
                                        </Text>
                                        <Input.TextArea
                                          rows={2}
                                          placeholder="例如：有丰富经验的 MOM/ERP 实施负责人"
                                          value={roleVal}
                                          onChange={(e) => {
                                            const v = e.target.value;
                                            if (presetCreating) setPresetCreateDraft((d) => ({ ...d, review_role: v }));
                                            else if (n > 0) updatePresetAt(idxSafe, { review_role: v });
                                          }}
                                          style={{ resize: "none" }}
                                        />
                                      </div>
                                      <div>
                                        <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                                          审查目标与原则
                                        </Text>
                                        <Input.TextArea
                                          rows={4}
                                          placeholder="目标、原则、分级与重点识别要求等"
                                          value={goalsVal}
                                          onChange={(e) => {
                                            const v = e.target.value;
                                            if (presetCreating) setPresetCreateDraft((d) => ({ ...d, review_goals_principles: v }));
                                            else if (n > 0) updatePresetAt(idxSafe, { review_goals_principles: v });
                                          }}
                                          style={{ resize: "none" }}
                                        />
                                      </div>
                                      <div>
                                        <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                                          输出要求
                                        </Text>
                                        <Input.TextArea
                                          rows={4}
                                          placeholder="输出章节结构、约束与禁止项（将完整替代默认输出格式说明）"
                                          value={outVal}
                                          onChange={(e) => {
                                            const v = e.target.value;
                                            if (presetCreating) setPresetCreateDraft((d) => ({ ...d, output_requirements: v }));
                                            else if (n > 0) updatePresetAt(idxSafe, { output_requirements: v });
                                          }}
                                          style={{ resize: "none" }}
                                        />
                                      </div>
                                    </Space>
                                  ) : (
                                    <Text type="secondary">点击「名称」右侧 + 新建预设：先点 + 清空并填写，再选关注点，右侧填写三列文案后点勾确认。</Text>
                                  )}
                                </div>
                              </div>
                            </div>
                          );
                        })(),
                      },
                    ]}
                  />
                </div>
              ),
            },
            {
              key: "models",
              label: "模型",
              children: (
                <div style={{ fontSize: 12, paddingTop: 4 }}>
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
              ),
            },
          ]}
        />
      </Modal>

      <Modal title="帮助" open={helpOpen} onCancel={() => setHelpOpen(false)} footer={null} width={820} styles={{ body: { fontSize: 12, paddingTop: 8 } }}>
        {helpLoading ? (
          <Spin />
        ) : helpTabsParsed.ok ? (
          <div className="help-tabs-shell">
            <Tabs
              size="small"
              className="help-modal-tabs"
              items={helpTabsParsed.tabs.map((t) => ({
                key: t.label,
                label: t.label,
                children: (
                  <div className="help-tab-body">
                    <SimpleMarkdown markdown={t.content} />
                  </div>
                ),
              }))}
            />
          </div>
        ) : (
          <div className="help-tabs-shell help-tabs-shell--fallback">
            <div className="help-tab-body">
              <SimpleMarkdown markdown={helpTabsParsed.markdown || "# 帮助\n\n暂无帮助内容。"} />
            </div>
          </div>
        )}
      </Modal>
      <Modal
        title="新对话"
        open={newConversationOpen}
        onCancel={() => setNewConversationOpen(false)}
        okText="进入"
        onOk={() => {
          const title = `KA - ${formatLocalDateTime(new Date())}`;
          void createConversation(analysisTypeDraft, title, selectedPresetId || null).then(() => setNewConversationOpen(false));
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
        <div className={`composer-overlay ${showMainOutput ? "composer-overlay-bottom" : "composer-overlay-center"}`}>
          <div className="composer-overlay-inner">
            {!showMainOutput ? (
              <div className="welcome">
                <div className="welcome-title">Welcome</div>
                <div className="welcome-subtitle">
                  {selected ? `，${displayProjectSubject(selected)}` : "，请先加载项目目录"}
                </div>
              </div>
            ) : null}
            <div className="composer-footer-stack">
              <div className="composer">
                <Input.TextArea
                  className="composer-textarea"
                  rows={4}
                  placeholder={composerTextPlaceholder}
                  value={draftText}
                  onChange={(e) => setDraftText(e.target.value)}
                  style={{ resize: "none" }}
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
                        const prev = selectedPresetId;
                        if (!id) {
                          setSelectedPresetId("");
                          setFocusPoints([]);
                          return;
                        }
                        const preset = focusPresets.find((p) => p.id === id);
                        if (preset) {
                          setFocusPoints(preset.focus_points || []);
                        } else {
                          setFocusPoints([]);
                        }
                        setSelectedPresetId(id);
                        void checkPresetChangeAgainstConversation(id, prev);
                      }}
                    />
                    {!focusPresets.length && settingsDraft.rules_md_path ? (
                      <Text type="secondary" style={{ fontSize: 11, maxWidth: 360 }}>
                        无组合预设：后端正在读取 <Text code>{settingsDraft.rules_md_path}</Text>
                        。若与预期不符，请检查 <Text code>AIKA_REPO_ROOT</Text> 或在设置 → 规则查看说明。
                      </Text>
                    ) : null}
                    <Tooltip title="加载文件或目录">
                      <Button shape="circle" icon={<PlusOutlined />} loading={pickLoading} onClick={() => void openProjectPicker()} />
                    </Tooltip>
                    {selected?.root_path ? (
                      <Tooltip title={selected.root_path}>
                        {(() => {
                          const { prefix, basename, full } = splitPathPrefixAndBasename(selected.root_path, 52);
                          return (
                            <Text className="composer-path-abbrev">
                              {prefix ? (
                                <>
                                  <span className="composer-path-abbrev-prefix">{prefix}</span>
                                  <span className="composer-path-abbrev-sep">/</span>
                                </>
                              ) : null}
                              <span className="composer-path-abbrev-basename">{basename || full}</span>
                            </Text>
                          );
                        })()}
                      </Tooltip>
                    ) : null}
                  </div>
                  <div className="composer-right composer-run-actions">
                    {pipelineRunning ? (
                      <Tooltip title="停止">
                        <span className="composer-run-tooltip-wrap">
                          <Button
                            className="composer-run"
                            shape="circle"
                            danger
                            icon={<StopOutlined className="composer-run-icon" />}
                            onClick={stopPipeline}
                          />
                        </span>
                      </Tooltip>
                    ) : (
                      <Tooltip title="开始全流程">
                        <span className="composer-run-tooltip-wrap">
                          <Button
                            className="composer-run"
                            shape="circle"
                            type="primary"
                            icon={<ArrowUpOutlined className="composer-run-icon" />}
                            disabled={selectedId == null || !selectedPresetId}
                            onClick={() => void runFullPipeline()}
                          />
                        </span>
                      </Tooltip>
                    )}
                  </div>
                </div>
              </div>
              {showMainOutput ? <div className="composer-disclaimer">{COMPOSER_DISCLAIMER}</div> : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
