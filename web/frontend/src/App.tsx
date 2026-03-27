import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Card, Divider, Input, InputNumber, message, Modal, Select, Space, Spin, Tabs, Typography } from "antd";
import { apiJson, openAnalyzeStream, openConvertStream, postRulesGenerateStream, waitAnalyzeStream, waitConvertStream } from "./api";
import { BlockRenderer, type Block } from "./BlockRenderer";

const { Text } = Typography;

type Project = { id: number; name: string; root_path: string };
type FocusPoint = { id: string; name: string; prompt: string };
type SettingsData = { focus_points: FocusPoint[]; chunk_limit: number };
type LayoutData = { mode: "single" | "multi"; root_label: string; candidates: { id: string; name: string; path: string }[]; warnings: string[] };

export default function App() {
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
  const [focusNote, setFocusNote] = useState("");
  const [focusDefs, setFocusDefs] = useState<FocusPoint[]>([]);
  const [layout, setLayout] = useState<LayoutData | null>(null);
  const [selectedCandidatePath, setSelectedCandidatePath] = useState<string | null>(null);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [outputTab, setOutputTab] = useState<string>("process");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [settingsDraft, setSettingsDraft] = useState<SettingsData>({ focus_points: [], chunk_limit: 40 });

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
    setSettingsDraft(data);
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
  const layoutFetchGen = useRef(0);

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
      const gen = ++layoutFetchGen.current;
      const data = await apiJson<LayoutData>("/api/v1/fs/detect-projects", {
        method: "POST",
        body: JSON.stringify({ root_path: rootPath }),
      });
      if (gen !== layoutFetchGen.current) return;
      setLayout(data);
      if (data.candidates.length === 0) {
        setSelectedCandidatePath(rootPath);
        await ensureProjectForPath(rootPath, data.root_label);
        return;
      }
      if (data.mode === "multi" && data.candidates.length > 1) {
        setSelectedCandidatePath(data.candidates[0].path);
        await ensureProjectForPath(data.candidates[0].path, data.candidates[0].name);
        return;
      }
      const single = data.candidates[0];
      setSelectedCandidatePath(single.path);
      await ensureProjectForPath(single.path, single.name || data.root_label);
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
        body: JSON.stringify(settingsDraft),
      });
      setChunkLimit(data.chunk_limit);
      setFocusDefs(data.focus_points);
      setSettingsOpen(false);
      message.success("设置已保存");
    } catch (e) {
      message.error(String((e as Error).message));
    }
  };

  const appendProcess = (s: string) => setStreamText((prev) => prev + s);
  const appendBackend = (s: string) => setConvertLog((prev) => prev + s);

  const runFullPipeline = async () => {
    if (selectedId == null) {
      message.warning("请先选择或创建项目");
      return;
    }
    if (focusPoints.length === 0 && !focusNote.trim()) {
      message.warning("请至少选择一个关注点或填写补充说明");
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
        { focus_points: focusPoints, focus_note: focusNote.trim() },
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
      message.error(String((e as Error).message));
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
          <Button shape="circle" onClick={() => setHelpOpen(true)} title="帮助">
            !
          </Button>
          <Button shape="circle" onClick={() => setSettingsOpen(true)} title="设置">
            ⚙
          </Button>
        </Space>
      </Space>
      <Text type="secondary">选择目录后自动加载项目并开始一键分析。</Text>
      <Divider />

      <Card title="项目选择" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: "100%" }} size={8}>
          <Space wrap>
            <Button type="primary" loading={pickLoading} disabled={!nativePickerAvailable} onClick={onPickDirectory}>
              选择目录并自动加载
            </Button>
            {pickedRootPath ? <Text code>{pickedRootPath}</Text> : <Text type="secondary">未选择目录</Text>}
          </Space>
          {layout && layout.mode === "multi" && (
            <Select
              style={{ minWidth: 460 }}
              placeholder="选择项目"
              value={selectedCandidatePath ?? undefined}
              options={layout.candidates.map((c) => ({ value: c.path, label: c.name }))}
              onChange={async (v) => {
                setSelectedCandidatePath(v);
                const hit = layout.candidates.find((c) => c.path === v);
                try {
                  await ensureProjectForPath(v, hit?.name || "project");
                } catch (e) {
                  message.error(String((e as Error).message));
                }
              }}
            />
          )}
          {layout && layout.mode === "single" && <Text>{`已识别项目：${layout.candidates[0]?.name || layout.root_label}`}</Text>}
          {layout?.warnings?.length ? <Alert type="warning" showIcon message={layout.warnings.join(" ")} /> : null}
          {selected ? (
            <Space wrap>
              <Text strong>{`${selected.name} (#${selected.id})`}</Text>
              <Text code>{selected.root_path}</Text>
            </Space>
          ) : (
            <Text type="secondary">请选择目录并自动加载项目</Text>
          )}
        </Space>
      </Card>

      <Card title="分析输入" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            mode="multiple"
            allowClear
            style={{ minWidth: 460 }}
            placeholder="选择分析关注点（可多选）"
            value={focusPoints}
            options={focusDefs.map((x) => ({ value: x.name, label: x.name }))}
            onChange={(v) => setFocusPoints(v as string[])}
          />
          <Input placeholder="补充关注点（可选）" style={{ width: 320 }} value={focusNote} onChange={(e) => setFocusNote(e.target.value)} />
        </Space>
      </Card>

      <Card title="一键分析（规则生成 → docs2md → 索引 → 大模型）" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Button type="primary" loading={pipelineRunning} onClick={runFullPipeline} disabled={selectedId == null}>
            开始分析
          </Button>
          <Button onClick={exportDocx} disabled={selectedId == null || !analysis}>
            导出 docx（epic-doc）
          </Button>
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
          <Text strong>关注点与对应 Prompt</Text>
          {settingsDraft.focus_points.map((fp, i) => (
            <Space key={`${fp.id}-${i}`} direction="vertical" style={{ width: "100%", border: "1px solid #f0f0f0", padding: 10, borderRadius: 8 }}>
              <Space wrap style={{ width: "100%" }}>
                <Input
                  placeholder="关注点名称"
                  style={{ width: 220 }}
                  value={fp.name}
                  onChange={(e) =>
                    setSettingsDraft((s) => {
                      const next = [...s.focus_points];
                      next[i] = { ...next[i], name: e.target.value };
                      return { ...s, focus_points: next };
                    })
                  }
                />
                <Button
                  danger
                  onClick={() =>
                    setSettingsDraft((s) => ({ ...s, focus_points: s.focus_points.filter((_, idx) => idx !== i) }))
                  }
                >
                  删除
                </Button>
              </Space>
              <Input.TextArea
                rows={3}
                placeholder="该关注点对应的提示词（prompt）"
                value={fp.prompt}
                onChange={(e) =>
                  setSettingsDraft((s) => {
                    const next = [...s.focus_points];
                    next[i] = { ...next[i], prompt: e.target.value };
                    return { ...s, focus_points: next };
                  })
                }
              />
            </Space>
          ))}
          <Button
            onClick={() =>
              setSettingsDraft((s) => ({
                ...s,
                focus_points: [...s.focus_points, { id: `custom-${Date.now()}`, name: "", prompt: "" }],
              }))
            }
          >
            新增关注点
          </Button>
        </Space>
      </Modal>

      <Modal title="帮助" open={helpOpen} onCancel={() => setHelpOpen(false)} footer={null} width={760}>
        <Space direction="vertical" size={10}>
          <Text>1) 点击「选择目录并自动加载」，系统会自动识别单项目/多项目结构。</Text>
          <Text>2) 在“分析输入”里选择关注点，可补充额外说明。</Text>
          <Text>3) 点击“开始分析”后，系统会自动执行：规则生成 → docs2md 转换 → 索引 → 大模型分析。</Text>
          <Text>4) 若未配置 VL API Key，转换日志会提示“跳过图片解析环节”。</Text>
          <Text>5) 齿轮设置里可维护关注点及对应 prompt，并修改 chunk 上限。</Text>
        </Space>
      </Modal>
    </div>
  );
}
