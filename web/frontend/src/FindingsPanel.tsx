import React, { useState } from "react";
import { Badge, Button, Collapse, Space, Tag, Tooltip, Typography, message } from "antd";
import {
  CheckCircleOutlined,
  EyeOutlined,
  FileTextOutlined,
  MinusCircleOutlined,
  PlusCircleOutlined,
} from "@ant-design/icons";

const { Text } = Typography;

export interface Finding {
  id: string;
  focus_id: string;
  title: string;
  severity: "high" | "medium" | "low";
  evidence: string;
  status: "open" | "acknowledged" | "resolved";
}

interface FindingsPanelProps {
  projectId: number | null;
  conversationId: number | null;
  findings: Finding[];
  onStatusChange: (findingId: string, status: Finding["status"]) => void;
  onGenerateReport: () => void;
  reportLoading: boolean;
  onAddToQueue?: (finding: Finding) => void;
}

const SEVERITY_COLOR: Record<string, string> = {
  high: "#ff4d4f",
  medium: "#faad14",
  low: "#52c41a",
};
const SEVERITY_LABEL: Record<string, string> = { high: "高", medium: "中", low: "低" };
const STATUS_LABEL: Record<string, string> = {
  open: "待处理",
  acknowledged: "已知悉",
  resolved: "已解决",
};

export const FindingsPanel: React.FC<FindingsPanelProps> = ({
  findings,
  onStatusChange,
  onGenerateReport,
  reportLoading,
  onAddToQueue,
}) => {
  const [collapsed, setCollapsed] = useState(false);

  const openCount = findings.filter((f) => f.status === "open").length;
  const highCount = findings.filter((f) => f.severity === "high" && f.status !== "resolved").length;

  if (!findings.length) return null;

  return (
    <div
      style={{
        border: "1px solid #d9d9d9",
        borderRadius: 8,
        marginTop: 12,
        background: "#fafafa",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 12px",
          background: "#f0f0f0",
          cursor: "pointer",
          borderBottom: collapsed ? "none" : "1px solid #d9d9d9",
        }}
        onClick={() => setCollapsed((c) => !c)}
      >
        <Space size={8}>
          <Text strong style={{ fontSize: 13 }}>
            审查发现
          </Text>
          <Badge count={openCount} style={{ backgroundColor: openCount > 0 ? "#ff4d4f" : "#52c41a" }} />
          {highCount > 0 && (
            <Tag color="red" style={{ fontSize: 11 }}>
              {highCount} 高风险
            </Tag>
          )}
        </Space>
        <Space size={8}>
          <Button
            size="small"
            type="primary"
            icon={<FileTextOutlined />}
            loading={reportLoading}
            onClick={(e) => {
              e.stopPropagation();
              onGenerateReport();
            }}
          >
            生成报告
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {collapsed ? "展开" : "收起"}
          </Text>
        </Space>
      </div>

      {/* Findings list */}
      {!collapsed && (
        <div style={{ maxHeight: 320, overflowY: "auto", padding: "4px 0" }}>
          {findings.map((f) => (
            <div
              key={f.id}
              style={{
                padding: "6px 12px",
                borderBottom: "1px solid #f0f0f0",
                display: "flex",
                alignItems: "flex-start",
                gap: 8,
                opacity: f.status === "resolved" ? 0.45 : 1,
              }}
            >
              {/* Severity badge */}
              <div
                style={{
                  width: 4,
                  minHeight: 36,
                  borderRadius: 2,
                  background: SEVERITY_COLOR[f.severity] ?? "#d9d9d9",
                  flexShrink: 0,
                  marginTop: 4,
                }}
              />
              {/* Content */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <Text
                    style={{
                      fontSize: 12,
                      color: SEVERITY_COLOR[f.severity],
                      fontWeight: 600,
                      flexShrink: 0,
                    }}
                  >
                    {SEVERITY_LABEL[f.severity] ?? f.severity}
                  </Text>
                  <Tag style={{ fontSize: 11, padding: "0 4px", margin: 0 }} color="default">
                    {f.focus_id}
                  </Tag>
                  <Text style={{ fontSize: 13 }}>{f.title}</Text>
                </div>
                {f.evidence && (
                  <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 2 }}>
                    {f.evidence}
                  </Text>
                )}
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {f.id} · {STATUS_LABEL[f.status] ?? f.status}
                </Text>
              </div>
              {/* Status actions */}
              <Space size={4} style={{ flexShrink: 0 }}>
                {onAddToQueue && f.status !== "resolved" && (
                  <Tooltip title="加入知识线索">
                    <Button
                      size="small"
                      type="text"
                      icon={<PlusCircleOutlined style={{ color: "#1677ff" }} />}
                      onClick={() => onAddToQueue(f)}
                    />
                  </Tooltip>
                )}
                {f.status === "open" && (
                  <Tooltip title="标记为已知悉">
                    <Button
                      size="small"
                      type="text"
                      icon={<EyeOutlined />}
                      onClick={() => onStatusChange(f.id, "acknowledged")}
                    />
                  </Tooltip>
                )}
                {f.status !== "resolved" && (
                  <Tooltip title="标记为已解决">
                    <Button
                      size="small"
                      type="text"
                      icon={<CheckCircleOutlined style={{ color: "#52c41a" }} />}
                      onClick={() => onStatusChange(f.id, "resolved")}
                    />
                  </Tooltip>
                )}
                {f.status !== "open" && (
                  <Tooltip title="重新打开">
                    <Button
                      size="small"
                      type="text"
                      icon={<MinusCircleOutlined />}
                      onClick={() => onStatusChange(f.id, "open")}
                    />
                  </Tooltip>
                )}
              </Space>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
