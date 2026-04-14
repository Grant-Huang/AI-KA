import { Button, Space, Spin, Tabs, Typography } from "antd";
import { useMemo } from "react";

import SimpleMarkdown from "../SimpleMarkdown";
import { parseHelpmeMarkdown } from "../helpTabs";

const { Title, Text } = Typography;

export default function HelpPage(props: {
  loading: boolean;
  markdown: string;
  onClose: () => void;
  /** 在 Modal 内使用：仅内容卡片，不渲染顶栏（标题由 Modal 提供） */
  compact?: boolean;
}) {
  const parsed = useMemo(() => parseHelpmeMarkdown(props.markdown), [props.markdown]);

  const inner =
    props.loading ? (
      <div className="help-page__loading">
        <Spin />
      </div>
    ) : parsed.ok ? (
      <div className="help-tabs-shell">
        <Tabs
          size="small"
          className="help-modal-tabs"
          items={parsed.tabs.map((t) => ({
            key: t.label,
            label: t.label,
            children: (
              <div className="help-tab-body">
                <SimpleMarkdown markdown={t.content} />
              </div>
            ),
          }))}
        />
      </div>
    ) : (
      <div className="help-tabs-shell help-tabs-shell--fallback">
        <div className="help-tab-body">
          <SimpleMarkdown markdown={parsed.markdown || "# 帮助\n\n暂无帮助内容。"} />
        </div>
      </div>
    );

  if (props.compact) {
    return <div className="help-page__body help-page__body--compact">{inner}</div>;
  }

  return (
    <div className="help-page help-page--standalone">
      <header className="help-page__header">
        <div className="help-page__header-text">
          <Title level={3} className="help-page__title">
            帮助
          </Title>
          <Text type="secondary" className="help-page__subtitle">
            使用说明与常见问题，内容与主窗口内帮助一致。
          </Text>
        </div>
        <Space wrap className="help-page__actions">
          <Button onClick={props.onClose}>关闭</Button>
        </Space>
      </header>
      <main className="help-page__body">{inner}</main>
    </div>
  );
}
