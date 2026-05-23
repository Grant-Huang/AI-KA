import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { parseUrl, buildUrl } from "./navigation";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Collapse,
  Divider,
  Drawer,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Select,
  Space,
  Spin,
  Tag,
  Tabs,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  LikeOutlined,
  DislikeOutlined,
  RedoOutlined,
  ArrowUpOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  FileSearchOutlined,
  StopOutlined,
  PlusOutlined,
  CheckOutlined,
  MinusOutlined,
  CloseOutlined,
  CommentOutlined,
  UserOutlined,
  SearchOutlined,
  FolderOpenOutlined,
  AuditOutlined,
  BulbOutlined,
  SendOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  EditOutlined,
  EllipsisOutlined,
  HistoryOutlined,
  LogoutOutlined,
  TagOutlined,
  PaperClipOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PushpinOutlined,
  AimOutlined,
  ArrowLeftOutlined,
  StarFilled,
  StarOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { AllSessionsPanel, AllSessionItem } from "./AllSessionsPanel";
import {
  apiJson,
  deleteConversation,
  patchConversation,
  deleteProject,
  fetchTextFile,
  getConversationsGlobal,
  getConversationDetail,
  getConversationMessages,
  getConversationsByPair,
  getProjectIngestStatus,
  getPresetHistory,
  getConversationOutputsIndex,
  postAgentConversationStream,
  postAnalyzeConversationStream,
  postFollowupConversationStream,
  authLogin,
  authLogout,
  authMe,
  getExpertProfile,
  putExpertProfile,
  listVaults,
  discoverVaults,
  registerVault,
  deleteVault,
  exportConversationToObsidian,
  addToReviewQueue,
  initProjectFromUpload,
  type AuthUser,
  type ExpertProfile,
  type ObsidianVault,
  type DiscoveredVault,
} from "./api";
import { parseMemoryInjectedItemsFromMilestonesRaw, useConversationReplay } from "./hooks/useConversationReplay";
import SimpleMarkdown, { ThinkableMarkdown } from "./SimpleMarkdown";
import { ChatWindow } from "./ChatWindow";
import HelpPage from "./pages/help";
import SystemSettingPage from "./pages/system_setting";
import ExtractionPage, { ReviewQueueTab, PendingRulesTab } from "./ExtractionPage";
import { FindingsPanel, type Finding } from "./FindingsPanel";
import type { ReviewQueueItem } from "./api";
import { StageTimeline } from "@meso/ui";
import type { Stage } from "@meso/ui";

const { Text, Title } = Typography;

type StandaloneView = "" | "help" | "settings";

function getStandaloneView(): StandaloneView {
  if (typeof window === "undefined") return "";
  const v = new URLSearchParams(window.location.search).get("view") || "";
  return v === "help" || v === "settings" ? (v as StandaloneView) : "";
}

function openStandaloneWindow(view: Exclude<StandaloneView, "">) {
  if (typeof window === "undefined") return;
  const u = new URL(window.location.href);
  u.searchParams.set("view", view);
  window.open(u.toString(), "_blank", "noopener,noreferrer");
}

function closeStandaloneView() {
  if (typeof window === "undefined") return;
  try {
    window.close();
  } catch {
    // ignore
  }
  const u = new URL(window.location.href);
  u.searchParams.delete("view");
  window.location.href = u.toString();
}

type Project = { id: number; name: string; root_path: string; vault_id?: number | null; archived?: boolean };
type Conversation = {
  id: number;
  project_id?: number;
  project_name?: string;
  project_exists?: boolean;
  project_available?: boolean;
  analysis_type: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  preset_id?: string | null;
  starred?: boolean;
};

type PipelineGateResult = { kind: "cancel" } | { kind: "ok"; convId: number };

type PresetGateState =
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

type ConversationOutputsIndexItem = {
  id: number;
  conversation_id: number;
  kind: string;
  created_at: string;
  final_download_path: string;
  milestones_download_path: string;
  fragments_index_download_path: string | null;
};

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
  embed_model?: string;
  embed_base_url?: string;
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
  /** md_out 索引：incremental 仅新文件或内容变化；full 清空后全量重建 */
  md_index_mode?: MdIndexMode;
  llm_settings: LlmSettings;
  review_domain_error?: string | null;
  /** 后端实际解析审查域的路径（用于排查「预设不显示」是否读错目录） */
  repo_root?: string;
  /** 活动审查技能包 id（默认 package-general） */
  active_skill_package_id?: string;
  skill_packages?: Array<{ id: string; name: string; version?: string; path?: string; description?: string }>;
  skill_packages_root?: string;
  /** 当前活动包的 review_domain.md 绝对路径 */
  review_domain_path?: string;
  focus_combo_tips?: FocusComboTipRow[];
  /** review_domain 前言中「目的：」解析出的主输入框功能提示 */
  composer_hint?: string | null;
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

type PipelineStep = "index" | "analyze";

type OutputEntryKind = "analyze" | "followup" | "rereview";
type OutputEntry = {
  id: string;
  kind: OutputEntryKind;
  convId: number | null;
  at: number;
  title: string;
  markdown: string;
};

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

const STAGE_FRAGMENT_INDEX = "stage:片段与来源索引";

/** 与本地流程里程碑用语对齐（后端 JSONL 仍可能写「解析文档」） */
function milestoneDisplayName(name: string): string {
  const n = String(name || "").trim();
  if (n === "解析文档") return "文档转换";
  return n;
}

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

/**
 * 历史回放用：从单次运行落盘的完整 Markdown 中尽量抽出「思考」展示段。
 * 优先与实时态相同的 fence 拆分；若无闭合 fence 则尝试 redacted_thinking 围栏内文本。
 */
function extractHistoryThinkMarkdown(md: string): string {
  const t = String(md || "");
  const sr = splitReportFromAnalysis(t);
  if (sr.analysisPart.trim()) return sr.analysisPart.trim();
  const rb = splitRedactedThinkingBlock(t);
  if (rb.think.trim()) return rb.think.trim();
  return "";
}

/**
 * 「思考分析」里程碑正文：优先展示流式阶段写入的 detail（含 thinking / 工具日志等），
 * 其次为落盘内容按 fence 拆出的 analysis 段；不再使用「合并到下方」类占位。
 */
function effectiveMilestoneBody(
  m: Milestone,
  reportSplit: { analysisPart: string; reportPart: string },
): string {
  const isAnalysisStage = m.id === "stage:思考分析" || m.name === "思考分析";
  if (!isAnalysisStage) return m.detailText || "";
  const detail = (m.detailText || "").trim();
  if (detail) return m.detailText || "";
  const ap = reportSplit.analysisPart.trim();
  if (ap) return reportSplit.analysisPart;
  return "";
}

/** 业务里程碑 Markdown：支持将围栏内 thinking 作为可折叠段展示（折叠开关由外部标题控制） */
function BusinessMilestoneMarkdown({ markdown, thinkingOpen }: { markdown: string; thinkingOpen?: boolean }) {
  const { before, think, after, thinkComplete } = useMemo(() => splitRedactedThinkingBlock(markdown), [markdown]);
  if (!think) {
    return <SimpleMarkdown markdown={markdown || ""} />;
  }
  return (
    <>
      {before.trim() ? <SimpleMarkdown markdown={before} /> : null}
      {thinkingOpen ?? !thinkComplete ? <div className="stream-render-text milestone-analysis-think-stream">{think}</div> : null}
      {after.trim() ? <SimpleMarkdown markdown={after} /> : null}
    </>
  );
}

function toFencedCodeBlock(lang: string, content: string): string {
  const body = String(content ?? "").replace(/\s+$/, "");
  return `\`\`\`${lang}\n${body}\n\`\`\``;
}

