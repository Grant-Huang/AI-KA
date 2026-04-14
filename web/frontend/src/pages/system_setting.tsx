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
    <div className="settings-page">
      <header className="settings-page__header">
        <div className="settings-page__header-text">
          <Title level={3} className="settings-page__title">
            设置
          </Title>
          <Text type="secondary" className="settings-page__subtitle">
            文档、审查域与模型配置与主窗口内设置一致。保存后会提示成功或失败，不会自动关闭页面。
          </Text>
        </div>
        <Space wrap className="settings-page__actions">
          <Button type="primary" onClick={props.onSave} loading={!!props.saving}>
            保存
          </Button>
          <Button onClick={props.onClose}>关闭</Button>
        </Space>
      </header>
      <main className="settings-page__body">{props.content}</main>
    </div>
  );
}

