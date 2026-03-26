import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Divider,
  Form,
  Input,
  InputNumber,
  message,
  Select,
  Space,
  Typography,
} from "antd";
import { apiJson, openAnalyzeStream, openConvertStream } from "./api";
import { BlockRenderer, type Block } from "./BlockRenderer";

const { Text } = Typography;

type Project = { id: number; name: string; root_path: string };

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
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [convertLog, setConvertLog] = useState("");
  const [streamText, setStreamText] = useState("");
  const [analysis, setAnalysis] = useState<{ title?: string; blocks?: Block[] } | null>(null);
  const [rulesText, setRulesText] = useState(defaultRulesText);
  const [chunkLimit, setChunkLimit] = useState(40);

  const loadProjects = useCallback(async () => {
    const data = await apiJson<{ projects: Project[] }>("/api/v1/projects");
    setProjects(data.projects || []);
    if (data.projects?.length && selectedId == null) {
      setSelectedId(data.projects[0].id);
    }
  }, [selectedId]);

  useEffect(() => {
    loadProjects().catch((e) => message.error(String(e.message)));
  }, [loadProjects]);

  const selected = useMemo(
    () => projects.find((p) => p.id === selectedId) || null,
    [projects, selectedId],
  );

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

  const onSaveRules = async () => {
    if (selectedId == null) return;
    let rules: object;
    try {
      rules = JSON.parse(rulesText) as object;
    } catch {
      message.error("规则 JSON 无效");
      return;
    }
    try {
      await apiJson("/api/v1/projects/" + selectedId + "/rules", {
        method: "POST",
        body: JSON.stringify({ rules }),
      });
      message.success("规则已保存");
    } catch (e) {
      message.error(String((e as Error).message));
    }
  };

  const runConvert = () => {
    if (selectedId == null) return;
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

  const runIndex = async () => {
    if (selectedId == null) return;
    try {
      const data = await apiJson<{ indexed_documents: number }>(
        "/api/v1/projects/" + selectedId + "/index-md",
        { method: "POST" },
      );
      message.success(`已索引 ${data.indexed_documents} 个文档`);
    } catch (e) {
      message.error(String((e as Error).message));
    }
  };

  const runAnalyze = () => {
    if (selectedId == null) return;
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
      const data = await apiJson<{ download_path: string }>(
        "/api/v1/projects/" + selectedId + "/export/docx",
        {
          method: "POST",
          body: JSON.stringify({
            analysis,
            title: analysis.title || "项目分析",
            theme: "tech",
          }),
        },
      );
      window.open(data.download_path, "_blank");
      message.success("已开始下载");
    } catch (e) {
      message.error(String((e as Error).message));
    }
  };

  return (
    <div className="app-shell">
      <Typography.Title level={2}>AI-KA ProjectLens</Typography.Title>
      <Text type="secondary">本机后端 + 浏览器：请填写服务器可访问的项目绝对路径；需配置 DOCS2MD_ROOT 与 LLM 环境变量。</Text>
      <Divider />

      <Card title="新建项目" style={{ marginBottom: 16 }}>
        <Form layout="inline" onFinish={onCreate}>
          <Form.Item name="name" rules={[{ required: true }]}>
            <Input placeholder="项目名称" style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="root_path" rules={[{ required: true }]}>
            <Input placeholder="绝对路径，如 D:/workspace/myproject" style={{ width: 420 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              创建
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Card title="当前项目" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            style={{ minWidth: 280 }}
            placeholder="选择项目"
            value={selectedId ?? undefined}
            options={projects.map((p) => ({ value: p.id, label: `${p.name} (#${p.id})` }))}
            onChange={(v) => setSelectedId(v as number)}
          />
          {selected && <Text code>{selected.root_path}</Text>}
        </Space>
      </Card>

      <Card title="1. docs2md 转换（SSE 日志）" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Button onClick={runConvert} disabled={selectedId == null}>
            开始转换
          </Button>
          <Button onClick={runIndex} disabled={selectedId == null}>
            索引 Markdown
          </Button>
        </Space>
        <div className="stream-log" style={{ marginTop: 12 }}>
          {convertLog || "（转换日志）"}
        </div>
      </Card>

      <Card title="2. 分析规则（JSON）" style={{ marginBottom: 16 }}>
        <Input.TextArea rows={10} value={rulesText} onChange={(e) => setRulesText(e.target.value)} />
        <Button style={{ marginTop: 8 }} onClick={onSaveRules} disabled={selectedId == null}>
          保存规则
        </Button>
      </Card>

      <Card title="3. 大模型分析（流式）" style={{ marginBottom: 16 }}>
        <Space align="center" style={{ marginBottom: 8 }}>
          <Text>chunk 数量上限</Text>
          <InputNumber min={1} max={500} value={chunkLimit} onChange={(v) => setChunkLimit(Number(v) || 40)} />
          <Button type="primary" onClick={runAnalyze} disabled={selectedId == null}>
            开始分析
          </Button>
          <Button onClick={exportDocx} disabled={selectedId == null || !analysis}>
            导出 docx（epic-doc）
          </Button>
        </Space>
        <div className="raw-stream stream-log">{streamText || "（流式原文）"}</div>
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
    </div>
  );
}