export default function App() {
  const TEXT_MODEL_OPTIONS = ["qwen3", "MiniMax-M2.5"];
  const VL_MODEL_OPTIONS = ["qwen3-vl-plus"];
  const DEFAULT_USERNAME = "Grant";

  const standaloneView = getStandaloneView();
  const isStandaloneHelp = standaloneView === "help";
  const isStandaloneSettings = standaloneView === "settings";
  const isStandalone = isStandaloneHelp || isStandaloneSettings;

  // ── Auth state ────────────────────────────────────────────
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);

  // ── Expert profile state ──────────────────────────────────
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [profileDraft, setProfileDraft] = useState<Omit<ExpertProfile, "profile_completed">>({
    industries: [], production_modes: [], functional_modules: [], focus_areas: [],
  });
  const [profileSaving, setProfileSaving] = useState(false);


  // Obsidian vaults
  const [vaults, setVaults] = useState<ObsidianVault[]>([]);
  const [vaultPickerOpen, setVaultPickerOpen] = useState(false);
  const [discoveredVaults, setDiscoveredVaults] = useState<DiscoveredVault[]>([]);
  const [discoverLoading, setDiscoverLoading] = useState(false);
  const [vaultManualPath, setVaultManualPath] = useState("");
  const [vaultManualRole, setVaultManualRole] = useState<"project" | "knowledge" | "both">("project");
  const [vaultRegLoading, setVaultRegLoading] = useState(false);
  const [selectedVaultId, setSelectedVaultId] = useState<number | null>(null);
  const [indexResolveWikilinks, setIndexResolveWikilinks] = useState(false);
  const [obsidianExportLoading, setObsidianExportLoading] = useState(false);

  const loadVaults = useCallback(async () => {
    try {
      const d = await listVaults();
      setVaults(d.vaults);
    } catch {
      // non-critical
    }
  }, []);

  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(() => parseUrl(window.location.pathname).selectedId);
  const [appMode, setAppMode] = useState<"review" | "extraction">(() => parseUrl(window.location.pathname).appMode);
  const [mainPanel, setMainPanel] = useState<"analyze" | "ingest" | "review_domain" | "all_conversations">(() => parseUrl(window.location.pathname).mainPanel);
  const [reviewMainTab, setReviewMainTab] = useState<"analyze" | "result_review" | "review_queue">(() => parseUrl(window.location.pathname).reviewMainTab);
  const [projectIngest, setProjectIngest] = useState<
    Record<number, { initialized: boolean; chunk_count: number; has_review_records?: boolean }>
  >(
    {},
  );
  const [corpusStaleReason, setCorpusStaleReason] = useState<string>("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(() => parseUrl(window.location.pathname).selectedConversationId);
  const [projectViewOnlyReason, setProjectViewOnlyReason] = useState<string>("");
  const [renameConvId, setRenameConvId] = useState<number | null>(null);
  const [renameConvValue, setRenameConvValue] = useState("");
  // 2026-04：新对话直接进入空白会话页，不再弹窗
  const [newConversationOpen, setNewConversationOpen] = useState(false);
  const [chatSearchQuery, setChatSearchQuery] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem("aika_sidebar_collapsed") === "1"
  );
  const [analysisTypeDraft, setAnalysisTypeDraft] = useState("KA");
  const [draftText, setDraftText] = useState("");
  /** 为 true 后不再显示「目的：」占位，直至 composer_hint 从服务端变化 */
  const [composerHintDismissed, setComposerHintDismissed] = useState(false);
  const prevRulesComposerHintRef = useRef<string | undefined>(undefined);
  const warnedNoPresetsRef = useRef(false);

  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [finalMarkdown, setFinalMarkdown] = useState<string>("");
  const [outputEntries, setOutputEntries] = useState<OutputEntry[]>([]);
  /** 解析完成后下发的「每行一个片段」索引全文，用于单独下载；审查结论 finalMarkdown 不含此段 */
  const [fragmentIndexMd, setFragmentIndexMd] = useState("");
  const [conversationMessages, setConversationMessages] = useState<
    Array<{ id: number; role: string; content: string; created_at?: string }>
  >([]);
  /** 后端会为每次分析写入 role=system 的审计行（分析请求参数），不应与对话混排 */
  const visibleConversationMessages = useMemo(
    () => conversationMessages.filter((m) => m.role === "user" || m.role === "assistant"),
    [conversationMessages],
  );
  const [conversationDownloads, setConversationDownloads] = useState<ConversationOutputsIndexItem[]>([]);
  const [historyRuns, setHistoryRuns] = useState<
    Array<{
      item: ConversationOutputsIndexItem;
      finalMarkdown: string;
      split: { analysisPart: string; reportPart: string };
      memoryInjectedItems: Array<{ id: string; title?: string }>;
    }>
  >([]);
  const reportSplit = useMemo(() => splitReportFromAnalysis(finalMarkdown), [finalMarkdown]);
  const historyAssistantMarkdown = useMemo(() => {
    // 历史回放：取最后一条 assistant 消息作为"最终结果/思考分析"来源
    const last = [...conversationMessages].reverse().find((m) => m.role === "assistant");
    return String(last?.content || "");
  }, [conversationMessages]);
  const historySplit = useMemo(() => splitReportFromAnalysis(historyAssistantMarkdown), [historyAssistantMarkdown]);
  const visibleOutputEntries = useMemo(() => {
    if (selectedConversationId == null) return outputEntries;
    return outputEntries.filter((e) => e.convId === selectedConversationId);
  }, [outputEntries, selectedConversationId]);

  // ── URL ↔ state sync ─────────────────────────────────────
  // Skip first render: state is already initialised from URL via lazy initialisers.
  const _isFirstNavRender = useRef(true);
  useEffect(() => {
    if (_isFirstNavRender.current) { _isFirstNavRender.current = false; return; }
    window.history.replaceState({}, "", buildUrl({ appMode, mainPanel, reviewMainTab, selectedId, selectedConversationId }));
  }, [appMode, mainPanel, reviewMainTab, selectedId, selectedConversationId]);

  // Browser back / forward
  useEffect(() => {
    const onPop = () => {
      const s = parseUrl(window.location.pathname);
      setAppMode(s.appMode);
      setMainPanel(s.mainPanel);
      setReviewMainTab(s.reviewMainTab);
      setSelectedId(s.selectedId);
      setSelectedConversationId(s.selectedConversationId);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Auth check on mount ───────────────────────────────────
  useEffect(() => {
    void (async () => {
      try {
        const user = await authMe();
        setCurrentUser(user);
        // Pre-load existing profile if any
        try {
          const prof = await authMe();
          // Profile data (if any) will be loaded from DB-based profile endpoint
          void prof; // profile_completed is part of AuthUser already
        } catch { /* profile not yet saved */ }
      } catch {
        setCurrentUser(null);
        setLoginOpen(true);
      } finally {
        setAuthLoading(false);
      }
    })();
  }, []);

  const replay = useConversationReplay(selectedId, selectedConversationId);
  useEffect(() => {
    if (selectedConversationId == null) return;
    if (!replay.entries.length) return;
    setOutputEntries((prev) => {
      const others = prev.filter((e) => e.convId !== selectedConversationId);
      return [...others, ...(replay.entries as any as OutputEntry[])];
    });
  }, [replay.entries, selectedConversationId]);
  useEffect(() => {
    if (!replay.milestones) return;
    setMilestones([]);
    setFragmentIndexMd("");
    currentStageKeyRef.current = "";
    lastMilestoneIdRef.current = "";
    for (const obj of replay.milestones.events as any[]) {
      if (obj?.type === "stage" && typeof obj.stage === "string" && typeof obj.status === "string") {
        const name = String(obj.stage);
        const state = String(obj.status);
        const key = `stage:${name}`;
        const kind: LogGroupKind =
          name.includes("错误")
            ? "error"
            : name.includes("片段") || name.includes("分析") || name.includes("呈现") || name.includes("追问")
              ? "business"
              : "system";
        ensureMilestone(key, name, kind);
        currentStageKeyRef.current = key;
        if (state === "active") {
          const detail = typeof obj.detail === "string" ? String(obj.detail) : "";
          const d = detail.trim();
          if (d && !/^model=/i.test(d)) appendMilestoneDetail(key, `${detail}\n`);
        } else if (state === "done") {
          setMilestoneStatus(key, "done");
        } else if (state === "error") {
          setMilestoneStatus(key, "error");
        }
        continue;
      }
      if (obj?.type === "agent_decision") {
        const key = "stage:Agent:routing";
        ensureMilestone(key, "Agent:routing", "system");
        const pretty = (() => {
          try {
            return JSON.stringify(obj.decision, null, 2);
          } catch {
            return String(obj.decision);
          }
        })();
        appendMilestoneDetail(key, `\n\n[agent_decision]\n${toFencedCodeBlock("json", pretty)}\n`);
        continue;
      }
      if (obj?.type === "chunk_index" && typeof obj.markdown === "string") {
        const md = String(obj.markdown);
        setFragmentIndexMd(md);
        const key = STAGE_FRAGMENT_INDEX;
        ensureMilestone(key, "片段与来源索引", "business");
        setMilestones((prev) => prev.map((mm) => (mm.id === key ? { ...mm, detailText: md } : mm)));
        continue;
      }
      if (obj?.type === "memory_injected" && Array.isArray(obj.items)) {
        const thinkKey = "stage:思考分析";
        ensureMilestone(thinkKey, "思考分析", "business");
        const parsed: Array<{ id: string; title?: string }> = [];
        for (const x of obj.items) {
          if (x && typeof x === "object" && "id" in x) {
            const id = String((x as { id?: unknown }).id ?? "").trim();
            if (id) parsed.push({ id, title: String((x as { title?: unknown }).title ?? "").trim() || undefined });
          }
        }
        if (parsed.length) {
          const lines = parsed.map((m) => {
            const tit = m.title ? ` — ${m.title}` : "";
            return `- ${m.id}${tit}`;
          });
          appendMilestoneDetail(thinkKey, `\n\n【加载的记忆】\n${lines.join("\n")}\n`);
        }
        continue;
      }
      if (obj?.type === "error" && typeof obj.message === "string") {
        const target = currentStageKeyRef.current || lastMilestoneIdRef.current || "sys:control";
        ensureMilestone(target, target.replace(/^stage:/, ""), "error");
        appendMilestoneDetail(target, `${String(obj.message)}\n`);
        setMilestoneStatus(target, "error");
      }
    }
  }, [replay.milestones]);

  const [chunkLimit, setChunkLimit] = useState(40);
  // Sprint 2+5: multi-turn conversation state
  const [deepMode, setDeepMode] = useState(false);
  const [sessionFindings, setSessionFindings] = useState<Finding[]>([]);
  const [reportLoading, setReportLoading] = useState(false);
  const [nativePickerAvailable, setNativePickerAvailable] = useState(true);
  const [pickLoading, setPickLoading] = useState(false);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [uploadModalMode, setUploadModalMode] = useState<"init" | "append">("init");
  const [uploadStep, setUploadStep] = useState<1 | 2>(1);
  const [uploadModalVaultId, setUploadModalVaultId] = useState<number | null>(null);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadRelPaths, setUploadRelPaths] = useState<string[]>([]);
  const [uploadProjectName, setUploadProjectName] = useState("");
  const [uploadLoading, setUploadLoading] = useState(false);
  const uploadInputRef = useRef<HTMLInputElement>(null);

  // Derived: file type summary for upload preview
  const uploadFileSummary = React.useMemo(() => {
    const pass = new Set(["md", "txt", "markdown"]);
    const conv = new Set(["docx", "doc", "pdf", "xlsx", "xls", "pptx", "ppt", "html", "htm"]);
    let passCount = 0, convCount = 0, otherCount = 0;
    for (const f of uploadFiles) {
      const ext = (f.name.split(".").pop() || "").toLowerCase();
      if (pass.has(ext)) passCount++;
      else if (conv.has(ext)) convCount++;
      else otherCount++;
    }
    return { passCount, convCount, otherCount };
  }, [uploadFiles]);
  const [focusPoints, setFocusPoints] = useState<string[]>([]);
  const [focusDefs, setFocusDefs] = useState<FocusPoint[]>([]);
  const [focusPresets, setFocusPresets] = useState<FocusPreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState<string>("");

  // 会话消息流（同一会话多轮追问/回答视为一条会话记录）
  useEffect(() => {
    let alive = true;
    setConversationMessages([]);
    setConversationDownloads([]);
    setCorpusStaleReason("");
    setSessionFindings([]);
    void (async () => {
      if (selectedId == null || selectedConversationId == null) return;
      try {
        const detail = await getConversationDetail(selectedId, selectedConversationId);
        if (!alive) return;
        if (detail?.preset_id) {
          const pid = String(detail.preset_id);
          setSelectedPresetId(pid);
          const preset = (focusPresets || []).find((p) => p.id === pid);
          if (preset) setFocusPoints(preset.focus_points || []);
        }

        const msgs = await getConversationMessages(selectedId, selectedConversationId, 200);
        if (!alive) return;
        setConversationMessages(Array.isArray(msgs.messages) ? msgs.messages : []);

        const idx = await getConversationOutputsIndex(selectedId, selectedConversationId, 50);
        if (!alive) return;
        setConversationDownloads(Array.isArray(idx.items) ? idx.items : []);

        // 语料就绪检查：若索引被清空/删除，历史会话仅供参考
        try {
          const st = await getProjectIngestStatus(selectedId);
          if (!alive) return;
          setProjectIngest((prev) => ({
            ...prev,
            [selectedId]: {
              initialized: !!st.initialized,
              chunk_count: Number(st.chunk_count) || 0,
              has_review_records: !!(st as any)?.has_review_records,
            },
          }));
          setCorpusStaleReason(st.initialized ? "" : "语料已过期，历史会话仅供参考。");
        } catch {
          if (!alive) return;
          setCorpusStaleReason("语料已过期，历史会话仅供参考。");
        }
      } catch (e) {
        if (!alive) return;
        message.error(String((e as Error).message || e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [selectedId, selectedConversationId, focusPresets]);

  // 历史：按 outputs-index 全量回放（每次分析/追问/复审都作为一组 run）
  useEffect(() => {
    let alive = true;
    setHistoryRuns([]);
    void (async () => {
      if (!selectedConversationId) return;
      const items = Array.isArray(conversationDownloads) ? conversationDownloads : [];
      if (!items.length) return;
      // 避免一次会话输出过多导致页面卡顿：先限制到最近 30 组
      const take = items.slice(0, 30);
      const rebuilt: Array<{
        item: ConversationOutputsIndexItem;
        finalMarkdown: string;
        split: { analysisPart: string; reportPart: string };
        memoryInjectedItems: Array<{ id: string; title?: string }>;
      }> = [];
      for (const it of take) {
        if (!alive) return;
        let md = "";
        try {
          md = await fetchTextFile(it.final_download_path);
        } catch {
          md = "";
        }
        let memoryInjectedItems: Array<{ id: string; title?: string }> = [];
        const mp = it.milestones_download_path;
        if (mp) {
          try {
            const rawMs = await fetchTextFile(mp);
            memoryInjectedItems = parseMemoryInjectedItemsFromMilestonesRaw(rawMs);
          } catch {
            memoryInjectedItems = [];
          }
        }
        rebuilt.push({
          item: it,
          finalMarkdown: md,
          split: splitReportFromAnalysis(md),
          memoryInjectedItems,
        });
      }
      if (!alive) return;
      setHistoryRuns(rebuilt);
    })();
    return () => {
      alive = false;
    };
  }, [conversationDownloads, selectedConversationId]);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  /** 历史会话：里程碑与报告拆分与「最后一条助手消息」对齐；实时跑批用当前 finalMarkdown */
  const activeReportSplit = useMemo(() => {
    if (!pipelineRunning && selectedConversationId != null) return historySplit;
    return reportSplit;
  }, [pipelineRunning, selectedConversationId, historySplit, reportSplit]);
  const [pipelineTaskBrief, setPipelineTaskBrief] = useState("");
  const [lastSubmittedUserMessage, setLastSubmittedUserMessage] = useState<{ text: string; created_at: string } | null>(null);
  const [problemAnalysis, setProblemAnalysis] = useState<string>("");
  const userExpandedMilestonesRef = useRef<Set<string>>(new Set());
  /** 可选：覆盖默认记忆检索词（默认后端用关注点拼接） */
  const [memoryQueryDraft, setMemoryQueryDraft] = useState("");
  const [pipelineFailModal, setPipelineFailModal] = useState<{ step: PipelineStep; message: string } | null>(null);
  const [presetGate, setPresetGate] = useState<PresetGateState | null>(null);
  const [resultFeedback, setResultFeedback] = useState<"like" | "dislike" | null>(null);

  const [settingsOpen, setSettingsOpen] = useState(isStandaloneSettings);
  const [helpOpen, setHelpOpen] = useState(isStandaloneHelp);
  const [helpMarkdown, setHelpMarkdown] = useState<string>("");
  const [helpLoading, setHelpLoading] = useState(false);
  const [settingsDraft, setSettingsDraft] = useState<SettingsData>({
    focus_points: [],
    chunk_limit: 40,
    chunk_strategy: "blank",
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
  const [reviewDomainError, setReviewDomainError] = useState<string | null>(null);
  const [textApiKeyDraft, setTextApiKeyDraft] = useState("");
  const [textApiKeyTouched, setTextApiKeyTouched] = useState(false);
  const [vlApiKeyDraft, setVlApiKeyDraft] = useState("");
  const [vlApiKeyTouched, setVlApiKeyTouched] = useState(false);
  const [focusSelectedIndex, setFocusSelectedIndex] = useState(0);
  const [presetSelectedIndex, setPresetSelectedIndex] = useState(0);
  /** 设置弹窗主 Tab：用于页脚仅在「审查域」时显示加载/路径 */
  const [settingsTabKey, setSettingsTabKey] = useState<"doc" | "models">("doc");
  /** 审查域内子 Tab：切换离开「预设组合」时取消「新增预设」草稿 */
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
  const stopAnalyzeRef = useRef<(() => void) | null>(null);
  const analyzeAbortRef = useRef<AbortController | null>(null);
  const indexAbortRef = useRef<AbortController | null>(null);
  const terminatedRef = useRef(false);
  const deltaAccRef = useRef<string>(""); // accumulated model-output text used for dedup
  const currentStageKeyRef = useRef<string>("");
  const lastMilestoneIdRef = useRef<string>("");
  const pipelineStepRef = useRef<PipelineStep>("index");

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

  // ── Auth handlers ─────────────────────────────────────────
  const handleLogin = async () => {
    if (!loginUsername.trim() || !loginPassword) return;
    setLoginLoading(true);
    setLoginError("");
    try {
      const user = await authLogin(loginUsername.trim(), loginPassword);
      setCurrentUser(user);
      setLoginOpen(false);
      setLoginUsername("");
      setLoginPassword("");
    } catch (e: unknown) {
      setLoginError(e instanceof Error ? e.message : "登录失败");
    } finally {
      setLoginLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      await authLogout();
    } catch { /* ignore */ }
    setCurrentUser(null);
    setLoginOpen(true);
  };

  const handleSaveProfile = async () => {
    setProfileSaving(true);
    try {
      await apiJson("/api/v1/auth/expert-profile", { method: "PUT", body: JSON.stringify(profileDraft) });
      setCurrentUser((u) => u ? { ...u, profile_completed: true } : u);
      setProfileModalOpen(false);
      void message.success("画像已保存");
    } catch (e: unknown) {
      void message.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setProfileSaving(false);
    }
  };

  const navPush = useCallback((partial: Partial<Parameters<typeof buildUrl>[0]>) => {
    window.history.pushState({}, "", buildUrl({
      appMode, mainPanel, reviewMainTab, selectedId, selectedConversationId, ...partial,
    }));
  }, [appMode, mainPanel, reviewMainTab, selectedId, selectedConversationId]);

  const handleStartFromReviewQueue = (item: ReviewQueueItem) => {
    window.sessionStorage.setItem("aika_initial_rq_item", JSON.stringify(item));
    setAppMode("extraction");
    setReviewMainTab("analyze");
  };

  const loadProjects = useCallback(async () => {
    const data = await apiJson<{
      projects: Array<Project & { status?: { initialized: boolean; chunk_count: number; has_review_records: boolean } }>
    }>("/api/v1/projects?with_status=true");
    const items = data.projects || [];
    setProjects(items.map((p) => ({ id: p.id, name: p.name, root_path: p.root_path, vault_id: p.vault_id, archived: p.archived })));
    const next: Record<number, { initialized: boolean; chunk_count: number; has_review_records?: boolean }> = {};
    for (const p of items) {
      if (p.status) {
        next[p.id] = { initialized: p.status.initialized, chunk_count: p.status.chunk_count, has_review_records: p.status.has_review_records };
      } else {
        next[p.id] = { initialized: false, chunk_count: 0 };
      }
    }
    setProjectIngest(next);
  }, []);

  const loadConversations = useCallback(async (opts?: { q?: string }) => {
    try {
      const data = await getConversationsGlobal({ limit: 50, offset: 0, q: opts?.q });
      const items: Conversation[] = (data?.conversations ?? []).map((c) => ({
        id: c.id,
        analysis_type: c.analysis_type,
        title: c.title,
        created_at: c.created_at,
        updated_at: c.updated_at,
        preset_id: c.preset_id ?? null,
        starred: c.starred ?? false,
        // 全局会话列表额外字段：保留在运行时对象上，便于渲染/只读判定
        project_id: c.project_id,
        project_name: c.project_name,
        project_exists: c.project_exists,
        project_available: c.project_available,
      }));
      setConversations(items);
      // 不再在全局列表加载时自动改 selectedConversationId，避免抢夺用户当前会话
    } catch (e) {
      setConversations([]);
    }
  }, []);

  const loadSettings = useCallback(async (opts?: { snapshot_chunk_strategy?: boolean }) => {
    const data = await apiJson<SettingsData>("/api/v1/settings");
    const cs: ChunkStrategy = data.chunk_strategy === "structured" ? "structured" : "blank";
    if (opts?.snapshot_chunk_strategy) {
      chunkStrategyAtOpenRef.current = cs;
    }
    const mim: MdIndexMode = data.md_index_mode === "full" ? "full" : "incremental";
    const merged: SettingsData = { ...data, chunk_strategy: cs, md_index_mode: mim };
    setChunkLimit(merged.chunk_limit);
    setFocusDefs(merged.focus_points);
    setFocusPresets(merged.focus_presets || []);
    setSettingsDraft(merged);
    setFocusSelectedIndex(0);
    setPresetSelectedIndex(0);
    setReviewDomainError(merged.review_domain_error || null);
    setTextApiKeyDraft("");
    setTextApiKeyTouched(false);
    setVlApiKeyDraft("");
    setVlApiKeyTouched(false);
    if (!warnedNoPresetsRef.current && !(merged.focus_presets || []).length) {
      warnedNoPresetsRef.current = true;
      message.warning(
        "未加载到预设（focus_presets 为空）。请检查当前审查技能包的 review_domain.md 是否包含「组合使用建议」表格，或在设置中手工创建预设。",
      );
    }
  }, []);

  useEffect(() => {
    loadProjects().catch((e) => message.error(String((e as Error).message)));
    loadSettings().catch((e) => message.error(String((e as Error).message)));
    loadVaults().catch(() => {});
  }, [loadProjects, loadSettings, loadVaults]);

  /** rules 中的「目的：」文案变化时，重新显示为输入框占位提示 */
  useEffect(() => {
    const h = (settingsDraft.composer_hint ?? "").trim();
    if (prevRulesComposerHintRef.current !== h) {
      prevRulesComposerHintRef.current = h;
      setComposerHintDismissed(false);
    }
  }, [settingsDraft.composer_hint]);

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
    if (appMode !== "review") return;
    loadConversations({ q: chatSearchQuery }).catch((e) => message.error(String((e as Error).message)));
  }, [appMode, chatSearchQuery, loadConversations]);

  const fetchAllConversations = useCallback(async (opts: { limit: number; offset: number; q: string }): Promise<{ items: AllSessionItem[]; hasMore: boolean }> => {
    const { conversations } = await getConversationsGlobal({ limit: opts.limit + 1, offset: opts.offset, q: opts.q });
    const hasMore = conversations.length > opts.limit;
    return {
      items: conversations.slice(0, opts.limit).map(c => ({
        id: c.id,
        title: c.title || "(无标题)",
        updated_at: c.updated_at ?? "",
        starred: c.starred,
        project_id: c.project_id,
      })),
      hasMore,
    };
  }, []);

  /** 项目列表变化后，若当前选中 id 已不存在则清空（不自动改选其它项目） */
  useEffect(() => {
    if (selectedId != null && !projects.some((p) => p.id === selectedId)) {
      setSelectedId(null);
    }
  }, [projects, selectedId]);

  useEffect(() => {
    if (!settingsOpen && !isStandaloneSettings) return;
    // 每次打开设置时都从后端刷新，避免显示旧值/读错配置源时难以定位
    loadSettings({ snapshot_chunk_strategy: true }).catch((e) => message.error(String((e as Error).message)));
  }, [settingsOpen, isStandaloneSettings, loadSettings]);

  useEffect(() => {
    apiJson<{ native_folder_picker: boolean }>("/api/v1/fs/capabilities")
      .then((d) => setNativePickerAvailable(!!d.native_folder_picker))
      .catch(() => setNativePickerAvailable(false));
  }, []);

  useEffect(() => {
    if (!helpOpen && !isStandaloneHelp) return;
    setHelpLoading(true);
    apiJson<{ markdown: string; source: string }>("/api/v1/helpme")
      .then((d) => setHelpMarkdown(d.markdown || ""))
      .catch((e) => setHelpMarkdown(`# 帮助加载失败\n\n${String((e as Error).message || e)}`))
      .finally(() => setHelpLoading(false));
  }, [helpOpen, isStandaloneHelp]);

  // Standalone 页面：直接全屏渲染，不使用弹框（布局与独立设置页一致）
  if (isStandaloneHelp) {
    return (
      <div className="app-layout app-layout--standalone">
        <HelpPage loading={helpLoading} markdown={helpMarkdown} onClose={closeStandaloneView} />
      </div>
    );
  }

  const selected = useMemo(() => projects.find((p) => p.id === selectedId) || null, [projects, selectedId]);

  // 切换项目时，自动恢复该项目持久化的 vault 关联
  useEffect(() => {
    if (selected?.vault_id != null) {
      setSelectedVaultId(selected.vault_id);
    }
  }, [selected?.id, selected?.vault_id]);

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
      await loadConversations({ q: chatSearchQuery });
      setSelectedConversationId(data.id);
      return data.id;
    },
    [selectedId, loadConversations, chatSearchQuery],
  );

  const createFreshConversationForPreset = useCallback(async () => {
    if (selectedId == null || !selectedPresetId) return null;
    const preset = focusPresets.find((p) => p.id === selectedPresetId);
    if (!preset) return null;
    const projName = displayProjectSubject(selected);
    const title = `KA - ${projName} - ${preset.name} - ${formatLocalDateTime(new Date())}`;
    return createConversation("KA", title, selectedPresetId);
  }, [selectedId, selectedPresetId, focusPresets, selected, createConversation]);

  const findReusableEmptyConversationForPreset = useCallback(
    async (projectId: number, presetId: string): Promise<number | null> => {
      // D2：该预设无"审查历史"（count==0）时，优先复用空会话，避免无限新建
      try {
        const pair = await getConversationsByPair(projectId, presetId);
        const items = Array.isArray(pair.conversations) ? pair.conversations : [];
        const candidates = items
          .filter((c) => (c.preset_id ?? "").trim() === presetId)
          .sort((a, b) => {
            const ta = String(a.updated_at || "");
            const tb = String(b.updated_at || "");
            if (ta < tb) return 1;
            if (ta > tb) return -1;
            return Number(b.id) - Number(a.id);
          });
        for (const c of candidates) {
          const d = await getConversationDetail(projectId, c.id);
          if (!d.has_analysis_run) return c.id;
        }
      } catch {
        // ignore
      }
      return null;
    },
    [],
  );

  const prepareConversationForPipeline = useCallback(async (): Promise<number | null> => {
    if (selectedId == null || !selectedPresetId) return null;
    const projectId = selectedId;
    const presetId = selectedPresetId;

    // 配对查询：仅提示存在历史，不再强制选择/切换（弱化 count>0 逻辑）
    try {
      const pair = await getConversationsByPair(projectId, presetId);
      if (pair.count > 0) {
        const okProceed = await new Promise<boolean>((resolve) => {
          Modal.confirm({
            title: "发现该审查组合的历史会话",
            okText: "继续",
            cancelText: "取消",
            content: (
              <Space direction="vertical" style={{ width: "100%" }} size={10}>
                <Text type="secondary">
                  当前项目在该审查组合下已有历史会话。此提示仅用于提醒你可在会话历史中回看；本次不会自动切换会话。
                </Text>
                <Button type="link" onClick={() => { navPush({ appMode: "review", mainPanel: "analyze", reviewMainTab: "analyze", selectedId, selectedConversationId }); setAppMode("review"); setMainPanel("analyze"); }}>
                  打开项目审查
                </Button>
              </Space>
            ),
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
          });
        });
        if (!okProceed) return null;
      }
    } catch {
      // ignore: 失败时不阻断主流程（仍可走后续逻辑）
    }

    let convId = selectedConversationId;
    let detail: Awaited<ReturnType<typeof getConversationDetail>> | null = null;

    if (convId != null) {
      detail = await getConversationDetail(projectId, convId);
      const bound = detail.preset_id?.trim();
      if (bound && bound !== presetId) {
        // 当前会话属于其它审查组合：避免混用；后续会走 createFreshConversationForPreset
        convId = null;
        detail = null;
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

    // 无历史审查记录：无需弹窗提示；直接继续（convId 为空则后续按既有逻辑新建会话并执行全流程）

    if (convId == null) {
      const reusable = await findReusableEmptyConversationForPreset(projectId, presetId);
      if (reusable != null) return reusable;
      return createFreshConversationForPreset();
    }

    return convId;
  }, [
    selectedId,
    selectedConversationId,
    selectedPresetId,
    createFreshConversationForPreset,
    findReusableEmptyConversationForPreset,
  ]);

  const checkPresetChangeAgainstConversation = useCallback(
    async (nextPresetId: string, previousPresetId: string) => {
      if (selectedId == null || selectedConversationId == null || !nextPresetId) return;
      const d = await getConversationDetail(selectedId, selectedConversationId);
      const bound = d.preset_id?.trim();
      if (!bound || bound === nextPresetId) return;
      // 不在同一会话里混用预设：直接回退选择
      setSelectedPresetId(previousPresetId);
      const p = focusPresets.find((x) => x.id === previousPresetId);
      setFocusPoints(p?.focus_points ?? []);
      message.warning("当前会话属于其它审查组合。请在会话历史中切换会话，或新建会话后再审查。");
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
    // Native picker unavailable (e.g. Docker) — fall back to upload modal
    openUploadModal("init");
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

  const openUploadModal = (mode: "init" | "append") => {
    setUploadModalMode(mode);
    setUploadFiles([]);
    setUploadRelPaths([]);
    setUploadStep(mode === "append" ? 2 : 1);
    setUploadModalVaultId(selectedVaultId);
    if (mode === "init") setUploadProjectName("");
    setUploadModalOpen(true);
  };

  const onUploadFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = Array.from(e.target.files || []);
    if (!fileList.length) return;
    setUploadFiles(fileList);
    const paths = fileList.map((f) => (f as any).webkitRelativePath || f.name);
    setUploadRelPaths(paths);
    if (uploadModalMode === "init" && !uploadProjectName) {
      const topFolder = paths[0]?.split("/")[0];
      if (topFolder && topFolder !== paths[0]) setUploadProjectName(topFolder);
    }
  };

  const onDoUpload = async () => {
    if (!uploadFiles.length) { message.warning("请先选择文件或目录"); return; }
    if (uploadModalMode === "init" && !uploadProjectName.trim()) {
      message.warning("请填写项目名称");
      return;
    }
    setUploadLoading(true);
    try {
      const isInit = uploadModalMode === "init";
      const result = await initProjectFromUpload({
        files: uploadFiles,
        relPaths: uploadRelPaths,
        mode: uploadModalMode,
        projectName: isInit ? uploadProjectName.trim() : undefined,
        vaultId: isInit ? uploadModalVaultId : undefined,
        projectId: !isInit ? (selectedId ?? null) : undefined,
      });
      await loadProjects();
      setSelectedId(result.id);
      setUploadModalOpen(false);
      if (uploadInputRef.current) uploadInputRef.current.value = "";
      const errNote = result.errors.length ? `（${result.errors.length} 个文件跳过）` : "";
      if (isInit) {
        message.success(`已${result.created ? "创建" : "加载"}项目「${result.name}」，转换 ${result.files_written} 个文件${errNote}`);
      } else {
        message.success(`已向「${result.name}」追加 ${result.files_written} 个文件${errNote}`);
      }
    } catch (e) {
      message.error(String((e as Error).message));
    } finally {
      setUploadLoading(false);
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
      setReviewDomainError(data.review_domain_error || null);
      setTextApiKeyDraft("");
      setTextApiKeyTouched(false);
      setVlApiKeyDraft("");
      setVlApiKeyTouched(false);
      const savedCs: ChunkStrategy = data.chunk_strategy === "structured" ? "structured" : "blank";
      if (savedCs !== chunkStrategyAtOpenRef.current) {
        message.warning("分块策略已更新，请重新执行「索引与分块」（或全流程中的索引步骤），否则分析仍基于旧分块结果。");
      }
      if (!isStandaloneSettings) setSettingsOpen(false);
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
    if (!settingsOpen && !isStandaloneSettings) {
      setPresetCreating(false);
      return;
    }
    setSettingsTabKey("doc");
    setRulesInnerTabKey("focus_points");
    setPresetCreating(false);
  }, [settingsOpen, isStandaloneSettings]);

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
      const check = await apiJson<{ focus_points: FocusPoint[]; count: number }>("/api/v1/settings/review-domain/validate", {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      Modal.confirm({
        title: "确认导入审查域",
        content: `检测通过：共 ${check.count} 个关注点。确认后将写入当前活动审查技能包的 review_domain.md。`,
        okText: "确认加载",
        cancelText: "取消",
        onOk: async () => {
          const data = await apiJson<SettingsData>("/api/v1/settings/review-domain/import", {
            method: "POST",
            body: JSON.stringify({ text }),
          });
          setChunkLimit(data.chunk_limit);
          setFocusDefs(data.focus_points);
          setFocusPresets(data.focus_presets || []);
          setSettingsDraft(data);
          setFocusSelectedIndex(0);
          setPresetSelectedIndex(0);
          setReviewDomainError(data.review_domain_error || null);
          setSelectedPresetId("");
          setFocusPoints([]);
          message.success("审查域已导入并保存");
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

  const pushOutputEntry = useCallback((entry: Omit<OutputEntry, "id" | "at">) => {
    const md = String(entry.markdown || "");
    if (!md.trim()) return;
    const now = Date.now();
    const id =
      typeof crypto !== "undefined" && typeof (crypto as any).randomUUID === "function"
        ? (crypto as any).randomUUID()
        : `${now}-${Math.random().toString(16).slice(2)}`;
    setOutputEntries((prev) => [...prev, { ...entry, id, at: now, markdown: md }]);
  }, []);

  // 已移除首页「组合建议」入口，保留该函数会导致误导与无用代码

  const renderMilestoneDetail = useCallback(
    (m: Milestone, opts?: { thinkingOpen?: boolean }) => {
      const t = effectiveMilestoneBody(m, activeReportSplit);
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
      return <BusinessMilestoneMarkdown markdown={t} thinkingOpen={opts?.thinkingOpen} />;
    },
    [activeReportSplit],
  );

  const stopPipeline = () => {
    if (!pipelineRunning) return;
    terminatedRef.current = true;
    analyzeAbortRef.current?.abort();
    indexAbortRef.current?.abort();
    stopAnalyzeRef.current?.();
    analyzeAbortRef.current = null;
    indexAbortRef.current = null;
    stopAnalyzeRef.current = null;
    setPipelineRunning(false);
    ensureMilestone("sys:control", "流程控制", "system");
    appendMilestoneDetail("sys:control", "[info] 用户已终止流程。\n");
    setMilestoneStatus("sys:control", "done");
    message.info("流程已终止");
  };

  const runAgentMessage = async () => {
    if (selectedId == null) {
      message.warning("请先选择已初始化项目（如需注册目录与建立索引，请先进入项目初始化）");
      return;
    }
    const st = projectIngest[selectedId];
    if (!st?.initialized) {
      message.warning("当前项目尚未完成初始化（索引未就绪）。请先进入「项目初始化」完成转换与索引。");
      setMainPanel("ingest");
      return;
    }
    const text = draftText.trim();
    if (!text) {
      message.warning("请输入内容");
      return;
    }
    const convId =
      selectedConversationId ??
      (await createConversation(analysisTypeDraft, undefined, null));
    if (convId == null) {
      message.error("创建会话失败");
      return;
    }
    setSelectedConversationId(convId);
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
    setLastSubmittedUserMessage({ text, created_at: new Date().toISOString() });
    const analysisText =
      `目标：已收到你的请求（见上方用户输入）。\n\n` +
      `计划：我会先做 routing（选择关注点/产物/是否需要澄清问题），然后进入 executing，按步骤输出过程与结果。`;
    setProblemAnalysis(analysisText);
    setDraftText("");
    setPipelineTaskBrief("");
    userExpandedMilestonesRef.current = new Set();

    // 链式里程碑：问题分析作为第一步（可折叠，后续 routing/executing 在其后串联）
    ensureMilestone("stage:问题分析", "问题分析", "system");
    appendMilestoneDetail("stage:问题分析", analysisText);
    setMilestoneStatus("stage:问题分析", "done");

    const ac = new AbortController();
    analyzeAbortRef.current = ac;
    stopAnalyzeRef.current = () => {
      ac.abort();
      setPipelineRunning(false);
    };

    await runPipelineTryCatch(async () => {
      await postAgentConversationStream(
        selectedId,
        convId,
        { message: text },
        (ev) => {
          if (ev.type === "delta" && typeof (ev as any).text === "string") {
            appendAnalyzeDelta(String((ev as any).text));
          }
          if (ev.type === "agent_stage" && typeof (ev as any).stage === "string") {
            const name = `Agent:${String((ev as any).stage)}`;
            const state = String((ev as any).state || "");
            const key = `stage:${name}`;
            const prev = currentStageKeyRef.current;
            if (prev && prev !== key && !userExpandedMilestonesRef.current.has(prev)) {
              setMilestoneOpenOverrides((o) => ({ ...o, [prev]: false }));
            }
            ensureMilestone(key, name, "system");
            currentStageKeyRef.current = key;
            if (state === "done") setMilestoneStatus(key, "done");
          }
          if (ev.type === "agent_decision") {
            const d = (ev as any).decision;
            const pretty = (() => {
              try {
                return JSON.stringify(d, null, 2);
              } catch {
                return String(d);
              }
            })();
            const target = currentStageKeyRef.current || "stage:Agent:routing";
            appendMilestoneDetail(target, `\n\n[agent_decision]\n${toFencedCodeBlock("json", pretty)}\n`);
            // 动态更新「问题分析」：不重复回显用户输入正文，避免出现"两次回显"
            try {
              const intent = String((d as any)?.intent || "").trim();
              const focusIds = Array.isArray((d as any)?.focus_ids) ? (d as any).focus_ids.map(String) : [];
              const artifacts = Array.isArray((d as any)?.output_artifacts) ? (d as any).output_artifacts.map(String) : [];
              const qs = Array.isArray((d as any)?.clarify_questions) ? (d as any).clarify_questions : [];
              const planLines: string[] = [];
              if (intent) planLines.push(`- 意图：${intent}`);
              if (focusIds.length) planLines.push(`- 关注点：${focusIds.join("、")}`);
              if (artifacts.length) planLines.push(`- 产物：${artifacts.join("、")}`);
              if (Array.isArray(qs) && qs.length) planLines.push(`- 需要澄清：${qs.length} 条`);
              const nextText =
                `目标：已收到你的请求（见上方用户输入）。\n\n` +
                `计划：\n${planLines.length ? planLines.join("\n") : "- 先做 routing→executing，按阶段输出过程与结果"}`;
              setProblemAnalysis(nextText);
              setMilestones((prev) =>
                prev.map((m) => (m.id === "stage:问题分析" ? { ...m, detailText: nextText } : m)),
              );
            } catch {
              // ignore
            }
          }
          if (ev.type === "explain_skills" || ev.type === "explain_tools" || ev.type === "explain_hooks" || ev.type === "explain_memory") {
            const target = currentStageKeyRef.current || "stage:Agent:executing";
            const pretty = (() => {
              try {
                return JSON.stringify(ev, null, 2);
              } catch {
                return String(ev);
              }
            })();
            appendMilestoneDetail(
              target,
              `\n\n[${String((ev as any).type)}]\n${toFencedCodeBlock("json", pretty)}\n`,
            );
          }
          if (ev.type === "need_ingest" && typeof (ev as any).message === "string") {
            const m = String((ev as any).message);
            ensureMilestone("sys:need_ingest", "需要项目初始化", "system");
            appendMilestoneDetail("sys:need_ingest", m + "\n");
            setMilestoneStatus("sys:need_ingest", "done");
            setCorpusStaleReason("语料已过期，历史会话仅供参考。");
          }
          if (ev.type === "artifact_ready" && typeof (ev as any).download_path === "string") {
            const label = typeof (ev as any).label === "string" ? String((ev as any).label) : "下载";
            const p = String((ev as any).download_path);
            const key = `sys:artifact:${label}`;
            ensureMilestone(key, `产物：${label}`, "business");
            appendMilestoneDetail(key, `下载：${p}\n`);
            setMilestoneStatus(key, "done");
          }
          if (ev.type === "final") {
            const md = typeof (ev as any).markdown === "string" ? String((ev as any).markdown) : "";
            if (md.trim()) {
              setFinalMarkdown(md);
              pushOutputEntry({ kind: "analyze", convId, title: "审查结果", markdown: md });
            }
          }
          if (ev.type === "error") {
            throw new Error(String((ev as any).message || "agent error"));
          }
        },
        ac.signal,
      );
      message.success("完成");
    });
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
      const idxBody: Record<string, unknown> = {};
      if (selectedVaultId != null) idxBody.vault_id = selectedVaultId;
      if (indexResolveWikilinks) idxBody.resolve_wikilinks = true;
      const idx = await apiJson<{ indexed_documents: number }>(`/api/v1/projects/${selectedId}/index-md`, {
        method: "POST",
        body: JSON.stringify(idxBody),
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
      memory_query?: string;
    } = {
      chunk_limit: chunkLimit,
      focus_points,
    };
    if (inc) analyzeBody.incremental_user_notes = inc;
    const mq = memoryQueryDraft.trim();
    if (mq) analyzeBody.memory_query = mq;
    const pr = (preset?.review_role ?? "").trim();
    if (pr) analyzeBody.review_role = pr;
    const pg = (preset?.review_goals_principles ?? "").trim();
    if (pg) analyzeBody.review_goals_principles = pg;
    const po = (preset?.output_requirements ?? "").trim();
    if (po) analyzeBody.output_requirements = po;
    // Sprint 2+5: multi-turn flags
    (analyzeBody as Record<string, unknown>).deferred_doc = true;
    (analyzeBody as Record<string, unknown>).deep_mode = deepMode;
    if (draftText.trim()) (analyzeBody as Record<string, unknown>).user_message = draftText.trim();
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
          if (ev.type === "explain_skills" || ev.type === "explain_tools" || ev.type === "explain_hooks" || ev.type === "explain_memory") {
            const key = "stage:评审策略";
            ensureMilestone(key, "评审策略", "system");
            const pretty = (() => {
              try {
                return JSON.stringify(ev, null, 2);
              } catch {
                return String(ev);
              }
            })();
            appendMilestoneDetail(key, `\n\n[${String((ev as any).type)}]\n${pretty}\n`);
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
            if (state === "active") {
              const detail = typeof (ev as any).detail === "string" ? String((ev as any).detail) : "";
              const d = detail.trim();
              if (d && !/^model=/i.test(d)) appendMilestoneDetail(key, `${detail}\n`);
            } else if (state === "done") {
              setMilestoneStatus(key, "done");
            }
          }
          if (ev.type === "finding") {
            const f = (ev as any).finding;
            if (f && typeof f === "object" && f.id) {
              setSessionFindings((prev) => {
                const exists = prev.some((x) => x.id === f.id);
                return exists ? prev : [...prev, f as Finding];
              });
            }
          }
          if (ev.type === "critique" && typeof (ev as any).summary === "string") {
            appendMilestoneDetail("stage:思考分析", `\n\n【自我审查】\n${String((ev as any).summary)}\n`);
          }
          if (ev.type === "pass_done") {
            const fc = (ev as any).finding_count;
            appendMilestoneDetail("stage:呈现结果", `\n审查完成，发现 ${Number(fc) || 0} 个问题。\n`);
          }
          if (ev.type === "final") {
            const rawFindings = (ev as any).findings;
            if (Array.isArray(rawFindings) && rawFindings.length) {
              setSessionFindings((prev) => {
                const newOnes = (rawFindings as Finding[]).filter(
                  (f) => !prev.some((x) => x.id === f.id)
                );
                return newOnes.length ? [...prev, ...newOnes] : prev;
              });
            }
            const md = typeof (ev as any).markdown === "string" ? String((ev as any).markdown) : "";
            const rawMem = (ev as { memory_files_injected?: unknown }).memory_files_injected;
            if (Array.isArray(rawMem) && rawMem.length) {
              const parsed: Array<{ id: string; title?: string }> = [];
              for (const x of rawMem) {
                if (x && typeof x === "object" && "id" in x) {
                  const id = String((x as { id?: unknown }).id ?? "").trim();
                  if (id) parsed.push({ id, title: String((x as { title?: unknown }).title ?? "").trim() || undefined });
                }
              }
              if (parsed.length) {
                const lines = parsed.map((m) => {
                  const tit = m.title ? ` — ${m.title}` : "";
                  return `- ${m.id}${tit}`;
                });
                appendMilestoneDetail("stage:思考分析", `\n\n【加载的记忆】\n${lines.join("\n")}\n`);
              }
            }
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
    pushOutputEntry({
      kind: (opts?.incremental_user_notes ?? "").trim() ? "rereview" : "analyze",
      convId,
      title: (opts?.incremental_user_notes ?? "").trim() ? "重新审查结果" : "审查结果",
      markdown: md,
    });
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
            if (state === "active") {
              const detail = typeof (ev as any).detail === "string" ? String((ev as any).detail) : "";
              const d = detail.trim();
              if (d && !/^model=/i.test(d)) appendMilestoneDetail(key, `${detail}\n`);
            } else if (state === "done") {
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
    pushOutputEntry({
      kind: "followup",
      convId,
      title: `追问结果：${question.trim().slice(0, 40) || "（空）"}`,
      markdown: md,
    });
    setFinalMarkdown(md);
  };

  const runPipelineTryCatch = async (runBody: () => Promise<void>) => {
    try {
      await runBody();
    } catch (e) {
      if ((e as Error)?.name === "AbortError" || terminatedRef.current) return;
      const msg = String((e as Error).message);
      const stepFallback =
        pipelineStepRef.current === "index"
          ? "sys:index"
          : "";
      const target = currentStageKeyRef.current || stepFallback || lastMilestoneIdRef.current || "sys:control";
      const targetLabel =
        target === "sys:index"
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
      stopAnalyzeRef.current = null;
    }
  };

  const runFullPipeline = async () => {
    if (selectedId == null) {
      message.warning("请先选择已初始化项目（如需注册目录与建立索引，请先进入项目初始化）");
      return;
    }
    if (!selectedPresetId) {
      message.warning("请先选择预设");
      return;
    }
    const preset = focusPresets.find((p) => p.id === selectedPresetId);
    const presetFocusPoints = preset?.focus_points || [];
    if (!preset || presetFocusPoints.length === 0) {
      message.warning("预设无可用关注点，请检查审查技能包内预设配置");
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

    // 首次审查：分析视图不再负责转换/索引。必须确保语料已初始化（chunks 就绪）。
    const st = projectIngest[selectedId];
    if (!st?.initialized) {
      message.warning("当前项目尚未完成初始化（索引未就绪）。请先进入「项目初始化」完成转换与索引。");
      setMainPanel("ingest");
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
    const taskBrief = `本次针对项目「${projName}」，将围绕${fpSample}${fpRest}共 ${presetFocusPoints.length} 项关注点开展关联审查。语料已完成初始化（转换与索引），本次将直接进入模型分析（并按需生成片段索引与审查结论）。若您刚在设置中修改过分块策略，请务必回到「项目初始化」重新执行索引，否则结论可能仍基于旧分块边界。`;
    setPipelineTaskBrief(taskBrief);
    await runPipelineTryCatch(async () => {
      pipelineStepRef.current = "analyze";
      await runAnalyzePhase(presetFocusPoints, { convId });
      if (terminatedRef.current) return;
      message.success("全流程完成");
    });
  };

  const resumePipelineAfterFailure = async (mode: "index_chain" | "analyze_only" | "full") => {
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
      message.warning("预设无可用关注点，请检查审查技能包内预设配置");
      return;
    }
    setFocusPoints(presetFocusPoints);
    setPipelineFailModal(null);
    setComposerHintDismissed(true);
    setPipelineRunning(true);
    terminatedRef.current = false;
    analyzeAbortRef.current?.abort();
    indexAbortRef.current?.abort();
    stopAnalyzeRef.current = null;
    analyzeAbortRef.current = null;
    indexAbortRef.current = null;
    const projName = displayProjectSubject(selected);
    const fpSample = presetFocusPoints.slice(0, 3).join("、");
    const fpRest = presetFocusPoints.length > 3 ? "等" : "";
    const taskBrief = `本次针对项目「${projName}」，将围绕${fpSample}${fpRest}共 ${presetFocusPoints.length} 项关注点开展关联审查。流程将顺序执行：① 索引与分块（按设置中的分块策略建立可检索片段）；② 模型分析（结合关注点生成结构化审查结论）。请关注下方各步骤日志；若您刚在设置中修改过分块策略，请务必重新执行索引后再解读分析结果，以免结论仍基于旧分块边界。`;
    setPipelineTaskBrief(taskBrief);

    if (mode === "full") {
      deltaAccRef.current = "";
      currentStageKeyRef.current = "";
      setMilestones([]);
      setMilestoneOpenOverrides({});
      setFinalMarkdown("");
      setFragmentIndexMd("");
      setResultFeedback(null);
    } else if (mode === "index_chain") {
      setMilestones((prev) => {
        return [
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
          .filter((m) => m.id === "sys:index")
          .map((m) => ({ ...m, status: "done" as MilestoneStatus })),
      );
    }

    await runPipelineTryCatch(async () => {
      if (mode === "full" || mode === "index_chain") {
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
    if (pipelineRunning) return true;
    if (finalMarkdown.trim()) return true;
    if (milestones.length) return true;
    // 打开会话后：即便本轮尚未产生新输出，也要展示历史（replay）
    if (selectedConversationId != null && replay.entries.length) return true;
    if (selectedConversationId != null && conversationMessages.length) return true;
    return false;
  }, [
    pipelineRunning,
    finalMarkdown,
    milestones.length,
    selectedConversationId,
    replay.entries.length,
    conversationMessages.length,
  ]);

  const startNewConversationPage = useCallback(() => {
    // 不弹窗、不强制选预设：进入"空白会话页"，由用户在该页选择预设与加载项目
    setNewConversationOpen(false);
    setMainPanel("analyze");
    setSelectedConversationId(null);
    setSelectedPresetId("");
    setFocusPoints([]);
    setFinalMarkdown("");
    setFragmentIndexMd("");
    setMilestones([]);
    setOutputEntries([]);
    setDraftText("");
    setPipelineTaskBrief("");
    // 让用户在新会话页自行加载项目；避免误将旧项目上下文带入新会话
    setSelectedId(null);
    setCorpusStaleReason("");
  }, []);

  const composerTextPlaceholder = useMemo(() => {
    if (projectViewOnlyReason.trim()) return projectViewOnlyReason.trim();
    if (corpusStaleReason.trim()) return corpusStaleReason.trim();
    if (!showMainOutput && !selectedConversationId) return "你可以粘贴项目文件内容，上传项目文档，或者选择项目空间，然后提出你的问题";
    if (composerHintDismissed) return DEFAULT_COMPOSER_PLACEHOLDER;
    const h = (settingsDraft.composer_hint ?? "").trim();
    return h || DEFAULT_COMPOSER_PLACEHOLDER;
  }, [projectViewOnlyReason, corpusStaleReason, showMainOutput, selectedConversationId, composerHintDismissed, settingsDraft.composer_hint]);

  const canStartAgentMessage = useMemo(() => {
    if (pipelineRunning) return false;
    if (selectedId == null) return false;
    if (!!projectViewOnlyReason.trim()) return false;
    if (!!corpusStaleReason.trim()) return false;
    if (!draftText.trim()) return false;
    return true;
  }, [pipelineRunning, selectedId, projectViewOnlyReason, corpusStaleReason, draftText]);

  const initializedProjects = useMemo(() => {
    const items = projects.filter((p) => !!projectIngest[p.id]?.initialized);
    // 多项目时：先按 chunk_count 降序，再按名称
    return [...items].sort((a, b) => {
      const ca = Number(projectIngest[a.id]?.chunk_count) || 0;
      const cb = Number(projectIngest[b.id]?.chunk_count) || 0;
      if (cb !== ca) return cb - ca;
      return String(a.name || "").localeCompare(String(b.name || ""), "zh-Hans-CN");
    });
  }, [projects, projectIngest]);

  // 所有项目（已初始化 + 未初始化），供「+」下拉展示
  const allProjectsSorted = useMemo(() => {
    return [...projects].sort((a, b) => {
      const ai = projectIngest[a.id]?.initialized ? 1 : 0;
      const bi = projectIngest[b.id]?.initialized ? 1 : 0;
      if (bi !== ai) return bi - ai; // 已初始化的排前面
      return String(a.name || "").localeCompare(String(b.name || ""), "zh-Hans-CN");
    });
  }, [projects, projectIngest]);

  const settingsTabsNode = (
        <Tabs
          activeKey={settingsTabKey}
          onChange={(k) => setSettingsTabKey(k as "doc" | "models")}
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
            // 审查域已独立为主页面入口（左侧栏）；设置弹窗仅保留文档与模型配置
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
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid #f0f0f0" }}>
              <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
                语义召回（Embedding）— 配置后可提升记忆与文档片段的召回准确率
              </Typography.Text>
              <Space wrap>
                <Input
                  style={{ width: 360 }}
                  addonBefore="Embed Base URL"
                  placeholder="OpenAI 兼容 Embeddings 接口 URL"
                  value={settingsDraft.llm_settings?.embed_base_url ?? ""}
                  onChange={(e) =>
                    setSettingsDraft((s) => ({ ...s, llm_settings: { ...s.llm_settings, embed_base_url: e.target.value } }))
                  }
                />
                <Input
                  style={{ width: 280 }}
                  addonBefore="Embed 模型"
                  placeholder="例如 text-embedding-ada-002"
                  value={settingsDraft.llm_settings?.embed_model ?? ""}
                  onChange={(e) =>
                    setSettingsDraft((s) => ({ ...s, llm_settings: { ...s.llm_settings, embed_model: e.target.value } }))
                  }
                />
              </Space>
            </div>
                </div>
              ),
            },
          ]}
        />
  );

  const reviewDomainPageNode = (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "10px 10px 18px" }}>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12 }}>
        <div>
          <Title level={4} style={{ margin: "6px 0 6px" }}>
            审查域设定
          </Title>
          <Text type="secondary">
            管理当前活动审查技能包的关注点与组合。
          </Text>
        </div>
        <Space wrap>
          <Button type="primary" onClick={() => void saveSettings()}>
            保存
          </Button>
        </Space>
      </div>

      <Divider style={{ margin: "14px 0" }} />

      <Space direction="vertical" style={{ width: "100%" }} size={12}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
          <div>
            <Text type="secondary" style={{ display: "block", marginBottom: 6 }}>
              当前审查技能包
            </Text>
            <Select
              style={{ minWidth: 320 }}
              value={settingsDraft.active_skill_package_id || "package-general"}
              options={(settingsDraft.skill_packages || []).map((p) => ({
                value: p.id,
                label: p.version ? `${p.name} (${p.version})` : p.name,
              }))}
              onChange={(v) => setSettingsDraft((s) => ({ ...s, active_skill_package_id: String(v || "") }))}
              disabled={!(settingsDraft.skill_packages || []).length}
            />
          </div>
          <div style={{ flex: 1 }} />
          <div className="settings-tab-rules-file">
            <Button size="small" onClick={onPickRulesFile}>
              导入审查域
            </Button>
          </div>
        </div>

        {settingsDraft.skill_packages_root ? (
          <Text type="secondary" style={{ fontSize: 11 }}>
            包根目录：
            <Text code style={{ fontSize: 11, wordBreak: "break-all" }}>
              {settingsDraft.skill_packages_root}
            </Text>
          </Text>
        ) : null}
        {settingsDraft.review_domain_path ? (
          <Text type="secondary" style={{ fontSize: 11 }}>
            当前审查域文件：
            <Text code style={{ fontSize: 11, wordBreak: "break-all" }}>
              {settingsDraft.review_domain_path}
            </Text>
          </Text>
        ) : null}

        {(settingsDraft.focus_presets || []).length === 0 ? (
          <Alert
            type={(settingsDraft.focus_combo_tips || []).length > 0 ? "warning" : reviewDomainError ? "error" : "info"}
            showIcon
            message={
              (settingsDraft.focus_combo_tips || []).length > 0
                ? "已解析「组合使用建议」表格，但未能生成预设"
                : reviewDomainError
                  ? "审查域解析异常（关注点也可能不完整）"
                  : "未识别到「组合使用建议」表格"
            }
            description={
              (settingsDraft.focus_combo_tips || []).length > 0
                ? "通常是因为表格中的 `focus:id` 与关注点 id 不一致（含全角符号差异）。请与 `### focus:…` 中 id 完全一致。"
                : "请在当前活动包的 review_domain.md 内包含「组合使用建议」五列表。"
            }
          />
        ) : null}

        <input
          ref={rulesFileInputRef}
          type="file"
          accept=".md,text/markdown"
          style={{ display: "none" }}
          onChange={onRulesFileChosen}
        />

        <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, padding: 12, background: "#fff" }}>
          <Title level={5} style={{ margin: "0 0 10px" }}>
            关注点
          </Title>
          <div style={{ display: "flex", gap: 12, alignItems: "stretch" }}>
            <div style={{ width: 320, display: "flex", flexDirection: "column", gap: 8 }}>
              <div
                style={{
                  border: "1px solid #d9dfd7",
                  borderRadius: 10,
                  padding: 10,
                  minHeight: 320,
                  maxHeight: 420,
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
                  {settingsDraft.focus_points.length === 0 ? <Text type="secondary">暂无关注点</Text> : null}
                </Space>
              </div>
              <Text type="secondary" style={{ fontSize: 11 }}>
                提示：关注点的 id/name/prompt 将写回当前活动包的 <Text code>review_domain.md</Text>。
              </Text>
            </div>

            <div style={{ flex: 1, border: "1px solid #d9dfd7", padding: 12, borderRadius: 10, background: "#f7f9f6" }}>
              {settingsDraft.focus_points.length ? (
                <Space direction="vertical" style={{ width: "100%" }} size={8}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <div style={{ flex: 1 }}>
                      <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                        id
                      </Text>
                      <Input
                        value={settingsDraft.focus_points[focusSelectedIndex]?.id}
                        onChange={(e) => {
                          const v = e.target.value;
                          setSettingsDraft((s) => {
                            const arr = [...(s.focus_points || [])];
                            const i = Math.min(Math.max(0, focusSelectedIndex), Math.max(0, arr.length - 1));
                            if (!arr[i]) return s;
                            arr[i] = { ...arr[i], id: v };
                            return { ...s, focus_points: arr };
                          });
                        }}
                      />
                    </div>
                    <div style={{ flex: 2 }}>
                      <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                        名称
                      </Text>
                      <Input
                        value={settingsDraft.focus_points[focusSelectedIndex]?.name}
                        onChange={(e) => {
                          const v = e.target.value;
                          setSettingsDraft((s) => {
                            const arr = [...(s.focus_points || [])];
                            const i = Math.min(Math.max(0, focusSelectedIndex), Math.max(0, arr.length - 1));
                            if (!arr[i]) return s;
                            arr[i] = { ...arr[i], name: v };
                            return { ...s, focus_points: arr };
                          });
                        }}
                      />
                    </div>
                  </div>
                  <div>
                    <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                      Prompt
                    </Text>
                    <Input.TextArea
                      rows={16}
                      placeholder="该关注点对应的提示词（prompt）"
                      value={settingsDraft.focus_points[focusSelectedIndex]?.prompt}
                      onChange={(e) => updateSelectedFocusPrompt(e.target.value)}
                      style={{ minHeight: 300, resize: "vertical" }}
                    />
                  </div>
                </Space>
              ) : (
                <Text type="secondary">审查域未提供可用关注点</Text>
              )}
            </div>
          </div>
        </div>

        <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, padding: 12, background: "#fff" }}>
          <Title level={5} style={{ margin: "0 0 10px" }}>
            组合（预设）
          </Title>
          {(() => {
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
              <div>
                <div style={{ display: "flex", gap: 12, alignItems: "stretch" }}>
                  <div style={{ width: 320, display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>
                    <div
                      style={{
                        border: "1px solid #d9dfd7",
                        borderRadius: 10,
                        padding: 10,
                        maxHeight: 360,
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
                              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {p.name || p.id}
                              </span>
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
                        {presetsArr.length === 0 ? <Text type="secondary">暂无预设</Text> : null}
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
                        <Tooltip title="新增预设">
                          <Button type="default" size="small" icon={<PlusOutlined />} aria-label="新增预设" onClick={startCreatePreset} />
                        </Tooltip>
                      ) : (
                        <Space size={0}>
                          <Tooltip title="取消新增">
                            <Button size="small" icon={<MinusOutlined />} aria-label="取消新增" onClick={cancelCreatePreset} />
                          </Tooltip>
                          <Tooltip title="确认新增（需名称）">
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
                      padding: 12,
                      borderRadius: 10,
                      minHeight: 360,
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
                            style={{ resize: "vertical" }}
                          />
                        </div>
                        <div>
                          <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                            审查目标与原则
                          </Text>
                          <Input.TextArea
                            rows={6}
                            placeholder="目标、原则、分级与重点识别要求等"
                            value={goalsVal}
                            onChange={(e) => {
                              const v = e.target.value;
                              if (presetCreating) setPresetCreateDraft((d) => ({ ...d, review_goals_principles: v }));
                              else if (n > 0) updatePresetAt(idxSafe, { review_goals_principles: v });
                            }}
                            style={{ resize: "vertical" }}
                          />
                        </div>
                        <div>
                          <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                            输出要求
                          </Text>
                          <Input.TextArea
                            rows={6}
                            placeholder="输出章节结构、约束与禁止项"
                            value={outVal}
                            onChange={(e) => {
                              const v = e.target.value;
                              if (presetCreating) setPresetCreateDraft((d) => ({ ...d, output_requirements: v }));
                              else if (n > 0) updatePresetAt(idxSafe, { output_requirements: v });
                            }}
                            style={{ resize: "vertical" }}
                          />
                        </div>
                      </Space>
                    ) : (
                      <Text type="secondary">点击名称右侧 + 新建预设，填写后保存。</Text>
                    )}
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      </Space>
    </div>
  );

  if (isStandaloneSettings) {
    return (
      <div className="app-layout app-layout--standalone">
        <SystemSettingPage
          content={settingsTabsNode}
          onSave={() => void saveSettings()}
          onClose={closeStandaloneView}
        />
      </div>
    );
  }

  const toggleSidebar = () => {
    setSidebarCollapsed((v) => {
      localStorage.setItem("aika_sidebar_collapsed", v ? "0" : "1");
      return !v;
    });
  };

  const CONV_SIDEBAR_LIMIT = 25;
  const starredConvs = conversations.filter(c => c.starred);
  const recentConvs = conversations.filter(c => !c.starred);
  const displayStarredConvs = starredConvs.slice(0, CONV_SIDEBAR_LIMIT);
  const displayRecentConvs = recentConvs.slice(0, Math.max(0, CONV_SIDEBAR_LIMIT - displayStarredConvs.length));

  return (
    <div className={`app-layout${isStandalone ? " app-layout--standalone" : ""}`}>

      {/* ── Sidebar ── */}
      {!isStandalone && (
        <div className={`app-sidebar${sidebarCollapsed ? " app-sidebar--collapsed" : ""}`}>
          {/* Header */}
          <div className="app-sidebar__header">
            <span className="app-sidebar__logo">AI-KA</span>
            <Button type="text" size="small" className="app-sidebar__toggle"
              icon={sidebarCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={toggleSidebar}
              title={sidebarCollapsed ? "展开侧边栏" : "收缩侧边栏"}
            />
          </div>

          <div className="app-sidebar__divider" />

          <div className="app-sidebar__body">
            {/* ─ 项目审查 ─ */}
            <div className="app-sidebar__section">
              <Tooltip title={sidebarCollapsed ? "项目审查" : undefined} placement="right">
                <button
                  className={`app-sidebar__section-header${appMode === "review" && mainPanel === "analyze" && reviewMainTab === "analyze" ? " app-sidebar__section-header--active" : ""}`}
                  onClick={() => { navPush({ appMode: "review", mainPanel: "analyze", reviewMainTab: "analyze", selectedId, selectedConversationId }); setAppMode("review"); setMainPanel("analyze"); setReviewMainTab("analyze"); }}
                >
                  <AuditOutlined />
                  <span className="app-sidebar__label">项目审查</span>
                </button>
              </Tooltip>
            </div>

            {/* ─ 知识归纳 ─ */}
            <Tooltip title={sidebarCollapsed ? "知识归纳" : undefined} placement="right">
              <button
                className={`app-sidebar__section-header${appMode === "extraction" ? " app-sidebar__section-header--active" : ""}`}
                onClick={() => { navPush({ appMode: "extraction", mainPanel: "analyze", reviewMainTab: "analyze", selectedId: null, selectedConversationId: null }); setAppMode("extraction"); setReviewMainTab("analyze"); }}
              >
                <BulbOutlined />
                <span className="app-sidebar__label">知识归纳</span>
              </button>
            </Tooltip>

            {/* ─ 知识线索 ─ */}
            <Tooltip title={sidebarCollapsed ? "知识线索" : undefined} placement="right">
              <button
                className={`app-sidebar__section-header${reviewMainTab === "review_queue" ? " app-sidebar__section-header--active" : ""}`}
                onClick={() => { setAppMode("review"); setMainPanel("analyze"); setReviewMainTab("review_queue"); }}
              >
                <AimOutlined />
                <span className="app-sidebar__label">知识线索</span>
              </button>
            </Tooltip>

            {/* ─ 待批准规则 ─ */}
            <Tooltip title={sidebarCollapsed ? "待批准规则" : undefined} placement="right">
              <button
                className={`app-sidebar__section-header${appMode === "review" && mainPanel === "analyze" && reviewMainTab === "result_review" ? " app-sidebar__section-header--active" : ""}`}
                onClick={() => { navPush({ appMode: "review", mainPanel: "analyze", reviewMainTab: "result_review", selectedId, selectedConversationId: null }); setAppMode("review"); setMainPanel("analyze"); setReviewMainTab("result_review"); }}
              >
                <PushpinOutlined />
                <span className="app-sidebar__label">待批准规则</span>
              </button>
            </Tooltip>

            <div className="app-sidebar__divider" />

            {/* ─ 工具入口 ─ */}
            <Tooltip title={sidebarCollapsed ? "项目初始化" : undefined} placement="right">
              <button className={`app-sidebar__section-header${appMode === "review" && mainPanel === "ingest" ? " app-sidebar__section-header--active" : ""}`}
                onClick={() => { navPush({ appMode: "review", mainPanel: "ingest", reviewMainTab: "analyze", selectedId, selectedConversationId: null }); setAppMode("review"); setMainPanel("ingest"); setReviewMainTab("analyze"); }}
              >
                <FolderOpenOutlined />
                <span className="app-sidebar__label">项目初始化</span>
              </button>
            </Tooltip>
            <Tooltip title={sidebarCollapsed ? "审查域设定" : undefined} placement="right">
              <button className={`app-sidebar__section-header${appMode === "review" && mainPanel === "review_domain" ? " app-sidebar__section-header--active" : ""}`}
                onClick={() => { navPush({ appMode: "review", mainPanel: "review_domain", reviewMainTab: "analyze", selectedId: null, selectedConversationId: null }); setAppMode("review"); setMainPanel("review_domain"); setReviewMainTab("analyze"); void loadSettings({ snapshot_chunk_strategy: true }); }}
              >
                <FileSearchOutlined />
                <span className="app-sidebar__label">审查域设定</span>
              </button>
            </Tooltip>
          </div>

          {/* Footer — single user button with popup menu */}
          <div className="app-sidebar__footer">
            <Dropdown
              trigger={["click"]}
              placement="topLeft"
              dropdownRender={() => (
                <div className="user-menu">
                  {currentUser && (
                    <div className="user-menu__header">
                      <div className="user-menu__avatar">{(currentUser.display_name ?? "?")[0]?.toUpperCase()}</div>
                      <div>
                        <div className="user-menu__name">{currentUser.display_name}</div>
                      </div>
                    </div>
                  )}
                  <div className="user-menu__section">
                    <button className="user-menu__item" onClick={() => openStandaloneWindow("settings")}>
                      <SettingOutlined />
                      <span>设置</span>
                    </button>
                    <button className="user-menu__item" onClick={() => openStandaloneWindow("help")}>
                      <QuestionCircleOutlined />
                      <span>帮助与支持</span>
                    </button>
                  </div>
                  <div className="user-menu__divider" />
                  <div className="user-menu__section">
                    {currentUser ? (
                      <button className="user-menu__item user-menu__item--danger" onClick={handleLogout}>
                        <LogoutOutlined />
                        <span>退出登录</span>
                      </button>
                    ) : (
                      <button className="user-menu__item" onClick={() => setLoginOpen(true)}>
                        <UserOutlined />
                        <span>登录</span>
                      </button>
                    )}
                  </div>
                </div>
              )}
            >
              <div className="app-sidebar__user-btn">
                <UserOutlined />
                <span className="app-sidebar__label">{currentUser?.display_name ?? "未登录"}</span>
              </div>
            </Dropdown>
          </div>
        </div>
      )}

      {/* ── Main area ── */}
      <div className="app-main">
        {appMode === "extraction" ? (
          <div className="extraction-overlay">
            <ExtractionPage />
          </div>
        ) : (
        <>
          {/* Session history column for review mode */}
          {appMode === "review" && mainPanel === "analyze" && reviewMainTab === "analyze" && (
            <div className="session-col">
              <div className="session-col__header">
                <Text strong style={{ fontSize: 13 }}>项目审查</Text>
                <Button size="small" icon={<PlusOutlined />} onClick={startNewConversationPage} title="新会话" />
              </div>
              <div className="session-col__list">
                {conversations.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 12, padding: "8px 4px", display: "block" }}>暂无历史会话</Text>
                ) : (() => {
                  const renderConvItem = (c: Conversation) => {
                    const { headline, subline } = conversationListDisplay(c);
                    const active = c.id === selectedConversationId;
                    return (
                      <div
                        key={c.id}
                        className={`session-item${active ? " session-item--active" : ""}${c.starred ? " session-item--starred" : ""}`}
                        onClick={() => {
                          const pid = c.project_id;
                          navPush({ appMode: "review", mainPanel: "analyze", reviewMainTab: "analyze", selectedId: typeof pid === "number" ? pid : null, selectedConversationId: c.id });
                          if (typeof pid === "number") setSelectedId(pid);
                          setProjectViewOnlyReason(c.project_available === false ? "项目不可用或已删除：仅可查看历史会话，无法继续审查/追问。" : "");
                          setMainPanel("analyze");
                          setSelectedConversationId(c.id);
                          setReviewMainTab("analyze");
                        }}
                      >
                        {c.starred && <StarFilled style={{ fontSize: 10, color: "#f5a623", flexShrink: 0, marginTop: 3 }} />}
                        <div className="session-item__body">
                          <Tooltip title={headline} placement="right" mouseEnterDelay={0.5}>
                            <div className="session-item__title">{headline}</div>
                          </Tooltip>
                          {subline && <div className="session-item__time">{subline}</div>}
                          {c.project_name && <div className="session-item__time">项目：{String(c.project_name)}</div>}
                          {c.project_available === false && <div className="session-item__time">（仅可回看）</div>}
                        </div>
                        <Dropdown
                          trigger={["click"]}
                          placement="bottomRight"
                          menu={{
                            items: [
                              {
                                key: "star",
                                label: c.starred ? "取消置顶" : "置顶",
                                icon: c.starred ? <StarFilled style={{ color: "#f5a623" }} /> : <StarOutlined />,
                                onClick: ({ domEvent }) => {
                                  domEvent.stopPropagation();
                                  void patchConversation(c.id, { starred: !c.starred })
                                    .then(() => loadConversations({ q: chatSearchQuery }));
                                },
                              },
                              {
                                key: "rename",
                                label: "重命名",
                                icon: <EditOutlined />,
                                onClick: ({ domEvent }) => {
                                  domEvent.stopPropagation();
                                  setRenameConvId(c.id);
                                  setRenameConvValue(c.title);
                                },
                              },
                              { type: "divider" as const },
                              {
                                key: "delete",
                                label: "删除",
                                icon: <DeleteOutlined />,
                                danger: true,
                                onClick: ({ domEvent }) => {
                                  domEvent.stopPropagation();
                                  const pid = c.project_id;
                                  if (typeof pid !== "number") return;
                                  Modal.confirm({
                                    title: "确认删除会话",
                                    content: `将删除会话「${headline}」。此操作不可撤销。`,
                                    okText: "删除", okButtonProps: { danger: true }, cancelText: "取消",
                                    onOk: async () => {
                                      await deleteConversation(pid, c.id);
                                      setSelectedConversationId((prev) => (prev === c.id ? null : prev));
                                      await loadConversations({ q: chatSearchQuery });
                                    },
                                  });
                                },
                              },
                            ],
                          }}
                        >
                          <Button type="text" size="small" className="session-item__menu"
                            icon={<EllipsisOutlined />} onClick={(e) => e.stopPropagation()} />
                        </Dropdown>
                      </div>
                    );
                  };
                  return (
                    <>
                      {displayStarredConvs.length > 0 && (
                        <>
                          <div className="session-group-label">置顶</div>
                          {displayStarredConvs.map(renderConvItem)}
                        </>
                      )}
                      {displayRecentConvs.length > 0 && (
                        <>
                          <div className="session-group-label">近期会话</div>
                          {displayRecentConvs.map(renderConvItem)}
                        </>
                      )}
                    </>
                  );
                })()}
                <div className="session-col__all-btn" onClick={() => { navPush({ appMode: "review", mainPanel: "all_conversations", reviewMainTab: "analyze", selectedId: null, selectedConversationId: null }); setMainPanel("all_conversations"); }}>
                  <UnorderedListOutlined style={{ fontSize: 12 }} />
                  <span>所有会话</span>
                </div>
              </div>
              {/* 知识线索快捷入口 */}
              <div style={{ borderTop: "1px solid #f0f0f0", padding: "4px 0 2px", flexShrink: 0 }}>
                <button
                  className="app-sidebar__section-header"
                  style={{ width: "100%", fontSize: 12 }}
                  onClick={() => setReviewMainTab("review_queue")}
                >
                  <AimOutlined />
                  <span className="app-sidebar__label">知识线索</span>
                </button>
              </div>
            </div>
          )}

        <div className="app-shell">
        <div className="main-surface">
          {reviewDomainError ? (
            <Alert
              type="error"
              showIcon
              message="审查域无法加载"
              description={
                <>
                  <div>{reviewDomainError}</div>
                  <div style={{ marginTop: 8 }}>
                    可将仓库根目录的 default_skills.md 复制到当前活动审查技能包的 review_domain.md，或调用 POST
                    /api/v1/settings/review-domain/restore-default-skills-template 从模板写入当前活动包后刷新。
                  </div>
                </>
              }
              style={{ marginBottom: 10 }}
            />
          ) : null}

          {appMode === "review" && mainPanel === "ingest" ? (
            <div style={{ maxWidth: 980, margin: "0 auto", padding: "10px 10px 18px" }}>
              <div className="page-header">
                <span className="page-header__title">项目初始化</span>
              </div>
              <Text type="secondary">
                上传项目文档（支持 .docx / .pdf / .xlsx / .pptx / .html 自动转为 Markdown），
                写入 Obsidian Vault 后建立索引，再切到「分析」视图进行审查。
              </Text>

              <Divider style={{ margin: "14px 0" }} />

              {/* ── 建议 4：无 Vault 时提前警告 ── */}
              {vaults.length === 0 && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 14 }}
                  message="尚未配置 Obsidian Vault"
                  description="配置 Vault 后，项目文档将写入 Vault/Projects/ 目录，便于 Obsidian 管理和持久化。若跳过，文件将写入后端临时目录，重新部署后丢失。"
                  action={
                    <Button
                      size="small"
                      type="primary"
                      onClick={() => { setVaultPickerOpen(true); setDiscoveredVaults([]); }}
                    >
                      配置 Vault →
                    </Button>
                  }
                />
              )}

              <Space direction="vertical" size={12} style={{ width: "100%" }}>
                {/* ── 项目选择行 ── */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <Select
                    style={{ minWidth: 340 }}
                    showSearch
                    placeholder="选择已注册项目"
                    value={selectedId ?? undefined}
                    options={projects.map((p) => ({ value: p.id, label: p.name }))}
                    filterOption={(input, opt) =>
                      String(opt?.label || "").toLowerCase().includes(String(input || "").toLowerCase())
                    }
                    onChange={(v) => {
                      const pid = Number(v);
                      if (!Number.isFinite(pid)) return;
                      setSelectedId(pid);
                      setProjectViewOnlyReason("");
                      setCorpusStaleReason("");
                    }}
                  />
                  {/* ── 主操作按钮 ── */}
                  <Button
                    type="primary"
                    icon={<span style={{ marginRight: 4 }}>📤</span>}
                    onClick={() => openUploadModal("init")}
                  >
                    上传文件初始化
                  </Button>
                  <Button
                    type="default"
                    icon={<span style={{ marginRight: 4 }}>📒</span>}
                    onClick={() => { setVaultPickerOpen(true); setDiscoveredVaults([]); }}
                  >
                    Obsidian Vault
                  </Button>
                  {/* 选择目录注册：本机直接运行时有用，降为次要入口 */}
                  <Button
                    type="text"
                    size="small"
                    style={{ color: "#8c8c8c" }}
                    loading={pickLoading}
                    onClick={() => void openProjectPicker()}
                  >
                    选择目录注册
                  </Button>
                </div>

                {/* ── 选中项目的详情行 ── */}
                {selected && (
                  <div style={{
                    background: "#fafafa", border: "1px solid #f0f0f0",
                    borderRadius: 6, padding: "10px 14px",
                  }}>
                    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <Text strong>{selected.name}</Text>
                        <div style={{ fontSize: 12, marginTop: 2 }}>
                          <Text type="secondary" code style={{ wordBreak: "break-all" }}>
                            {selected.root_path}
                          </Text>
                        </div>
                      </div>
                      {/* ── 建议 3：追加文件移到此处 ── */}
                      <Space size={6}>
                        <Button
                          size="small"
                          icon={<span style={{ marginRight: 2 }}>➕</span>}
                          onClick={() => openUploadModal("append")}
                        >
                          追加文件
                        </Button>
                        {projectIngest[selectedId!]?.initialized && !projectIngest[selectedId!]?.has_review_records ? (
                          <Button
                            danger size="small"
                            onClick={() => {
                              const pid = selectedId!;
                              const name = selected.name || `项目 #${pid}`;
                              Modal.confirm({
                                title: "确认删除项目",
                                content: `将删除项目「${name}」及其全部数据（索引/分块/会话/输出）。此操作不可撤销。`,
                                okText: "删除",
                                okButtonProps: { danger: true },
                                cancelText: "取消",
                                onOk: async () => {
                                  await deleteProject(pid);
                                  message.success("项目已删除");
                                  setSelectedId(null);
                                  setSelectedConversationId(null);
                                  setProjectViewOnlyReason("");
                                  setCorpusStaleReason("");
                                  await loadProjects();
                                  await loadConversations({ q: chatSearchQuery });
                                },
                              });
                            }}
                          >
                            删除
                          </Button>
                        ) : projectIngest[selectedId!]?.has_review_records ? (
                          <Button
                            size="small"
                            onClick={() => {
                              const pid = selectedId!;
                              const name = selected.name || `项目 #${pid}`;
                              Modal.confirm({
                                title: "归档项目",
                                content: `将归档项目「${name}」。归档后不再出现在选择列表，历史审查记录保留。`,
                                okText: "归档",
                                cancelText: "取消",
                                onOk: async () => {
                                  await apiJson(`/api/v1/projects/${pid}/archive`, { method: "POST" });
                                  message.success("项目已归档");
                                  setSelectedId(null);
                                  setSelectedConversationId(null);
                                  setProjectViewOnlyReason("");
                                  setCorpusStaleReason("");
                                  await loadProjects();
                                },
                              });
                            }}
                          >
                            归档
                          </Button>
                        ) : null}
                      </Space>
                    </div>

                    {/* Vault 关联行 */}
                    {vaults.length > 0 && (
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8, flexWrap: "wrap" }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>📒 Vault：</Text>
                        <Select
                          size="small"
                          allowClear
                          placeholder="关联 Obsidian Vault（可选）"
                          style={{ minWidth: 220 }}
                          value={selectedVaultId ?? undefined}
                          onChange={(v) => setSelectedVaultId(v ?? null)}
                          options={vaults.map((v) => ({
                            value: v.id,
                            label: `${v.name} (${v.role})`,
                          }))}
                        />
                        <Checkbox
                          checked={indexResolveWikilinks}
                          onChange={(e) => setIndexResolveWikilinks(e.target.checked)}
                        >
                          <Text style={{ fontSize: 12 }}>解析 Wikilinks</Text>
                        </Checkbox>
                      </div>
                    )}
                  </div>
                )}

                <Space wrap>
                  <Button
                    type="primary"
                    disabled={selectedId == null || pipelineRunning}
                    onClick={() =>
                      void runPipelineTryCatch(async () => {
                        setPipelineFailModal(null);
                        setPipelineRunning(true);
                        terminatedRef.current = false;
                        setMilestones([]);
                        setMilestoneOpenOverrides({});
                        setFinalMarkdown("");
                        setFragmentIndexMd("");
                        setOutputEntries([]);
                        setPipelineTaskBrief("初始化项目：对项目目录下的 Markdown 与 HTML 文件建立索引");

                        pipelineStepRef.current = "index";
                        const st = await getProjectIngestStatus(selectedId as number);
                        if (!st.initialized) {
                          await runIndexPhase();
                        }
                        // 持久化 vault 关联到项目
                        if (selectedVaultId != null) {
                          await apiJson(`/api/v1/projects/${selectedId}`, {
                            method: "PATCH",
                            body: JSON.stringify({ vault_id: selectedVaultId }),
                          }).catch(() => {});
                        }
                        message.success("初始化完成：索引已就绪");
                        await loadProjects();
                      })
                    }
                  >
                    初始化
                  </Button>
                  {pipelineRunning ? (
                    <Button danger onClick={stopPipeline}>
                      停止
                    </Button>
                  ) : null}
                </Space>

                {milestones.length ? (
                  <div style={{ marginTop: 10 }}>
                    <Divider style={{ margin: "10px 0" }} />
                    <Title level={5} style={{ margin: "6px 0 10px" }}>
                      初始化日志
                    </Title>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {milestones.map((m) => (
                        <div key={m.id} style={{ fontSize: 12 }}>
                          <details open={m.status === "running"}>
                            <summary className="milestone-stream-summary" style={{ cursor: "pointer" }}>
                              {(m.status === "done" ? "✓ " : m.status === "error" ? "× " : "→ ") + m.name}
                            </summary>
                            <div style={{ marginTop: 6, color: "#6b7280" }}>{renderMilestoneDetail(m)}</div>
                          </details>
                        </div>
                      ))}
                    </div>
                    {/* P1b: CTA after initialization */}
                    {!pipelineRunning && milestones.every((m) => m.status === "done") &&
                      selectedId != null && projectIngest[selectedId]?.initialized ? (
                      <div style={{ marginTop: 16 }}>
                        <Button
                          type="primary"
                          icon={<span style={{ marginRight: 4 }}>→</span>}
                          onClick={() => setMainPanel("analyze")}
                        >
                          开始审查
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </Space>
            </div>
          ) : appMode === "review" && mainPanel === "all_conversations" ? (
            <AllSessionsPanel
              fetchSessions={fetchAllConversations}
              onSelect={(item) => {
                const pid = item.project_id ?? null;
                navPush({ appMode: "review", mainPanel: "analyze", reviewMainTab: "analyze", selectedId: pid, selectedConversationId: item.id });
                if (pid != null) setSelectedId(pid);
                setSelectedConversationId(item.id);
                setMainPanel("analyze");
                setReviewMainTab("analyze");
              }}
            />
          ) : appMode === "review" && mainPanel === "review_domain" ? (
            reviewDomainPageNode
          ) : appMode === "review" && mainPanel === "analyze" && reviewMainTab === "analyze" && !showMainOutput ? (
            <div className="chat-bubble-row chat-bubble-row--assistant">
              <div className="chat-bubble chat-bubble--assistant">
                <ThinkableMarkdown markdown="你好！今天想做哪些方面的项目审查？" />
              </div>
            </div>
          ) : appMode === "review" && mainPanel === "analyze" && reviewMainTab === "analyze" && showMainOutput ? (
            <>
              <div className="page-header">
                <span className="page-header__title">项目审查</span>
                {initializedProjects.find((p) => p.id === selectedId)?.name && (
                  <>
                    <span className="page-header__sep">·</span>
                    <span className="page-header__sub">{initializedProjects.find((p) => p.id === selectedId)?.name}</span>
                  </>
                )}
              </div>
              <div className="pipeline-output-panel pipeline-output-panel--footer-clear">
                {pipelineRunning && lastSubmittedUserMessage?.text ? (
                  <div className="pipeline-output-intro">
                    <div className="chat-bubble-row chat-bubble-row--user">
                      <div className="chat-bubble chat-bubble--user">
                        {lastSubmittedUserMessage.created_at && (
                          <div className="chat-bubble__meta">{formatConversationTime(lastSubmittedUserMessage.created_at)}</div>
                        )}
                        <div className="chat-bubble__text">{lastSubmittedUserMessage.text}</div>
                      </div>
                    </div>
                  </div>
                ) : null}

                {pipelineTaskBrief ? (
                  <div className="pipeline-output-intro">
                    <div className="pipeline-task-brief">{pipelineTaskBrief}</div>
                  </div>
                ) : null}
                {!projectViewOnlyReason.trim() && corpusStaleReason.trim() ? (
                  <Alert
                    type="warning"
                    showIcon
                    message={corpusStaleReason.trim()}
                    style={{ marginBottom: 10 }}
                  />
                ) : null}
                <div className="raw-stream stream-log process-stream">
                  {!pipelineRunning && selectedConversationId != null && historyRuns.length ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      {historyRuns.map((run) => {
                        const it = run.item;
                        const isRereview = it.kind === "rereview";
                        const isFollowup = it.kind === "followup";
                        const isAnalyze = it.kind === "analyze";
                        const title = `${formatConversationTime(it.created_at)} · ${
                          isAnalyze ? "审查" : isFollowup ? "追问" : isRereview ? "重新审查" : it.kind
                        }`;

                        const thinkText = extractHistoryThinkMarkdown(run.finalMarkdown);
                        const hasThink = Boolean(thinkText);
                        const thinkPlaceholder =
                          !hasThink && String(run.split.reportPart || "").trim().length > 0
                            ? "本轮落盘文件未解析出可单独展示的思考片段（例如未使用 think 围栏），审查结论见下方正文。"
                            : "";

                        const reportMd = String(run.split.reportPart || "").trim() || String(run.finalMarkdown || "").trim();

                        return (
                          <div key={`run-${it.id}`} style={{ fontSize: 12 }}>
                            <div style={{ color: "#374151", fontWeight: 650, marginBottom: 6 }}>{title}</div>

                            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                              {it.fragments_index_download_path ? (
                                <>
                                  <div className="milestone-stream-line" style={{ color: "#374151" }}>
                                    ✓ 片段与来源索引 &gt;
                                  </div>
                                  <div className="fragment-index-download-bar">
                                    <Button
                                      type="default"
                                      size="small"
                                      icon={<DownloadOutlined />}
                                      onClick={() =>
                                        window.open(String(it.fragments_index_download_path), "_blank", "noopener,noreferrer")
                                      }
                                    >
                                      片段索引
                                    </Button>
                                  </div>
                                </>
                              ) : null}

                              {(() => {
                                const key = `run-think:${it.id}`;
                                const open = !!milestoneOpenOverrides[key];
                                const sym = open ? "～" : ">";
                                return (
                                  <details
                                    open={open}
                                    onToggle={(ev) => {
                                      setMilestoneOpenOverrides((prev) => ({ ...prev, [key]: ev.currentTarget.open }));
                                    }}
                                  >
                                    <summary className="milestone-stream-summary" style={{ color: "#374151" }}>
                                      ✓ 思考分析 {sym}
                                    </summary>
                                    <div style={{ marginTop: 6, color: "#6b7280" }}>
                                      {run.memoryInjectedItems.length ? (
                                        <div
                                          className="stream-render-text milestone-analysis-think-stream"
                                          style={{ marginBottom: 8, whiteSpace: "pre-wrap" }}
                                        >
                                          {`【加载的记忆】\n${run.memoryInjectedItems
                                            .map((m) => `- ${m.id}${m.title ? ` — ${m.title}` : ""}`)
                                            .join("\n")}`}
                                        </div>
                                      ) : null}
                                      {hasThink ? (
                                        <div className="stream-render-text milestone-analysis-think-stream">{thinkText}</div>
                                      ) : thinkPlaceholder ? (
                                        <div style={{ lineHeight: 1.55 }}>{thinkPlaceholder}</div>
                                      ) : (
                                        <div style={{ lineHeight: 1.55 }}>（暂无已保存的思考过程文本）</div>
                                      )}
                                    </div>
                                  </details>
                                );
                              })()}

                              {reportMd ? (
                                <div className="chat-bubble-row chat-bubble-row--assistant">
                                  <div className="chat-bubble chat-bubble--assistant">
                                    <SimpleMarkdown markdown={reportMd} />
                                  </div>
                                </div>
                              ) : null}

                              <div className="result-actions-below-stream" style={{ paddingLeft: 0, paddingRight: 0 }}>
                                <div className="result-export-row">
                                  <Button
                                    type="default"
                                    size="small"
                                    className="result-export-md-btn"
                                    icon={<DownloadOutlined />}
                                    onClick={() => window.open(it.final_download_path, "_blank", "noopener,noreferrer")}
                                  >
                                    审查报告
                                  </Button>
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : milestones.length ? (
                    <div className="milestone-timeline" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {pipelineRunning ? (
                        <StageTimeline
                          compact
                          stages={milestones
                            .filter((m) => m.id !== "sys:complete" && m.id !== "stage:呈现结果" && m.name !== "呈现结果")
                            .map<Stage>((m) => ({
                              id: m.id,
                              label: m.name,
                              status: m.status === "running" ? "active" : m.status === "done" ? "done" : m.status === "error" ? "done" : "pending",
                            }))}
                        />
                      ) : null}
                      {milestones
                        .filter(
                          (m) =>
                            m.id !== "sys:complete" && m.id !== "stage:呈现结果" && m.name !== "呈现结果",
                        )
                        .flatMap((m) => {
                          const isHistoryView = !pipelineRunning && selectedConversationId != null;
                          const effectiveText = effectiveMilestoneBody(m, activeReportSplit);
                          const showDetails = effectiveText.trim().length > 0;
                          const done = m.status === "done";
                          const running = m.status === "running";
                          const lead = done ? "✓ " : running ? "→ " : "　";
                          const displayName = milestoneDisplayName(m.name);
                          const titleColor = m.status === "error" ? "#cf1322" : "#374151";
                          const isThinkingStage = m.id === "stage:思考分析" || m.name === "思考分析";
                          const defaultOpen = m.status === "running";
                          const o = milestoneOpenOverrides[m.id];
                          const expanded = o !== undefined ? o : defaultOpen;
                          const expandedThinking = isThinkingStage ? (o !== undefined ? o : false) : expanded;
                          const sym = isThinkingStage ? (expandedThinking ? "～" : ">") : ">";
                          const title = `${lead}${displayName} ${sym}`;

                          const milestoneBlock = (
                            <div key={m.id} className="milestone-timeline-item" style={{ fontSize: 12 }}>
                              {isThinkingStage ? (
                                <details
                                  style={{ marginTop: 0 }}
                                  open={expandedThinking}
                                  onToggle={(ev) => {
                                    const el = ev.currentTarget;
                                    if (el.open) userExpandedMilestonesRef.current.add(m.id);
                                    setMilestoneOpenOverrides((prev) => ({ ...prev, [m.id]: el.open }));
                                  }}
                                >
                                  <summary className="milestone-stream-summary" style={{ cursor: "pointer", color: titleColor }}>
                                    {title}
                                  </summary>
                                  <div style={{ marginTop: 6, color: "#6b7280" }}>
                                    {showDetails ? (
                                      renderMilestoneDetail(m, { thinkingOpen: expandedThinking })
                                    ) : (
                                      <span style={{ lineHeight: 1.55 }}>（尚无已保存的思考过程文本）</span>
                                    )}
                                  </div>
                                </details>
                              ) : showDetails ? (
                                <details
                                  style={{ marginTop: 0 }}
                                  open={expanded}
                                  onToggle={(ev) => {
                                    const el = ev.currentTarget;
                                    if (el.open) userExpandedMilestonesRef.current.add(m.id);
                                    setMilestoneOpenOverrides((prev) => ({ ...prev, [m.id]: el.open }));
                                  }}
                                >
                                  <summary className="milestone-stream-summary" style={{ cursor: "pointer", listStyle: "none", color: titleColor }}>
                                    {title}
                                  </summary>
                                  <div style={{ marginTop: 6, color: "#6b7280" }}>{renderMilestoneDetail(m)}</div>
                                </details>
                              ) : (
                                <details
                                  style={{ marginTop: 0 }}
                                  open={expanded}
                                  onToggle={(ev) => {
                                    const el = ev.currentTarget;
                                    if (el.open) userExpandedMilestonesRef.current.add(m.id);
                                    setMilestoneOpenOverrides((prev) => ({ ...prev, [m.id]: el.open }));
                                  }}
                                >
                                  <summary className="milestone-stream-summary" style={{ cursor: "pointer", listStyle: "none", color: titleColor }}>
                                    {title}
                                  </summary>
                                  <div style={{ marginTop: 6, color: "#6b7280" }}>
                                    <span style={{ lineHeight: 1.55 }}>（暂无过程文本）</span>
                                  </div>
                                </details>
                              )}
                            </div>
                          );

                          if (m.id === STAGE_FRAGMENT_INDEX && fragmentIndexMd.trim()) {
                            return [
                              milestoneBlock,
                              <div key={`${m.id}-frag-md-btn`} className="fragment-index-download-bar">
                                <Button type="default" size="small" icon={<DownloadOutlined />} onClick={downloadFragmentIndexMd}>
                                  片段索引
                                </Button>
                              </div>,
                            ];
                          }
                          return [milestoneBlock];
                        })}
                    </div>
                  ) : null}
                </div>
                {/* 会话历史：以消息流为准（同一会话多轮对话合并展示）。replay.entries 仅保留作兼容兜底。 */}
                {!pipelineRunning && selectedConversationId != null && visibleConversationMessages.length ? (
                  <ChatWindow
                    messages={visibleConversationMessages}
                    aria-label="会话消息"
                  />
                ) : !pipelineRunning && replay.entries.length ? (
                  <div className="pipeline-final-report">
                    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                      {replay.entries.map((e) => (
                        <div key={e.id}>
                          <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 6 }}>
                            {formatConversationTime(e.createdAt)} · {e.kind}
                          </div>
                          <ThinkableMarkdown markdown={e.markdown} />
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {/* 会话历史下载：已改为在每个 run 的原位置展示（见上方 historyRuns 回放区域） */}
                {!pipelineRunning && visibleOutputEntries.length ? (
                  <div className="pipeline-final-report">
                    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                      {visibleOutputEntries.map((e) => (
                        <div key={e.id}>
                          <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 6 }}>
                            {formatLocalDateTime(new Date(e.at))} · {e.title}
                          </div>
                          <ThinkableMarkdown markdown={e.markdown} />
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
                {!pipelineRunning && activeReportSplit.reportPart.trim() ? (
                  <div className="pipeline-final-report">
                    <SimpleMarkdown markdown={activeReportSplit.reportPart} />
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
                        审查报告
                      </Button>
                      <Button
                        type="default"
                        size="small"
                        icon={<BulbOutlined />}
                        disabled={selectedId == null || selectedConversationId == null}
                        onClick={() => {
                          setAppMode("extraction");
                          // Pass context so ExtractionPage opens in post-review mode
                          window.sessionStorage.setItem(
                            "aika_post_review_ctx",
                            JSON.stringify({
                              projectId: selectedId,
                              conversationId: selectedConversationId,
                            })
                          );
                        }}
                        title="将本次审查结果发送到知识提取"
                      >
                        提取知识
                      </Button>
                      {vaults.filter((v) => v.role === "knowledge" || v.role === "both").length > 0 ? (
                        <Button
                          type="default"
                          size="small"
                          loading={obsidianExportLoading}
                          disabled={selectedId == null || selectedConversationId == null || !finalMarkdown.trim()}
                          onClick={async () => {
                            const knowledgeVaults = vaults.filter((v) => v.role === "knowledge" || v.role === "both");
                            const targetVault = knowledgeVaults.length === 1
                              ? knowledgeVaults[0]
                              : (selectedVaultId != null && knowledgeVaults.find((v) => v.id === selectedVaultId))
                                || knowledgeVaults[0];
                            if (!targetVault) return;
                            setObsidianExportLoading(true);
                            try {
                              const result = await exportConversationToObsidian(
                                selectedId as number,
                                selectedConversationId as number,
                                {
                                  vault_id: targetVault.id,
                                  content: finalMarkdown,
                                },
                              );
                              message.success(`已写入 Obsidian：${result.note_path.split("/").slice(-1)[0]}`);
                            } catch (e) {
                              message.error(String((e as Error).message));
                            } finally {
                              setObsidianExportLoading(false);
                            }
                          }}
                          title="将审查结论导出为 Obsidian 笔记"
                        >
                          📒 导出到 Obsidian
                        </Button>
                      ) : null}
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
                          disabled={
                            pipelineRunning ||
                            selectedId == null ||
                            !selectedPresetId ||
                              !!projectViewOnlyReason.trim() ||
                              !!corpusStaleReason.trim()
                          }
                          title="重新执行全流程"
                        />
                      </Space>
                    </div>
                  </div>
                ) : null}

                {/* Findings panel */}
                {sessionFindings.length > 0 ? (
                  <div style={{ padding: "0 0 12px 0" }}>
                    <FindingsPanel
                      projectId={selectedId}
                      conversationId={selectedConversationId}
                      findings={sessionFindings}
                      onStatusChange={(findingId: string, status: Finding["status"]) => {
                        if (selectedId == null || selectedConversationId == null) return;
                        void (async () => {
                          try {
                            await fetch(
                              `/api/v1/projects/${selectedId}/conversations/${selectedConversationId}/findings/${findingId}`,
                              { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }
                            );
                            setSessionFindings((prev) => prev.map((f) => (f.id === findingId ? { ...f, status } : f)));
                          } catch {
                            // ignore
                          }
                        })();
                      }}
                      onGenerateReport={() => {
                        if (selectedId == null || selectedConversationId == null) return;
                        setReportLoading(true);
                        void (async () => {
                          try {
                            const res = await fetch(
                              `/api/v1/projects/${selectedId}/conversations/${selectedConversationId}/generate-report`,
                              { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: null, include_resolved: false }) }
                            );
                            const json = await res.json();
                            if (json?.data?.report_markdown) {
                              const md = String(json.data.report_markdown);
                              pushOutputEntry({ kind: "analyze", convId: selectedConversationId, title: "正式评审报告", markdown: md });
                              setFinalMarkdown(md);
                            } else {
                              message.error(json?.error || "生成报告失败");
                            }
                          } catch (e) {
                            message.error(String(e));
                          } finally {
                            setReportLoading(false);
                          }
                        })();
                      }}
                      reportLoading={reportLoading}
                      onAddToQueue={(finding) => {
                        void (async () => {
                          try {
                            await addToReviewQueue({
                              focus_id: finding.focus_id,
                              suggestion: finding.title + (finding.evidence ? `: ${finding.evidence}` : ""),
                              source_type: "post_review",
                              project_id: selectedId,
                              conversation_id: selectedConversationId,
                            });
                            void message.success("已加入知识线索");
                          } catch (e) {
                            void message.error(String(e));
                          }
                        })();
                      }}
                    />
                  </div>
                ) : null}
              </div>
            </>
          ) : null}

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
              因为你选择了与当前会话不同的审查组合，所以系统检测到该预设在历史中已存在审查记录。
              但是此提示仅用于提醒你可回看历史；本次不会自动切换会话。如你确认继续，将在当前会话（或新会话）中按所选预设继续执行。
              <br />
              - 最近审查会话：「{presetGate.latest.title}」
              {presetGate.latest.updated_at ? `（${formatConversationTime(presetGate.latest.updated_at)}）` : ""}
            </Text>
            <Space wrap>
              <Button
                type="primary"
                onClick={() => {
                  if (presetGate?.kind !== "history") return;
                  // 继续：不切换到历史会话；优先沿用当前会话（若可复用），否则新建
                  (async () => {
                    const cid =
                      presetGate.canReuseCurrent && presetGate.currentConvId != null
                        ? presetGate.currentConvId
                        : await createFreshConversationForPreset();
                    if (cid == null) {
                      presetGate.resolve({ kind: "cancel" });
                      setPresetGate(null);
                      return;
                    }
                    setSelectedConversationId(cid);
                    presetGate.resolve({ kind: "ok", convId: cid });
                    setPresetGate(null);
                  })();
                }}
              >
                继续
              </Button>
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
              {pipelineFailModal.step === "index"
                ? "索引与分块"
                : "模型分析"}
            </Text>
            <Text type="danger" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {pipelineFailModal.message}
            </Text>
            <Text type="secondary">排除故障后，可选择从哪一步继续：</Text>
            <Space wrap>
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
        open={isStandaloneSettings ? true : settingsOpen}
        onOk={saveSettings}
        onCancel={() => (isStandaloneSettings ? closeStandaloneView() : setSettingsOpen(false))}
        width={960}
        centered
        okText="保存"
        mask={!isStandaloneSettings}
        getContainer={undefined}
        styles={{
          body: {
            maxHeight: isStandaloneSettings ? "calc(100dvh - 180px)" : "min(580px, calc(100vh - 200px))",
            overflowY: "auto",
            paddingBlock: 12,
          },
        }}
        footer={(_, { OkBtn, CancelBtn }) => (
          <div style={{ display: "flex", justifyContent: "flex-end", width: "100%" }}>
            <Space>
              {isStandaloneSettings ? <Button onClick={closeStandaloneView}>关闭</Button> : <CancelBtn />}
              <OkBtn />
            </Space>
          </div>
        )}
      >
        {settingsTabsNode}
      </Modal>

      <Modal
        title="帮助"
        open={helpOpen}
        onCancel={() => setHelpOpen(false)}
        footer={null}
        width={820}
        getContainer={undefined}
        styles={{
          body: {
            fontSize: 12,
            paddingTop: 8,
            maxHeight: "min(580px, calc(100vh - 200px))",
            overflowY: "auto",
          },
        }}
      >
        <HelpPage compact loading={helpLoading} markdown={helpMarkdown} onClose={() => setHelpOpen(false)} />
      </Modal>
      {/* 新对话：已改为直接进入空白会话页（startNewConversationPage），保留 state 兼容历史但不再使用弹窗 */}

      {/* ── 上传文件 Modal（初始化两步 / 追加单步）── */}
      <Modal
        title={
          uploadModalMode === "init"
            ? (uploadStep === 1 ? "📤 上传文件初始化项目  —  步骤 1/2：选择 Vault" : "📤 上传文件初始化项目  —  步骤 2/2：上传文件")
            : "➕ 向项目追加文件"
        }
        open={uploadModalOpen}
        onCancel={() => { setUploadModalOpen(false); if (uploadInputRef.current) uploadInputRef.current.value = ""; }}
        footer={
          <Space>
            {uploadModalMode === "init" && uploadStep === 1 ? (
              <>
                <Button onClick={() => setUploadModalOpen(false)}>取消</Button>
                <Button
                  type="primary"
                  disabled={uploadModalVaultId === null && vaults.length > 0}
                  onClick={() => setUploadStep(2)}
                >
                  下一步 →
                </Button>
              </>
            ) : (
              <>
                {uploadModalMode === "init"
                  ? <Button onClick={() => setUploadStep(1)}>← 上一步</Button>
                  : <Button onClick={() => setUploadModalOpen(false)}>取消</Button>
                }
                <Button type="primary" loading={uploadLoading} onClick={() => void onDoUpload()}>
                  {uploadModalMode === "init" ? "上传并初始化" : "上传并追加"}
                </Button>
              </>
            )}
          </Space>
        }
        width={580}
      >
        <input ref={uploadInputRef} type="file" style={{ display: "none" }} onChange={onUploadFileChange} />

        {/* ── Step 1：Vault 选择（仅 init 模式）── */}
        {uploadModalMode === "init" && uploadStep === 1 && (
          <Space direction="vertical" style={{ width: "100%" }} size={16}>
            <Text type="secondary">
              选择文件要写入的 Obsidian Vault。Vault 下将创建{" "}
              <Text code>Projects/&lt;项目名&gt;/</Text> 子目录存放转换后的 Markdown。
            </Text>
            {vaults.length > 0 ? (
              <div>
                <Text strong style={{ display: "block", marginBottom: 8 }}>选择目标 Vault</Text>
                <Select
                  style={{ width: "100%" }}
                  placeholder="选择已注册的 Vault"
                  value={uploadModalVaultId ?? undefined}
                  allowClear
                  onChange={(v) => setUploadModalVaultId(v ?? null)}
                  options={vaults
                    .filter((v) => v.role === "project" || v.role === "both")
                    .map((v) => ({ value: v.id, label: `${v.name}  (${v.path})` }))}
                />
                {uploadModalVaultId == null && (
                  <Alert
                    style={{ marginTop: 10 }}
                    type="warning"
                    showIcon
                    message="未选择 Vault，文件将写入后端临时目录，重新部署后丢失。"
                  />
                )}
              </div>
            ) : (
              <Alert
                type="warning"
                showIcon
                message="尚未注册任何 Vault"
                description="文件将写入后端临时目录。建议先关闭此弹窗，点击「Obsidian Vault」按钮完成配置。"
                action={
                  <Button size="small" onClick={() => { setUploadModalOpen(false); setVaultPickerOpen(true); setDiscoveredVaults([]); }}>
                    去配置
                  </Button>
                }
              />
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              没有合适的 Vault？先{" "}
              <a onClick={() => { setUploadModalOpen(false); setVaultPickerOpen(true); setDiscoveredVaults([]); }} style={{ cursor: "pointer" }}>
                注册新 Vault
              </a>
              ，完成后再回来上传。
            </Text>
          </Space>
        )}

        {/* ── Step 2：文件选择 ── */}
        {(uploadModalMode !== "init" || uploadStep === 2) && (
          <Space direction="vertical" style={{ width: "100%" }} size={14}>
            {uploadModalMode === "init" ? (
              uploadModalVaultId != null ? (
                <div style={{ background: "#f6ffed", border: "1px solid #b7eb8f", borderRadius: 6, padding: "8px 12px" }}>
                  <Text>📒 目标 Vault：<Text strong>{vaults.find((v) => v.id === uploadModalVaultId)?.name}</Text></Text>
                  <br />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    文件将写入 <Text code>{vaults.find((v) => v.id === uploadModalVaultId)?.name}/Projects/&lt;项目名&gt;/</Text>
                  </Text>
                </div>
              ) : (
                <Alert type="warning" showIcon message="文件将写入后端临时目录（无 Vault）" />
              )
            ) : (
              <div style={{ background: "#f0f5ff", border: "1px solid #adc6ff", borderRadius: 6, padding: "8px 12px" }}>
                <Text>➕ 追加到项目：<Text strong>{selected?.name}</Text></Text>
                <br />
                <Text type="secondary" style={{ fontSize: 12, wordBreak: "break-all" }}>
                  写入目录：<Text code>{selected?.root_path}</Text>
                </Text>
              </div>
            )}

            <div>
              <Text strong style={{ display: "block", marginBottom: 8 }}>选择文件</Text>
              <Space size={8}>
                <Button onClick={() => {
                  if (!uploadInputRef.current) return;
                  (uploadInputRef.current as any).webkitdirectory = true;
                  uploadInputRef.current.removeAttribute("multiple");
                  uploadInputRef.current.click();
                }}>📁 选择文件夹</Button>
                <Button onClick={() => {
                  if (!uploadInputRef.current) return;
                  (uploadInputRef.current as any).webkitdirectory = false;
                  uploadInputRef.current.setAttribute("multiple", "");
                  uploadInputRef.current.click();
                }}>🗂 选择多个文件</Button>
              </Space>
              <div style={{ marginTop: 4 }}>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  支持格式：.md .txt（直接写入）/ .docx .pdf .xlsx .pptx .html（自动转为 Markdown）
                </Text>
              </div>
            </div>

            {uploadFiles.length > 0 && (
              <div style={{ background: "#fafafa", borderRadius: 6, padding: "8px 12px", fontSize: 13 }}>
                <Text strong>已选 {uploadFiles.length} 个文件：</Text>
                <ul style={{ margin: "4px 0 0 0", paddingLeft: 20 }}>
                  {uploadFileSummary.passCount > 0 && (
                    <li><Text type="secondary">{uploadFileSummary.passCount} 个 Markdown/文本 → 直接写入</Text></li>
                  )}
                  {uploadFileSummary.convCount > 0 && (
                    <li><Text style={{ color: "#1677ff" }}>{uploadFileSummary.convCount} 个 Office/PDF → 将自动转为 Markdown</Text></li>
                  )}
                  {uploadFileSummary.otherCount > 0 && (
                    <li><Text type="warning">{uploadFileSummary.otherCount} 个未知格式 → 尝试转换，失败跳过</Text></li>
                  )}
                </ul>
              </div>
            )}

            {uploadModalMode === "init" && (
              <div>
                <Text strong style={{ display: "block", marginBottom: 6 }}>项目名称</Text>
                <Input
                  value={uploadProjectName}
                  onChange={(e) => setUploadProjectName(e.target.value)}
                  placeholder="从文件夹名自动识别，也可手动修改"
                />
              </div>
            )}
          </Space>
        )}
      </Modal>

      {/* ── Obsidian Vault Picker Modal ── */}
      <Modal
        title="📒 注册 Obsidian Vault"
        open={vaultPickerOpen}
        onCancel={() => setVaultPickerOpen(false)}
        footer={null}
        width={680}
      >
        <Space direction="vertical" style={{ width: "100%" }} size={16}>
          {/* Registered vaults */}
          {vaults.length > 0 ? (
            <div>
              <Text strong>已注册 Vault</Text>
              <div style={{ marginTop: 8 }}>
                {vaults.map((v) => (
                  <div
                    key={v.id}
                    style={{
                      display: "flex", alignItems: "center", gap: 8,
                      padding: "6px 0", borderBottom: "1px solid #f0f0f0",
                    }}
                  >
                    <span style={{ flex: 1 }}>
                      <Text strong>{v.name}</Text>
                      <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                        [{v.role}]
                      </Text>
                      <br />
                      <Text type="secondary" code style={{ fontSize: 11 }}>{v.path}</Text>
                    </span>
                    <Button
                      danger size="small"
                      onClick={async () => {
                        try {
                          await deleteVault(v.id);
                          if (selectedVaultId === v.id) setSelectedVaultId(null);
                          await loadVaults();
                        } catch (e) {
                          message.error(String((e as Error).message));
                        }
                      }}
                    >
                      移除
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Discover */}
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <Text strong>扫描本机 Vault</Text>
              <Button
                size="small"
                loading={discoverLoading}
                onClick={async () => {
                  setDiscoverLoading(true);
                  try {
                    const d = await discoverVaults();
                    setDiscoveredVaults(d.vaults);
                  } catch (e) {
                    message.error(String((e as Error).message));
                  } finally {
                    setDiscoverLoading(false);
                  }
                }}
              >
                扫描
              </Button>
            </div>
            {discoveredVaults.length > 0 ? (
              <div>
                {discoveredVaults.map((dv) => (
                  <div
                    key={dv.path}
                    style={{
                      display: "flex", alignItems: "center", gap: 8,
                      padding: "6px 0", borderBottom: "1px solid #f0f0f0",
                    }}
                  >
                    <span style={{ flex: 1 }}>
                      <Text strong>{dv.name}</Text>
                      {dv.already_registered ? (
                        <Tag color="green" style={{ marginLeft: 8 }}>已注册</Tag>
                      ) : null}
                      <br />
                      <Text type="secondary" code style={{ fontSize: 11 }}>{dv.path}</Text>
                    </span>
                    {!dv.already_registered ? (
                      <Button
                        size="small" type="primary"
                        loading={vaultRegLoading}
                        onClick={async () => {
                          setVaultRegLoading(true);
                          try {
                            await registerVault({ path: dv.path, role: "project" });
                            await loadVaults();
                            message.success(`已注册：${dv.name}`);
                            setDiscoveredVaults((prev) =>
                              prev.map((x) => x.path === dv.path ? { ...x, already_registered: true } : x)
                            );
                          } catch (e) {
                            message.error(String((e as Error).message));
                          } finally {
                            setVaultRegLoading(false);
                          }
                        }}
                      >
                        注册
                      </Button>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : discoverLoading ? null : (
              <Text type="secondary" style={{ fontSize: 12 }}>点击「扫描」搜索本机 Obsidian Vault</Text>
            )}
          </div>

          {/* Manual registration */}
          <div>
            <Text strong>手动注册路径</Text>
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
              <Input
                placeholder="Vault 绝对路径（含 .obsidian/ 目录）"
                value={vaultManualPath}
                onChange={(e) => setVaultManualPath(e.target.value)}
              />
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Text style={{ fontSize: 12 }}>角色：</Text>
                <Radio.Group
                  size="small"
                  value={vaultManualRole}
                  onChange={(e) => setVaultManualRole(e.target.value as "project" | "knowledge" | "both")}
                >
                  <Radio.Button value="project">项目文档</Radio.Button>
                  <Radio.Button value="knowledge">知识库</Radio.Button>
                  <Radio.Button value="both">两用</Radio.Button>
                </Radio.Group>
                <Button
                  type="primary" size="small"
                  loading={vaultRegLoading}
                  disabled={!vaultManualPath.trim()}
                  onClick={async () => {
                    setVaultRegLoading(true);
                    try {
                      const v = await registerVault({ path: vaultManualPath.trim(), role: vaultManualRole });
                      await loadVaults();
                      setVaultManualPath("");
                      message.success(`已注册：${v.name}`);
                    } catch (e) {
                      message.error(String((e as Error).message));
                    } finally {
                      setVaultRegLoading(false);
                    }
                  }}
                >
                  注册
                </Button>
              </div>
            </div>
          </div>
        </Space>
      </Modal>
        </div>
      </div>
        </>
        )}
      </div>{/* end app-main */}

      {/* ── Rename Conversation Modal ── */}
      <Modal
        open={renameConvId != null}
        title="重命名会话"
        onOk={async () => {
          if (renameConvId == null) return;
          const t = renameConvValue.trim();
          if (!t) return;
          await patchConversation(renameConvId, { title: t });
          setRenameConvId(null);
          await loadConversations({ q: chatSearchQuery });
        }}
        onCancel={() => setRenameConvId(null)}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Input
          value={renameConvValue}
          onChange={(e) => setRenameConvValue(e.target.value)}
          onPressEnter={async () => {
            if (renameConvId == null) return;
            const t = renameConvValue.trim();
            if (!t) return;
            await patchConversation(renameConvId, { title: t });
            setRenameConvId(null);
            await loadConversations({ q: chatSearchQuery });
          }}
          maxLength={80}
        />
      </Modal>

      {/* ── Expert Profile Modal ── */}
      <Modal
        open={profileModalOpen}
        title="完善专家画像（约 3 分钟）"
        onOk={() => void handleSaveProfile()}
        onCancel={() => setProfileModalOpen(false)}
        okText="保存画像"
        cancelText="稍后再说"
        confirmLoading={profileSaving}
        width={600}
      >
        <div style={{ marginBottom: 8, color: "#888", fontSize: 13 }}>
          画像完成后 AI 将基于你的背景提问，不会问低质量的通用问题。
        </div>
        <Form layout="vertical">
          <Form.Item label="你主要负责或擅长的行业（多选）">
            <Checkbox.Group
              value={profileDraft.industries}
              onChange={(v) => setProfileDraft((d) => ({ ...d, industries: v as string[] }))}
              options={["汽车整车", "汽车零部件", "通用机械", "工程机械", "电力装备", "电子制造", "航空航天", "轨道交通", "船舶海工"]}
              style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px" }}
            />
          </Form.Item>
          <Form.Item label="你主要擅长哪些生产模式（多选）">
            <Checkbox.Group
              value={profileDraft.production_modes}
              onChange={(v) => setProfileDraft((d) => ({ ...d, production_modes: v as string[] }))}
              options={[
                "批量离散制造", "混线柔性装配", "配置式制造", "离散装配岛模式",
                "连续+离散混合制造", "返工/维修型制造", "模块化制造", "高变异小批量定制",
              ]}
              style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px" }}
            />
          </Form.Item>
          <Form.Item label="你擅长的功能模块（多选）">
            <Checkbox.Group
              value={profileDraft.functional_modules}
              onChange={(v) => setProfileDraft((d) => ({ ...d, functional_modules: v as string[] }))}
              options={[
                "计划排程", "执行与追溯", "质量管理", "质量控制", "物流管理", "仓库管理",
                "能源管理", "设备管理", "数据采集与设备集成", "报表分析", "制造工艺管理", "数据分析",
              ]}
              style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px" }}
            />
          </Form.Item>
          <Form.Item label="你最希望 AI 辅助解决哪个阶段的问题（多选）">
            <Checkbox.Group
              value={profileDraft.focus_areas}
              onChange={(v) => setProfileDraft((d) => ({ ...d, focus_areas: v as string[] }))}
              options={["售前与方案设计", "蓝图确认阶段", "开发与测试管理", "上线陪跑与验收", "客户关系与变更管理"]}
              style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px" }}
            />
          </Form.Item>
        </Form>
      </Modal>


      {appMode === "review" && mainPanel === "analyze" ? (
        <>
          {reviewMainTab === "review_queue" ? (
            <div style={{ maxWidth: 980, margin: "0 auto", width: "100%" }}>
              <div className="page-header">
                <Button type="text" size="small" icon={<ArrowLeftOutlined />}
                  onClick={() => setReviewMainTab("analyze")} title="返回" style={{ marginRight: 4 }} />
                <span className="page-header__title">知识线索</span>
              </div>
              <div style={{ padding: "0 24px" }}>
                <ReviewQueueTab onStartExtraction={handleStartFromReviewQueue} />
              </div>
            </div>
          ) : reviewMainTab === "result_review" ? (
            <div style={{ maxWidth: 980, margin: "0 auto", width: "100%" }}>
              <div className="page-header">
                <Button type="text" size="small" icon={<ArrowLeftOutlined />}
                  onClick={() => { navPush({ appMode: "review", mainPanel: "analyze", reviewMainTab: "analyze", selectedId, selectedConversationId }); setReviewMainTab("analyze"); }} title="返回" style={{ marginRight: 4 }} />
                <span className="page-header__title">待批准规则</span>
              </div>
              <div style={{ padding: "0 24px" }}>
                <PendingRulesTab reviewedBy={currentUser?.display_name} />
              </div>
            </div>
          ) : (
        <div className="composer-overlay composer-overlay-bottom">
          <div className="composer-overlay-inner">
            <div className="composer-footer-stack">
              <div style={{ padding: "0 12px 12px" }}>
              <div className="composer">
                <Input.TextArea
                  className="composer-textarea"
                  autoSize={{ minRows: 2, maxRows: 6 }}
                  placeholder={composerTextPlaceholder}
                  value={draftText}
                  onChange={(e) => setDraftText(e.target.value)}
                  style={{ background: "#fff", border: "none", boxShadow: "none" }}
                />
                <div className="composer-toolbar">
                  <div className="composer-left">
                    {/* "+" dropdown for project selection and other actions */}
                    <Dropdown
                      trigger={["click"]}
                      placement="topLeft"
                      dropdownRender={() => (
                        <div style={{
                          background: "#fff", border: "1px solid #e0e0d8", borderRadius: 10,
                          padding: "10px 12px", minWidth: 260,
                          boxShadow: "0 4px 16px rgba(0,0,0,0.10)",
                        }}>
                          <div style={{ fontSize: 11, color: "#999", marginBottom: 6 }}>选择项目</div>
                          {/* P2b: 所有项目，未初始化带标签 */}
                          <div style={{ maxHeight: 200, overflowY: "auto", display: "flex", flexDirection: "column", gap: 2 }}>
                            {allProjectsSorted.map((p) => {
                              const isInited = !!projectIngest[p.id]?.initialized;
                              const isSelected = p.id === selectedId;
                              return (
                                <div
                                  key={p.id}
                                  onClick={() => {
                                    if (!isInited) {
                                      setSelectedId(p.id);
                                      setMainPanel("ingest");
                                    } else {
                                      setSelectedId(p.id);
                                      setProjectViewOnlyReason("");
                                      setCorpusStaleReason("");
                                    }
                                  }}
                                  style={{
                                    display: "flex", alignItems: "center", gap: 6,
                                    padding: "5px 8px", borderRadius: 6, cursor: "pointer",
                                    background: isSelected ? "#f0f9f4" : "transparent",
                                    fontSize: 13,
                                  }}
                                  onMouseEnter={(e) => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "#f5f5f5"; }}
                                  onMouseLeave={(e) => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                                >
                                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</span>
                                  {!isInited && <Tag color="warning" style={{ fontSize: 10, padding: "0 4px", margin: 0 }}>未就绪</Tag>}
                                </div>
                              );
                            })}
                            {allProjectsSorted.length === 0 && (
                              <div style={{ fontSize: 12, color: "#aaa", padding: "4px 8px" }}>暂无项目</div>
                            )}
                          </div>
                          <div style={{ marginTop: 8, borderTop: "1px solid #f0f0f0", paddingTop: 8, display: "flex", flexDirection: "column", gap: 2 }}>
                            <Button type="text" size="small" icon={<FolderOpenOutlined />} block
                              style={{ textAlign: "left", justifyContent: "flex-start" }}
                              onClick={() => { setMainPanel("ingest"); }}>
                              注册新项目目录
                            </Button>
                            {/* P2a: Obsidian 快速入口 */}
                            <Button type="text" size="small" icon={<span style={{ marginRight: 4 }}>📒</span>} block
                              style={{ textAlign: "left", justifyContent: "flex-start" }}
                              onClick={() => {
                                setMainPanel("ingest");
                                setVaultPickerOpen(true);
                                setDiscoveredVaults([]);
                              }}>
                              从 Obsidian Vault 加载
                            </Button>
                          </div>
                        </div>
                      )}
                    >
                      <Button size="small" type="text" icon={<PlusOutlined />}
                        style={{ borderRadius: 6, fontWeight: 600, fontSize: 15 }} title="选择项目 / 更多" />
                    </Dropdown>
                    {/* Show selected project name as compact indicator */}
                    {selectedId != null && projects.find((p) => p.id === selectedId) && (
                      <span style={{ fontSize: 12, color: "#527c5e", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {projects.find((p) => p.id === selectedId)?.name}
                      </span>
                    )}
                    {/* 模式 C：不展示预设；由后端 Agent 自动路由关注点组合 */}
                    {!focusPresets.length && settingsDraft.review_domain_path ? (
                      <Text type="secondary" style={{ fontSize: 11, maxWidth: 240 }}>
                        无预设（读取 <Text code>{settingsDraft.review_domain_path}</Text>）
                      </Text>
                    ) : null}
                    {/* 深度模式开关 */}
                    <Tooltip
                      title={deepMode ? "⚡深度模式已开启：分析后追加自我审查，约消耗 2-3x tokens" : "开启深度模式（自我审查）"}
                    >
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                          cursor: "pointer",
                          padding: "0 6px",
                          borderRadius: 4,
                          background: deepMode ? "#fff7e6" : "transparent",
                          border: deepMode ? "1px solid #faad14" : "1px solid transparent",
                          fontSize: 12,
                          color: deepMode ? "#d46b08" : "#8c8c8c",
                          userSelect: "none",
                        }}
                        onClick={() => setDeepMode((v) => !v)}
                      >
                        ⚡{deepMode ? " 深度" : ""}
                      </span>
                    </Tooltip>
                  </div>
                  <div className="composer-right composer-run-actions">
                    {pipelineRunning ? (
                      <Tooltip title="停止" trigger={["hover"]} placement="top">
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
                      <Tooltip title="开始" trigger={["hover"]} placement="top">
                        <span className="composer-run-tooltip-wrap">
                          <Button
                            className="composer-run"
                            shape="circle"
                            type="primary"
                            icon={<ArrowUpOutlined className="composer-run-icon" />}
                            disabled={!canStartAgentMessage}
                            onClick={() => void runAgentMessage()}
                          />
                        </span>
                      </Tooltip>
                    )}
                  </div>
                </div>
              </div>
              </div>
              {showMainOutput ? <div className="composer-disclaimer">{COMPOSER_DISCLAIMER}</div> : null}
            </div>
          </div>
        </div>
          )}
        </>
      ) : null}
    </div>
  );
}
