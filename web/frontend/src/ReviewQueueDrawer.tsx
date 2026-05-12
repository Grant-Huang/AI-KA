import React, { useCallback, useEffect, useState } from "react";
import { Badge, Button, Drawer, Empty, Space, Spin, Table, Tag, Tooltip } from "antd";
import { DeleteOutlined, ReloadOutlined } from "@ant-design/icons";
import type { ReviewQueueItem } from "./api";
import { deleteReviewQueueItem, getReviewQueue, patchReviewQueueItem } from "./api";

// Derive trust level from source role — backend trust field not yet exposed
function trustFromRole(role: string): "high" | "medium" | "low" {
  if (role === "senior_expert") return "medium";
  return "low";
}

const TRUST_COLOR = { high: "green", medium: "blue", low: "default" } as const;
const TRUST_LABEL = { high: "高信任", medium: "中信任", low: "低信任" } as const;

const STATUS_COLOR: Record<string, string> = {
  pending_review: "default", in_review: "processing",
  approved: "success", rejected: "error", archived: "warning",
};
const STATUS_LABEL: Record<string, string> = {
  pending_review: "待审查", in_review: "审查中",
  approved: "已批准", rejected: "已拒绝", archived: "已归档",
};

export function ReviewQueueDrawer({
  open,
  onClose,
  onStartExtraction,
}: {
  open: boolean;
  onClose: () => void;
  onStartExtraction: (item: ReviewQueueItem) => void;
}) {
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { items: data } = await getReviewQueue();
      setItems(data);
    } catch { /* silent on load error */ } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const handleArchive = async (id: string, current: string) => {
    try {
      await patchReviewQueueItem(id, { status: current === "archived" ? "pending_review" : "archived" });
      void load();
    } catch { /* silent */ }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteReviewQueueItem(id);
      setItems((prev) => prev.filter((x) => x.id !== id));
    } catch { /* silent */ }
  };

  const pendingCount = items.filter(
    (x) => x.status === "pending_review" || x.status === "in_review",
  ).length;

  const columns = [
    {
      title: "信任",
      width: 80,
      render: (_: unknown, row: ReviewQueueItem) => {
        const t = trustFromRole(row.source_role);
        return (
          <Tooltip title={`来源角色：${row.source_role}`}>
            <Tag color={TRUST_COLOR[t]} style={{ fontSize: 11 }}>{TRUST_LABEL[t]}</Tag>
          </Tooltip>
        );
      },
    },
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
      render: (v: string) => (
        <Tooltip title={<div style={{ maxWidth: 360, whiteSpace: "pre-wrap" }}>{v}</div>} placement="left">
          <span style={{ color: "#444", fontSize: 13, cursor: "default" }}>{v}</span>
        </Tooltip>
      ),
    },
    {
      title: "×",
      dataIndex: "occurrences",
      width: 48,
      align: "center" as const,
      render: (v: number) => (
        <Badge count={v} color={v >= 3 ? "red" : v >= 2 ? "orange" : "blue"} showZero />
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 80,
      render: (v: string) => (
        <Tag color={STATUS_COLOR[v] || "default"}>{STATUS_LABEL[v] || v}</Tag>
      ),
    },
    {
      title: "操作",
      width: 170,
      render: (_: unknown, row: ReviewQueueItem) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            disabled={row.status === "approved" || row.status === "rejected"}
            onClick={() => {
              onStartExtraction(row);
              onClose();
            }}
          >
            开始提取
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => void handleArchive(row.id, row.status)}
          >
            {row.status === "archived" ? "恢复" : "归档"}
          </Button>
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => void handleDelete(row.id)}
          />
        </Space>
      ),
    },
  ];

  return (
    <Drawer
      title={
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span>审查队列</span>
          {pendingCount > 0 && <Badge count={pendingCount} color="orange" />}
          <Button
            icon={<ReloadOutlined />}
            size="small"
            onClick={load}
            loading={loading}
            style={{ marginLeft: "auto" }}
          >
            刷新
          </Button>
        </div>
      }
      open={open}
      onClose={onClose}
      width={760}
      styles={{ body: { padding: "12px 16px" } }}
    >
      <div style={{ marginBottom: 10, fontSize: 12, color: "#888" }}>
        按出现次数降序 · 高 Trust 线索来自资深顾问审查（更可靠）· 低 Trust 需多条合并后才提升为提取候选
      </div>
      {loading && items.length === 0 ? (
        <div style={{ textAlign: "center", padding: 40 }}><Spin /></div>
      ) : items.length === 0 ? (
        <Empty
          description="暂无队列条目。完成一次项目审查后，LLM 会自动提取泛化知识线索。"
          style={{ padding: "40px 0" }}
        />
      ) : (
        <Table
          dataSource={items}
          columns={columns}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ pageSize: 25, showSizeChanger: false }}
        />
      )}
    </Drawer>
  );
}

/** Hook: returns count of pending_review + in_review items for badge display */
export function useReviewQueueCount(): number {
  const [count, setCount] = useState(0);
  useEffect(() => {
    getReviewQueue()
      .then(({ items }) => {
        setCount(
          items.filter((x) => x.status === "pending_review" || x.status === "in_review").length,
        );
      })
      .catch(() => {});
  }, []);
  return count;
}
