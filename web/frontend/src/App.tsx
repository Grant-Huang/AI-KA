import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Divider,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Select,
  Space,
  Spin,
  Tabs,
  Tooltip,
  Typography,
} from "antd";
import {
  apiJson,
  openAnalyzeStream,
  openConvertStream,
  postRulesGenerateStream,
  waitAnalyzeStream,
  waitConvertStream,
} from "./api";
import { BlockRenderer, type Block } from "./BlockRenderer";

const { Text } = Typography;

type Project = { id: number; name: string; root_path: string };
type RulesObj = { goal?: string; dimensions?: string[]; style?: { prefer?: string[] } };

type LayoutData = {
  mode: "single" | "multi";
  root_label: string;
  candidates: { id: string; name: string; path: string }[];
  warnings: string[];
};

const focusOptions = ["需求", "风险", "接口与集成", "范围蔓延", "进度", "质量", "验收", "数据一致性"];

const defaultRulesText = JSON.stringify(
  {
    goal: "基于转换后的 Markdown 做项目风险与需求梳理",
    dimensions: ["需求", "风险", "接口与集成"],
    style: { prefer: ["cards", "table", "tabs"] },
  },
  null,
  2,
);

export default function App() {
  const [form] = Form.useForm<{ name: string; root_path: string }>();
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [convertLog, setConvertLog] = useState("");
  const [streamText, setStreamText] = useState("");
  const [analysis, setAnalysis] = useState<{ title?: string; blocks?: Block[] } | null>(null);
  const [rulesText, setRulesText] = useState(defaultRulesText);
  const [chunkLimit, setChunkLimit] = useState(40);
  const [nativePickerAvailable, setNativePickerAvailable] = useState(true);
  const [pickLoading, setPickLoading] = useState(false);
  const [focusPoints, setFocusPoints] = useState<string[]>([]);
  const [focusNote, setFocusNote] = useState("");
  const [layout, setLayout] = useState<LayoutData | null>(null);
  const [selectedCandidatePath, setSelectedCandidatePath] = useState<string | null>(null);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [outputTab, setOutputTab] = useState<string>("process");
  const [rulesModalOpen, setRulesModalOpen] = useState(false);

  const loadProjects = useCallback(async () => {
    const data = await apiJson<{ projects: Project[] }>("/api/v1/projects");
    setProjects(data.projects || []);
    setSelectedId((prev) => {
      if (data.projects?.length && prev == null) {
        return data.projects[0].id;
      }
      return prev;
    });
  }, []);

  useEffect(() => {
    loadProjects().catch((e) => message.error(String(e.message)));
  }, [loadProjects]);

  useEffect(() => {
    apiJson<{ native_folder_picker: boolean }>("/api/v1/fs/capabilities")
      .then((d) => setNativePickerAvailable(!!d.native_folder_picker))
      .catch(() => setNativePickerAvailable(false));
  }, []);

  const selected = useMemo(
    () => projects.find((p) => p.id === selectedId) || null,
    [projects, selectedId],
  );

  const layoutFetchGen = useRef(0);

  useEffect(() => {
    setSelectedCandidatePath(null);
  }, [selectedId]);

  useEffect(() => {
    if (!selected) {
      setLayout(null);
      setSelectedCandidatePath(null);
      return;
    }
    const gen = ++layoutFetchGen.current;
    const rootPath = selected.root_path;
    apiJson<LayoutData>("/api/v1/fs/detect-projects", {
      method: "POST",
      body: JSON.stringify({ root_path: rootPath }),
    })
      .then((data) => {
        if (gen !== layoutFetchGen.current) {
          return;
        }
        setLayout(data);
        if (data.mode === "multi" && data.candidates.length) {
          const match = data.candidates.find((c) => c.path === rootPath);
          setSelectedCandidatePath(match ? match.path : data.candidates[0].path);
        } else if (data.candidates.length) {
          setSelectedCandidatePath(data.candidates[0].path);
        } else {
          setSelectedCandidatePath(rootPath);
        }
      })
      .catch((e) => {
        if (gen !== layoutFetchGen.current) {
          return;
        }
        message.error(String(e.message));
        setLayout(null);
      });
  }, [selected?.id, selected?.root_path]);

  useEffect(() => {
    if (!selectedId || !selected || selectedCandidatePath == null) {
      return;
    }
    if (selected.root_path === selectedCandidatePath) {
      return;
    }
    apiJson(`/api/v1/projects/${selectedId}`, {
      method: "PATCH",
      body: JSON.stringify({ root_path: selectedCandidatePath }),
    })
      .then(() => loadProjects())
      .catch((e) => message.error(String(e.message)));
  }, [selectedCandidatePath, selectedId, selected, loadProjects]);

  const onCreate = async (v: { name: string; root_path: string }) => {
    try {
      const data = await apiJson<{ id: number }>("/api/v1/projects", {
        method: "POST",
        body: JSON.stringify({ name: v.name, root_path: v.root_path }),
      });
      message.success("项目已创建");
      await loadProjects();
      setSelectedId(data.id);
    } catch (e) {
      message.error(String((e as Error).message));
    }
  };

  const onPickDirectory = async () => {
    setPickLoading(true);
    try {
      const data = await apiJson<{ path: string }>("/api/v1/fs/pick-directory", { method: "POST" });
      form.setFieldValue("root_path", data.path);
      message.success("已选择目录");
    } catch (e) {
      message.error(String((e as Error).message));
    } finally {
      setPickLoading(false);
    }
  };

  const onSaveRulesFromModal = async () => {
    if (selectedId == null) {
      return;
    }
    let rules: object;
    try {
      rules = JSON.parse(rulesText) as object;
    } catch {
      message.error("规则 JSON 无效");
      return;
    }
    try {
      await apiJson(`/api/v1/projects/${selectedId}/rules`, {
        method: "POST",
        body: JSON.stringify({ rules }),
      });
      message.success("规则已保存");
      setRulesModalOpen(false);
    } catch (e) {
      message.error(String((e as Error).message));
    }
  };

  const appendProcess = (s: string) => {
    setStreamText((prev) => prev + s);
  };

  const appendBackend = (s: string) => {
    setConvertLog((prev) => prev + s);
  };

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
        {
          focus_points: focusPoints,
          focus_note: focusNote.trim(),
        },
        (ev) => {
          if (ev.type === "delta" && typeof ev.text === "string") {
            appendProcess(ev.text);
          }
          if (ev.type === "final" && ev.rules && typeof ev.rules === "object") {
            setRulesText(JSON.stringify(ev.rules, null, 2));
            appendProcess("\n【规则生成】已完成并保存。\n");
          }
        },
      );

      appendBackend("【docs2md】开始转换…\n");
      setOutputTab("log");
      await waitConvertStream(selectedId, (line) => appendBackend(line));
      appendBackend("【docs2md】转换完成。\n");

      appendBackend("【索引】正在将 Markdown 写入索引与分块…\n");
      const idx = await apiJson<{ indexed_documents: number }>(`/api/v1/projects/${selectedId}/index-md`, {
        method: "POST",
      });
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

  const runConvertOnly = () => {
    if (selectedId == null) {
      return;
    }
    setConvertLog("");
    const stop = openConvertStream(
      selectedId,
      (ev) => {
        if (ev.type === "log" && typeof ev.text === "string") {
          setConvertLog((s) => s + ev.text + "\n");
        }
        if (ev.type === "complete") {
          message.success("转换完成");
        }
        if (ev.type === "error") {
          message.error(String(ev.message));
        }
      },
      (e) => message.error(e.message),
    );
    setTimeout(stop, 600_000);
  };

  const runIndexOnly = async () => {
    if (selectedId == null) {
      return;
    }
    try {
      const data = await apiJson<{ indexed_documents: number }>(`/api/v1/projects/${selectedId}/index-md`, {
        method: "POST",
      });
      message.success(`已索引 ${data.indexed_documents} 个文档`);
    } catch (e) {
      message.error(String((e as Error).message));
    }
  };

  const runAnalyzeOnly = () => {
    if (selectedId == null) {
      return;
    }
    setStreamText("");
    setAnalysis(null);
    const stop = openAnalyzeStream(
      selectedId,
      chunkLimit,
      (ev) => {
        if (ev.type === "delta" && typeof ev.text === "string") {
          setStreamText((s) => s + ev.text);
        }
        if (ev.type === "final") {
          if (ev.analysis && typeof ev.analysis === "object") {
            setAnalysis(ev.analysis as { title?: string; blocks?: Block[] });
          } else if (typeof ev.raw === "string") {
            setStreamText(ev.raw);
            message.warning("模型输出非 JSON，已显示原文");
          }
        }
        if (ev.type === "error") {
          message.error(String(ev.message));
        }
      },
      (e) => message.error(e.message),
    );
    setTimeout(stop, 600_000);
  };

  const exportDocx = async () => {
    if (selectedId == null || !analysis) {
      message.warning("请先完成分析");
      return;
    }
    try {
      const data = await apiJson<{ download_path: string }>(`/api/v1/projects/${selectedId}/export/docx`, {
        method: "POST",
        body: JSON.stringify({
          analysis,
          title: analysis.title || "项目分析",
          theme: "tech",
        }),
      });
      window.open(data.download_path, "_blank");
      message.success("已开始下载");
    } catch (e) {
      message.error(String((e as Error).message));
    }
  };

  return (
    <div className="app-shell">
      <Typography.Title level={2}>AI-KA ProjectLens</Typography.Title>
      <Text type="secondary">
        本机后端 + 浏览器：项目根目录须为后端进程可读的绝对路径；点击「选择目录」由本机后端弹出系统文件夹对话框并回填路径。需配置 DOCS2MD_ROOT 与 LLM 环境变量。
      </Text>
      <Divider />

      <Card title="分析配置" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Space wrap align="center">
            <Tooltip
              title="参与大模型分析的 Markdown 分块数量上限。数值越大，纳入的文档片段越多，上下文更全，但耗时与费用通常更高。"
              placement="topLeft"
            >
              <Text strong>chunk 数量上限</Text>
            </Tooltip>
            <InputNumber min={1} max={500} value={chunkLimit} onChange={(v) => setChunkLimit(Number(v) || 40)} />
          </Space>
          <Space wrap>
            <Select
              mode="multiple"
              allowClear
              style={{ minWidth: 420 }}
              placeholder="选择分析关注点（可多选）"
              value={focusPoints}
              options={focusOptions.map((x) => ({ value: x, label: x }))}
              onChange={(v) => setFocusPoints(v as string[])}
            />
            <Input
              placeholder="补充关注点（可选）"
              style={{ width: 320 }}
              value={focusNote}
              onChange={(e) => setFocusNote(e.target.value)}
            />
            <Button onClick={() => setRulesModalOpen(true)} disabled={selectedId == null}>
              编辑分析规则（JSON）
            </Button>
          </Space>
          <Collapse
            items={[
              {
                key: "help",
                label: "环境变量与帮助（LLM / docs2md / 索引说明）",
                children: (
                  <Space direction="vertical">
                    <Text>
                      配置 LLM：设置环境变量
                      <Text code>AIKA_LLM_PROVIDER</Text>（如 <Text code>openai_compatible</Text> 或{" "}
                      <Text code>mock</Text>）、<Text code>AIKA_LLM_BASE_URL</Text>、<Text code>AIKA_LLM_API_KEY</Text>
                      、<Text code>AIKA_LLM_MODEL</Text> 等，详见仓库 README。
                    </Text>
                    <Text>
                      docs2md：可选设置 <Text code>DOCS2MD_ROOT</Text> 指向本地 docs2md 仓库；否则使用已安装的{" "}
                      <Text code>docs2md</Text> 包。
                    </Text>
                    <Text>
                      「索引 Markdown」步骤：把 docs2md 转换产物目录下的 Markdown 扫描入库并分块，供后续大模型分析使用。一键流程中会在转换完成后自动执行，无需单独点击。
                    </Text>
                  </Space>
                ),
              },
            ]}
          />
        </Space>
      </Card>

      <Card title="新建项目" style={{ marginBottom: 16 }}>
        <Form form={form} layout="inline" onFinish={onCreate}>
          <Form.Item name="name" rules={[{ required: true }]}>
            <Input placeholder="项目名称" style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="root_path" rules={[{ required: true }]}>
            <Input
              placeholder="绝对路径，如 D:/workspace/myproject"
              style={{ width: 420 }}
              addonAfter={
                <Button
                  type="link"
                  size="small"
                  loading={pickLoading}
                  disabled={!nativePickerAvailable}
                  onClick={onPickDirectory}
                >
                  选择目录
                </Button>
              }
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              创建
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Card title="当前项目" style={{ marginBottom: 16 }}>
        <Space wrap align="start">
          <Select
            style={{ minWidth: 280 }}
            placeholder="选择项目"
            value={selectedId ?? undefined}
            options={projects.map((p) => ({ value: p.id, label: `${p.name} (#${p.id})` }))}
            onChange={(v) => setSelectedId(v as number)}
          />
          {selected && <Text code>{selected.root_path}</Text>}
        </Space>
        {layout && layout.mode === "multi" && layout.candidates.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <Alert
              type="info"
              showIcon
              message="检测到多子项目：请选择本次要分析的一个项目（一次只分析一个）"
              style={{ marginBottom: 8 }}
            />
            <Select
              style={{ minWidth: 400 }}
              placeholder="选择子项目目录"
              value={selectedCandidatePath ?? undefined}
              options={layout.candidates.map((c) => ({ value: c.path, label: `${c.name} → ${c.path}` }))}
              onChange={(v) => setSelectedCandidatePath(v)}
            />
          </div>
        )}
        {layout?.warnings?.length ? (
          <Alert type="warning" showIcon message={layout.warnings.join(" ")} style={{ marginTop: 8 }} />
        ) : null}
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
                  children: (
                    <div className="raw-stream stream-log" style={{ minHeight: 160 }}>
                      {streamText || "（规则生成与大模型分析流式输出）"}
                    </div>
                  ),
                },
                {
                  key: "log",
                  label: "后台日志",
                  children: (
                    <div className="stream-log" style={{ minHeight: 160 }}>
                      {convertLog || "（docs2md 与索引日志）"}
                    </div>
                  ),
                },
              ]}
            />
          </Spin>
        </div>
        <Collapse
          style={{ marginTop: 12 }}
          items={[
            {
              key: "adv",
              label: "高级：分步执行（排障）",
              children: (
                <Space wrap>
                  <Button onClick={runConvertOnly} disabled={selectedId == null}>
                    仅 docs2md 转换
                  </Button>
                  <Button onClick={runIndexOnly} disabled={selectedId == null}>
                    仅索引 Markdown
                  </Button>
                  <Button onClick={runAnalyzeOnly} disabled={selectedId == null}>
                    仅大模型分析
                  </Button>
                </Space>
              ),
            },
          ]}
        />
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

      <Modal
        title="编辑分析规则（JSON）"
        open={rulesModalOpen}
        onOk={onSaveRulesFromModal}
        onCancel={() => setRulesModalOpen(false)}
        width={720}
        okText="保存"
      >
        <Input.TextArea rows={14} value={rulesText} onChange={(e) => setRulesText(e.target.value)} />
      </Modal>
    </div>
  );
}
