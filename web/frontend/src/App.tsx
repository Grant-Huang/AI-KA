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
  Popover,
  Select,
  Space,
  Spin,
  Table,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  DownloadOutlined,
  InfoCircleOutlined,
  PlayCircleOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { apiJson, openConvertStream, postAnalyzeStream } from "./api";
import SimpleMarkdown from "./SimpleMarkdown";

const { Text } = Typography;

type Project = { id: number; name: string; root_path: string };
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
type FocusComboTip = { stage: string; recommended: string };
type FocusPreset = { id: string; name: string; focus_points: string[] };
type SettingsData = {
  focus_points: FocusPoint[];
  focus_presets?: FocusPreset[];
  chunk_limit: number;
  disable_image_parse?: boolean;
  llm_settings: LlmSettings;
  focus_combo_tips?: FocusComboTip[];
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

export default function App() {
  const TEXT_MODEL_OPTIONS = ["qwen3", "MiniMax-M2.5"];
  const VL_MODEL_OPTIONS = ["qwen3-vl-plus"];

  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pickedRootPath, setPickedRootPath] = useState<string>("");

  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [finalMarkdown, setFinalMarkdown] = useState<string>("");

  const [chunkLimit, setChunkLimit] = useState(40);
  const [nativePickerAvailable, setNativePickerAvailable] = useState(true);
  const [pickLoading, setPickLoading] = useState(false);
  const [focusPoints, setFocusPoints] = useState<string[]>([]);
  const [focusDefs, setFocusDefs] = useState<FocusPoint[]>([]);
  const [focusComboTips, setFocusComboTips] = useState<FocusComboTip[]>([]);
  const [focusPresets, setFocusPresets] = useState<FocusPreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState<string>("");
  const [pipelineRunning, setPipelineRunning] = useState(false);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpMarkdown, setHelpMarkdown] = useState<string>("");
  const [helpLoading, setHelpLoading] = useState(false);
  const [settingsDraft, setSettingsDraft] = useState<SettingsData>({
    focus_points: [],
    chunk_limit: 40,
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

  const rulesFileInputRef = useRef<HTMLInputElement | null>(null);
  const stopConvertRef = useRef<(() => void) | null>(null);
  const stopAnalyzeRef = useRef<(() => void) | null>(null);
  const analyzeAbortRef = useRef<AbortController | null>(null);
  const terminatedRef = useRef(false);
  const deltaAccRef = useRef<string>(""); // accumulated model-output text used for dedup
  const currentStageKeyRef = useRef<string>("");
  const lastMilestoneIdRef = useRef<string>("");

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
  }, []);

  const loadProjects = useCallback(async () => {
    const data = await apiJson<{ projects: Project[] }>("/api/v1/projects");
    setProjects(data.projects || []);
    setSelectedId((prev) => {
      if (data.projects?.length && prev == null) return data.projects[0].id;
      return prev;
    });
  }, []);

  const loadSettings = useCallback(async () => {
    const data = await apiJson<SettingsData>("/api/v1/settings");
    setChunkLimit(data.chunk_limit);
    setFocusDefs(data.focus_points);
    setFocusComboTips(data.focus_combo_tips || []);
    setFocusPresets(data.focus_presets || []);
    setSettingsDraft(data);
    setFocusSelectedIndex(0);
    setPresetSelectedIndex(0);
    setRulesMdError(data.rules_md_error || null);
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
    if (!settingsOpen) return;
    // 每次打开设置时都从后端刷新，避免显示旧值/读错配置源时难以定位
    loadSettings().catch((e) => message.error(String((e as Error).message)));
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
      setFocusComboTips(data.focus_combo_tips || []);
      setFocusPresets(data.focus_presets || []);
      setSettingsDraft(data);
      setPresetSelectedIndex(0);
      setRulesMdError(data.rules_md_error || null);
      setTextApiKeyDraft("");
      setTextApiKeyTouched(false);
      setVlApiKeyDraft("");
      setVlApiKeyTouched(false);
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

  const parseRecommendedFocus = (s: string): string[] => {
    const raw = String(s || "").trim();
    if (!raw) return [];
    // 优先解析 rules.md 中稳定的 `focus:<id>` 格式
    const ids = Array.from(raw.matchAll(/focus:([a-zA-Z0-9_\-]+)/g)).map((m) => String(m[1] || "").trim()).filter(Boolean);
    const idToName = new Map(focusDefs.map((x) => [x.id, x.name]));
    if (ids.length) {
      const out: string[] = [];
      const seen = new Set<string>();
      for (const id of ids) {
        const name = idToName.get(id);
        if (!name) continue;
        if (seen.has(name)) continue;
        seen.add(name);
        out.push(name);
      }
      return out;
    }

    // 兼容旧格式：直接按名称拆分
    const parts = raw.split(/[,+、\s]+/g).map((x) => x.trim()).filter(Boolean);
    const allow = new Set(focusDefs.map((x) => x.name));
    const out: string[] = [];
    const seen = new Set<string>();
    for (const p of parts) {
      if (!allow.has(p)) continue;
      if (seen.has(p)) continue;
      seen.add(p);
      out.push(p);
    }
    return out;
  };

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
    return <SimpleMarkdown markdown={t || "（暂无内容）"} />;
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

  const runFullPipeline = async () => {
    if (selectedId == null) {
      message.warning("请先选择或创建项目");
      return;
    }
    if (focusPoints.length === 0) {
      message.warning("请至少选择一个关注点");
      return;
    }
    setPipelineRunning(true);
    terminatedRef.current = false;
    deltaAccRef.current = "";
    currentStageKeyRef.current = "";
    setMilestones([]);
    setFinalMarkdown("");
    try {
      ensureMilestone("sys:convert", "文档转换", "system");
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

      ensureMilestone("sys:index", "索引与分块", "system");
      appendMilestoneDetail("sys:index", "【索引】正在将 Markdown 写入索引与分块…\n");
      const idx = await apiJson<{ indexed_documents: number }>(`/api/v1/projects/${selectedId}/index-md`, { method: "POST" });
      appendMilestoneDetail("sys:index", `【索引】完成，已索引 ${idx.indexed_documents} 个文档。\n`);
      setMilestoneStatus("sys:index", "done");
      if (terminatedRef.current) return;

      // 分析阶段由后端 stage 事件驱动，不预先创建未来里程碑
      currentStageKeyRef.current = "";

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
        postAnalyzeStream(
          selectedId,
          { chunk_limit: chunkLimit, focus_points: focusPoints },
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
                // 不输出冗余“开始/完成”提示，仅创建里程碑
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
      setFinalMarkdown(md);
      message.success("全流程完成");
    } catch (e) {
      if ((e as Error)?.name === "AbortError" || terminatedRef.current) return;
      const msg = String((e as Error).message);
      const target = currentStageKeyRef.current || lastMilestoneIdRef.current || "sys:control";
      ensureMilestone(target, target.startsWith("stage:") ? target.slice(6) : "系统调用", "error");
      appendMilestoneDetail(target, `[error] ${msg}\n`);
      setMilestoneStatus(target, "error");
      message.error(msg);
    } finally {
      setPipelineRunning(false);
      analyzeAbortRef.current = null;
      stopConvertRef.current = null;
      stopAnalyzeRef.current = null;
    }
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

  return (
    <div className="app-shell">
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={2} style={{ margin: 0 }}>
          AI-KA 业务关联审查平台
        </Typography.Title>
        <Space>
          <Button shape="circle" icon={<QuestionCircleOutlined />} onClick={() => setHelpOpen(true)} title="帮助" />
          <Button shape="circle" icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)} title="设置" />
        </Space>
      </Space>
      <Text type="secondary">选择项目目录与关注点，一键完成转换、索引与审查，并可导出 Markdown。</Text>
      <Divider />

      <Space direction="vertical" style={{ width: "100%" }} size={10}>
        {rulesMdError ? (
          <Alert
            type="error"
            showIcon
            message={`rules.md 格式异常：${rulesMdError}`}
            description="系统已自动回退到 default_rules.md。请修复 rules.md 后刷新页面，或在设置页保存一次。"
          />
        ) : null}
        <Space wrap>
          <Button type="primary" loading={pickLoading} disabled={!nativePickerAvailable} onClick={onPickDirectory}>
            选择项目
          </Button>
          {pickedRootPath ? <Text code>{pickedRootPath}</Text> : <Text type="secondary">未选择项目路径</Text>}
        </Space>
        {selected ? <Text>{`已识别项目：${selected.name}`}</Text> : <Text type="secondary">选择项目目录</Text>}
        <Space wrap align="center">
          <Select
            mode="multiple"
            allowClear
            style={{ minWidth: 520 }}
            placeholder="选择分析关注点（可多选）"
            value={focusPoints}
            options={focusDefs.map((x) => ({ value: x.name, label: x.name }))}
            onChange={(v) => setFocusPoints(v as string[])}
          />
          {focusPresets.length ? (
            <Select
              style={{ width: 200 }}
              placeholder="选择预设"
              value={selectedPresetId || undefined}
              allowClear
              options={focusPresets.map((p) => ({ value: p.id, label: p.name }))}
              onChange={(v) => {
                const id = String(v || "");
                setSelectedPresetId(id);
                const preset = focusPresets.find((p) => p.id === id);
                if (preset) {
                  setFocusPoints(preset.focus_points || []);
                  message.success(`已套用预设：${preset.name}`);
                }
              }}
            />
          ) : null}
          {focusComboTips.length > 0 ? (
            <Popover
              trigger="click"
              placement="bottomLeft"
              title="关注点组合建议（来自 rules.md）"
              content={
                <Table
                  size="small"
                  pagination={false}
                  style={{ width: 640 }}
                  rowKey={(r) => r.stage}
                  dataSource={focusComboTips}
                  columns={[
                    { title: "评审节点", dataIndex: "stage", key: "stage", width: 160 },
                    { title: "推荐组合的关注点", dataIndex: "recommended", key: "recommended" },
                    {
                      title: "操作",
                      key: "op",
                      width: 90,
                      render: (_: unknown, r: FocusComboTip) => (
                        <Button
                          size="small"
                          onClick={() => {
                            const next = parseRecommendedFocus(r.recommended || "");
                            if (!next.length) {
                              message.warning("未解析到可用关注点（请确认 rules.md 推荐组合使用 focus:<id> 或名称能匹配关注点列表）");
                              return;
                            }
                            setFocusPoints(next);
                            message.success("已套用推荐组合");
                          }}
                        >
                          套用
                        </Button>
                      ),
                    },
                  ]}
                />
              }
            >
              <Button size="small" icon={<InfoCircleOutlined />}>
                组合建议
              </Button>
            </Popover>
          ) : null}
        </Space>
        <Space wrap>
          <Tooltip title={pipelineRunning ? "终止当前流程（会中断转换/分析）" : "执行：转换→索引→分析"}>
            <Button
              type="primary"
              danger={pipelineRunning}
              loading={pipelineRunning}
              onClick={pipelineRunning ? stopPipeline : runFullPipeline}
              disabled={selectedId == null}
              icon={pipelineRunning ? <StopOutlined /> : <PlayCircleOutlined />}
            >
              {pipelineRunning ? "终止" : "执行"}
            </Button>
          </Tooltip>
          <Button icon={<DownloadOutlined />} onClick={exportMarkdown} disabled={!finalMarkdown.trim()}>
            导出 md
          </Button>
        </Space>
      </Space>

      <div style={{ marginTop: 12, marginBottom: 16 }}>
        {pipelineRunning ? <Text type="secondary">分析进行中…（可滚动查看实时输出）</Text> : null}
        <div className="raw-stream stream-log process-stream">
          {milestones.length ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {milestones.map((m) => {
                const showDetails = (m.detailText || "").trim().length > 0;
                const done = m.status === "done";
                const title = done ? `✓ ${m.name} >` : `${m.name} >`;
                const titleColor = m.status === "error" ? "#cf1322" : "#374151";
                return (
                  <div key={m.id} style={{ fontSize: 12 }}>
                    {showDetails ? (
                      <details style={{ marginTop: 0 }}>
                        <summary style={{ cursor: "pointer", listStyle: "none", color: titleColor }}>
                          {title}
                        </summary>
                        <div style={{ marginTop: 6 }}>{renderMilestoneDetail(m)}</div>
                      </details>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : (
            <Text type="secondary">（将按完成进度逐步显示里程碑；细节默认折叠）</Text>
          )}
        </div>
      </div>

      {finalMarkdown.trim() ? (
        <div style={{ marginTop: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <Text strong>结果</Text>
            <Button icon={<DownloadOutlined />} onClick={exportMarkdown}>
              导出 md
            </Button>
          </div>
          <div style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 12, background: "#fff" }}>
            <SimpleMarkdown markdown={finalMarkdown} />
          </div>
        </div>
      ) : null}

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
              <Button size="small" onClick={addPreset}>
                新增预设
              </Button>
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
                        justifyContent: "space-between",
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
                      <Button
                        size="small"
                        danger
                        onClick={(e) => {
                          e.stopPropagation();
                          deletePreset(idx);
                        }}
                      >
                        删除
                      </Button>
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
    </div>
  );
}
