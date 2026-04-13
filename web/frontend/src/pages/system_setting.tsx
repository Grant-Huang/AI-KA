import { Button, Space, Typography } from "antd";
import { ReactNode } from "react";

const { Title, Text } = Typography;

export default function SystemSettingPage(props: {
  content: ReactNode;
  onSave: () => void;
  onClose: () => void;
  saving?: boolean;
}) {
  return (
    <div className="standalone-page">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            设置
          </Title>
          <Text type="secondary">保存后会提示成功/失败，不会自动关闭页面。</Text>
        </div>
        <Space wrap>
          <Button type="primary" onClick={props.onSave} loading={!!props.saving}>
            保存
          </Button>
          <Button onClick={props.onClose}>关闭</Button>
        </Space>
      </div>
      <div style={{ marginTop: 14 }}>{props.content}</div>
    </div>
  );
}

