import { Button, Spin, Tabs, Typography } from "antd";
import { useMemo } from "react";

import SimpleMarkdown from "../SimpleMarkdown";
import { parseHelpmeMarkdown } from "../helpTabs";

const { Title } = Typography;

export default function HelpPage(props: {
  loading: boolean;
  markdown: string;
  onClose: () => void;
}) {
  const parsed = useMemo(() => parseHelpmeMarkdown(props.markdown), [props.markdown]);
  return (
    <div className="standalone-page">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <Title level={3} style={{ margin: 0 }}>
          帮助
        </Title>
        <Button onClick={props.onClose}>关闭</Button>
      </div>
      <div style={{ marginTop: 14 }}>
        {props.loading ? (
          <Spin />
        ) : parsed.ok ? (
          <Tabs
            size="small"
            items={parsed.tabs.map((t) => ({
              key: t.label,
              label: t.label,
              children: (
                <div style={{ paddingTop: 8 }}>
                  <SimpleMarkdown markdown={t.content} />
                </div>
              ),
            }))}
          />
        ) : (
          <SimpleMarkdown markdown={parsed.markdown || "# 帮助\n\n暂无帮助内容。"} />
        )}
      </div>
    </div>
  );
}

