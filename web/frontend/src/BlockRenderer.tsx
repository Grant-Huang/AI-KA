import React from "react";
import { Alert, Card, Col, Row, Table, Tabs, Tag, Typography } from "antd";

const { Title, Paragraph, Text } = Typography;

export type Block = Record<string, unknown>;

function renderBlock(b: Block, key: string): React.ReactNode {
  const t = String(b.type || "").toLowerCase();
  if (t === "heading") {
    const level = Number(b.level) || 2;
    return (
      <Title key={key} level={level <= 4 ? (level as 1 | 2 | 3 | 4 | 5) : 3}>
        {String(b.text || "")}
      </Title>
    );
  }
  if (t === "paragraph") {
    return (
      <Paragraph key={key} style={{ whiteSpace: "pre-wrap" }}>
        {String(b.text || "")}
      </Paragraph>
    );
  }
  if (t === "tags") {
    const items = Array.isArray(b.items) ? b.items : [];
    return (
      <div key={key} style={{ marginBottom: 12 }}>
        {(items as unknown[]).map((x, i) => (
          <Tag key={i}>{String(x)}</Tag>
        ))}
      </div>
    );
  }
  if (t === "table") {
    const headers = Array.isArray(b.headers) ? (b.headers as unknown[]).map(String) : [];
    const rows = Array.isArray(b.rows) ? (b.rows as unknown[][]) : [];
    const cols = headers.map((h, i) => ({
      title: h,
      dataIndex: i,
      key: String(i),
      render: (v: unknown) => <Text>{String(v ?? "")}</Text>,
    }));
    const dataSource = rows.map((r, idx) => {
      const rec: Record<string, unknown> = { key: idx };
      r.forEach((cell, j) => {
        rec[j] = cell;
      });
      return rec;
    });
    return <Table key={key} size="small" pagination={false} columns={cols} dataSource={dataSource} style={{ marginBottom: 16 }} />;
  }
  if (t === "cards") {
    const items = Array.isArray(b.items) ? (b.items as Block[]) : [];
    return (
      <Row key={key} gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {items.map((it, i) => (
          <Col xs={24} md={12} key={i}>
            <Card title={String(it.title || "")} size="small">
              <Paragraph style={{ marginBottom: 8 }}>{String(it.body || "")}</Paragraph>
              {Array.isArray(it.tags) &&
                (it.tags as unknown[]).map((tg, j) => <Tag key={j}>{String(tg)}</Tag>)}
            </Card>
          </Col>
        ))}
      </Row>
    );
  }
  if (t === "tabs") {
    const items = Array.isArray(b.items) ? (b.items as { tab?: string; blocks?: Block[] }[]) : [];
    return (
      <Tabs
        key={key}
        style={{ marginBottom: 16 }}
        items={items.map((it, i) => ({
          key: String(i),
          label: String(it.tab || `Tab ${i + 1}`),
          children: (
            <div>{(it.blocks || []).map((inner, j) => renderBlock(inner, `${key}-${i}-${j}`))}</div>
          ),
        }))}
      />
    );
  }
  if (t === "callout") {
    const style = String(b.style || "info") as "success" | "info" | "warning" | "error";
    const map: Record<string, "success" | "info" | "warning" | "error"> = {
      success: "success",
      info: "info",
      warning: "warning",
      danger: "error",
    };
    return (
      <Alert
        key={key}
        type={map[style] || "info"}
        message={b.title ? String(b.title) : undefined}
        description={String(b.text || "")}
        style={{ marginBottom: 16 }}
        showIcon
      />
    );
  }
  return (
    <Paragraph key={key} type="secondary">
      {JSON.stringify(b)}
    </Paragraph>
  );
}

export function BlockRenderer(props: { blocks: Block[] }) {
  return (
    <div>
      {props.blocks.map((b, i) => renderBlock(b, `b-${i}`))}
    </div>
  );
}
