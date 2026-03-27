import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Card, Divider, Input, InputNumber, Popover, message, Modal, Select, Space, Spin, Table, Tabs, Typography } from "antd";
import { InfoCircleOutlined, QuestionCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { apiJson, openAnalyzeStream, openConvertStream, postRulesGenerateStream, waitAnalyzeStream, waitConvertStream } from "./api";
import { BlockRenderer, type Block } from "./BlockRenderer";

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
type SettingsData = {
  focus_points: FocusPoint[];
  chunk_limit: number;
  llm_settings: LlmSettings;
  focus_combo_tips?: FocusComboTip[];
  rules_md_error?: string | null;
};

export default function App() {
  const TEXT_MODEL_OPTIONS = ["qwen3", "MiniMax-M2.5"];
  const VL_MODEL_OPTIONS = ["qwen3-vl-plus"];
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pickedRootPath, setPickedRootPath] = useState<string>("");
  const [convertLog, setConvertLog] = useState("");
  const [streamText, setStreamText] = useState("");
  const [analysis, setAnalysis] = useState<{ title?: string; blocks?: Block[] } | null>(null);
  const [chunkLimit, setChunkLimit] = useState(40);
  const [nativePickerAvailable, setNativePickerAvailable] = useState(true);
  const [pickLoading, setPickLoading] = useState(false);
  const [focusPoints, setFocusPoints] = useState<string[]>([]);
  const [focusDefs, setFocusDefs] = useState<FocusPoint[]>([]);
  const [focusComboTips, setFocusComboTips] = useState<FocusComboTip[]>([]);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [outputTab, setOutputTab] = useState<string>("process");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [settingsDraft, setSettingsDraft] = useState<SettingsData>({
    focus_points: [],
    chunk_limit: 40,
    llm_settings: {
      text_provider: "openai_compatible",
      text_base_url: "",
      text_model: "qwen3",
      vl_model: "qwen3-vl-plus",
      vl_base_url: "",
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
  const rulesFileInputRef = useRef<HTMLInputElement | null>(null);

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
    setSettingsDraft(data);
    setFocusSelectedIndex(0);
    setRulesMdError(data.rules_md_error || null);
    setTextApiKeyDraft("");
    setTextApiKeyTouched(false);
    setVlApiKeyDraft("");
    setVlApiKeyTouched(false);
  }, []);

  useEffect(() => {
    loadProjects().catch((e) => message.error(String(e.message)));
    loadSettings().catch((e) => message.error(String(e.message)));
  }, [loadProjects, loadSettings]);

  useEffect(() => {
    apiJson<{ native_folder_picker: boolean }>("/api/v1/fs/capabilities")
      .then((d) => setNativePickerAvailable(!!d.native_folder_picker))
      .catch(() => setNativePickerAvailable(false));
  }, []);

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
      setSettingsDraft(data);
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
          setSettingsDraft(data);
          setFocusSelectedIndex(0);
          setRulesMdError(data.rules_md_error || null);
          message.success("rules.md 已加载并保存");
        },
      });
    } catch (err) {
      message.error(String((err as Error).message));
    }
  };

  const appendProcess = (s: string) => setStreamText((prev) => prev + s);
  const appendBackend = (s: string) => setConvertLog((prev) => prev + s);

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
    setStreamText("");
    setConvertLog("");
    setAnalysis(null);
    setOutputTab("process");
    try {
      appendProcess("【规则生成】正在调用大模型生成分析规则 JSON…\n");
      await postRulesGenerateStream(
        selectedId,
        { focus_points: focusPoints, focus_note: "" },
        (ev) => {
          if (ev.type === "delta" && typeof ev.text === "string") appendProcess(ev.text);
          if (ev.type === "final") appendProcess("\n【规则生成】已完成并保存。\n");
        },
      );

      appendBackend("【docs2md】开始转换…\n");
      setOutputTab("log");
      await waitConvertStream(selectedId, (line) => appendBackend(line));
      appendBackend("【docs2md】转换完成。\n");

      appendBackend("【索引】正在将 Markdown 写入索引与分块…\n");
      const idx = await apiJson<{ indexed_documents: number }>(`/api/v1/projects/${selectedId}/index-md`, { method: "POST" });
      appendBackend(`【索引】完成，已索引 ${idx.indexed_documents} 个文档。\n`);

      setOutputTab("process");
      appendProcess("\n【大模型分析】开始流式输出…\n");
      const fin = await waitAnalyzeStream(selectedId, chunkLimit, (t) => appendProcess(t));
      if (fin.analysis && typeof fin.analysis === "object") {
        setAnalysis(fin.analysis as { title?: string; blocks?: Block[] });
      } else if (fin.raw) {
        appendProcess(fin.raw);
        message.warning("模型输出非 JSON，已显示原文");
      }
      message.success("全流程完成");
    } catch (e) {
      const msg = String((e as Error).message);
      appendProcess(`\n[error] ${msg}\n`);
      appendBackend(`\n[error] ${msg}\n`);
      setOutputTab("log");
      message.error(msg);
    } finally {
      setPipelineRunning(false);
    }
  };

  const exportDocx = async () => {
    if (selectedId == null || !analysis) {
      message.warning("请先完成分析");
      return;
    }
    try {
      const data = await apiJson<{ download_path: string }>(`/api/v1/projects/${selectedId}/export/docx`, {
        method: "POST",
        body: JSON.stringify({ analysis, title: analysis.title || "项目分析", theme: "tech" }),
      });
      window.open(data.download_path, "_blank");
      message.success("已开始下载");
    } catch (e) {
      message.error(String((e as Error).message));
    }
  };

  return (
    <div className="app-shell">
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={2} style={{ margin: 0 }}>
          AI-KA ProjectLens
        </Typography.Title>
        <Space>
          <Button shape="circle" icon={<QuestionCircleOutlined />} onClick={() => setHelpOpen(true)} title="帮助" />
          <Button shape="circle" icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)} title="设置" />
        </Space>
      </Space>
      <Text type="secondary">选择目录后自动加载项目并开始一键分析。</Text>
      <Divider />

      <Card title="一键分析" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: "100%" }} size={10}>
          {rulesMdError ? (
            <Alert
              type="error"
              showIcon
              message={`rules.md 格式异常：${rulesMdError}`}
              description="系统已自动回退到数据库中的上次有效设置。请修复 rules.md 后刷新页面，或在设置页保存一次。"
            />
          ) : null}
          <Space wrap>
            <Button type="primary" loading={pickLoading} disabled={!nativePickerAvailable} onClick={onPickDirectory}>
              选择项目
            </Button>
            {pickedRootPath ? <Text code>{pickedRootPath}</Text> : <Text type="secondary">未选择项目路径</Text>}
          </Space>
          {selected ? <Text>{`已识别项目：${selected.name}`}</Text> : <Text type="secondary">选择项目目录</Text>}
          <Select
            mode="multiple"
            allowClear
            style={{ minWidth: 520 }}
            placeholder="选择分析关注点（可多选）"
            value={focusPoints}
            options={focusDefs.map((x) => ({ value: x.name, label: x.name }))}
            onChange={(v) => setFocusPoints(v as string[])}
          />
          {focusComboTips.length > 0 ? (
            <Popover
              trigger="click"
              placement="bottomLeft"
              title="关注点组合建议（来自 rules.md）"
              content={
                <Table
                  size="small"
                  pagination={false}
                  style={{ width: 560 }}
                  rowKey={(r) => r.stage}
                  dataSource={focusComboTips}
                  columns={[
                    { title: "评审节点", dataIndex: "stage", key: "stage", width: 180 },
                    { title: "推荐组合的关注点", dataIndex: "recommended", key: "recommended" },
                  ]}
                />
              }
            >
              <Button icon={<InfoCircleOutlined />}>组合建议 Tips</Button>
            </Popover>
          ) : null}
          <Space wrap>
            <Button type="primary" loading={pipelineRunning} onClick={runFullPipeline} disabled={selectedId == null}>
              开始分析
            </Button>
            <Button onClick={exportDocx} disabled={selectedId == null || !analysis}>
              导出 docx（epic-doc）
            </Button>
          </Space>
        </Space>
        <div style={{ marginTop: 12 }}>
          <Spin spinning={pipelineRunning}>
            <Tabs
              activeKey={outputTab}
              onChange={setOutputTab}
              items={[
                {
                  key: "process",
                  label: "过程流式输出",
                  children: <div className="raw-stream stream-log" style={{ minHeight: 160 }}>{streamText || "（规则生成与大模型分析流式输出）"}</div>,
                },
                {
                  key: "log",
                  label: "后台日志",
                  children: <div className="stream-log" style={{ minHeight: 160 }}>{convertLog || "（docs2md 与索引日志）"}</div>,
                },
              ]}
            />
          </Spin>
        </div>
      </Card>

      <Card title="结构化预览">
        {analysis?.blocks?.length ? (
          <>
            {analysis.title && <Typography.Title level={4}>{analysis.title}</Typography.Title>}
            <BlockRenderer blocks={analysis.blocks as Block[]} />
          </>
        ) : (
          <Text type="secondary">分析完成后在此展示卡片/表格/Tabs 等</Text>
        )}
      </Card>

      <Modal title="设置" open={settingsOpen} onOk={saveSettings} onCancel={() => setSettingsOpen(false)} width={860} okText="保存">
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <div>
            <Text strong>chunk 上限（全局）</Text>
            <div style={{ marginTop: 8 }}>
              <InputNumber
                min={1}
                max={500}
                value={settingsDraft.chunk_limit}
                onChange={(v) =>
                  setSettingsDraft((s) => ({ ...s, chunk_limit: Math.max(1, Math.min(500, Number(v) || 40)) }))
                }
              />
            </div>
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
                    options={TEXT_MODEL_OPTIONS.map((m) => ({ value: m, label: m }))}
                    onChange={(vals) =>
                      setSettingsDraft((s) => ({
                        ...s,
                        llm_settings: { ...s.llm_settings, text_model: String(vals?.[0] || "") || "qwen3" },
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
                  <Text type="secondary">
                    {settingsDraft.llm_settings?.has_text_api_key ? "文本 Key 已配置（不回显）" : "文本 Key 未配置"}
                  </Text>
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
                    options={VL_MODEL_OPTIONS.map((m) => ({ value: m, label: m }))}
                    onChange={(vals) =>
                      setSettingsDraft((s) => ({
                        ...s,
                        llm_settings: { ...s.llm_settings, vl_model: String(vals?.[0] || "") || "qwen3-vl-plus" },
                      }))
                    }
                  />
                  <Input
                    style={{ width: 360 }}
                    addonBefore="VL Base URL"
                    placeholder="可选，未填则沿用文本 Base URL/环境配置"
                    value={settingsDraft.llm_settings?.vl_base_url}
                    onChange={(e) =>
                      setSettingsDraft((s) => ({
                        ...s,
                        llm_settings: { ...s.llm_settings, vl_base_url: e.target.value },
                      }))
                    }
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
                  <Text type="secondary">
                    {settingsDraft.llm_settings?.has_vl_api_key ? "VL Key 已配置（不回显）" : "VL Key 未配置"}
                  </Text>
                </Space>
              </div>

              <Text type="secondary">Key 输入框只允许粘贴与删除，且不可查看/复制。</Text>
              <Text type="secondary">文本解析使用 Provider + Text Base URL + 文本模型 + 文本 Key；图片解析使用 VL 模型 + VL Key +（可选）VL Base URL。</Text>
            </Space>
          </div>
        </Space>
      </Modal>

      <Modal title="帮助" open={helpOpen} onCancel={() => setHelpOpen(false)} footer={null} width={760}>
        <Space direction="vertical" size={10}>
          <Text>1) 点击「选择项目」，系统会回填绝对路径并自动加载该项目。</Text>
          <Text>2) 在首页选择分析关注点（可多选）；若 rules.md 提供“组合使用建议”，会在下拉框后显示 Tips。</Text>
          <Text>3) 点击“开始分析”后，系统自动执行：规则生成 → docs2md 转换 → 索引 → 大模型分析。</Text>
          <Text>4) 设置页分为三部分：chunk 上限、关注点维护、Model（文本模型与 VL 模型分别配置 Key）。</Text>
          <Text>5) 可在设置页点击「加载 rules」导入完整规则文件，系统会先校验再确认保存。</Text>
        </Space>
      </Modal>
    </div>
  );
}
