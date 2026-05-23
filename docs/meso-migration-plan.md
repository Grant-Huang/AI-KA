# Meso 平台迁移计划

## 目标

将 AI-KA 的流式对话 UI 层迁移到 [Meso 平台](https://github.com/grant-huang/meso)，
使用 `@meso/ui` 组件库和 Meso SSE v1.0 协议。

## 测试门禁（Test Gates）

每个阶段必须通过其对应的门禁才能进入下一阶段。

| 阶段 | 内容 | 门禁条件 |
|------|------|---------|
| **G0** | 建立分支基线 | CI 全绿（既有测试） |
| **G1** | 加协议契约测试 | 新测试 RED（预期），既有测试 GREEN |
| **G2** | 迁移 `streaming.py` + `analyze/stream` SSE | 所有测试 GREEN |
| **G3** | 迁移 `followup/stream` + `agent/stream` SSE | 所有测试 GREEN |
| **G4** | 迁移 extraction SSE | 所有测试 GREEN |
| **G5** | 前端引入 Meso 依赖 | `npm run build` GREEN |
| **G6** | 前端 SSE 客户端替换 `useSSEStream` | 前端测试 GREEN |
| **G7** | 前端 Chat UI 替换 Meso 组件 | `npm run build` GREEN |

## SSE 事件映射

### 协议格式变更

所有 SSE 事件从扁平格式迁移到 Meso v1.0 信封格式：

```
# 旧格式（AI-KA 现有）
data: {"type": "stage", "name": "召回记忆", "state": "start"}

# 新格式（Meso v1.0）
data: {"type": "stage", "schema_version": "1.0", "payload": {"name": "召回记忆", "state": "active"}}
```

### 事件类型映射

| AI-KA 类型 | Meso v1.0 类型 | 备注 |
|-----------|---------------|------|
| `stage` (name/state=start\|end) | `stage` (payload.state=active\|done) | state 值重命名 |
| `delta` (text) | `text` (payload.delta) | |
| `final` | `extension(name="final")` + `done` | 结果内容 + 终止 |
| `error` | `error` (payload.message) | |
| `finding` | `extension(name="finding", data=...)` | |
| `chunk_index` | `extension(name="chunk_index", data=...)` | |
| `explain_memory` | `memory` 或 `extension` | |
| `explain_skill` | `extension(name="explain_skill", data=...)` | |
| `explain_tools` | `extension(name="explain_tools", data=...)` | |
| `explain_hooks` | `extension(name="explain_hooks", data=...)` | |
| `status` | `extension(name="status", data=...)` | |
| `critique` | `extension(name="critique", data=...)` | |
| `pass_done` | `extension(name="pass_done", data=...)` | |
| `agent_stage` | `extension(name="agent_stage", data=...)` | |
| `assistant_delta` | `text` (payload.delta) | |
| `agent_decision` | `extension(name="agent_decision", data=...)` | |

## 前端 Meso 依赖接入

### 方案：vendor dist

将 Meso 构建产物 vendored 到 `web/vendor/meso/` 目录：

```
web/vendor/meso/
  meso-types/    # @meso/types dist
  meso-ui/       # @meso/ui dist
```

`package.json` 中以 `file:` 路径引用：

```json
{
  "dependencies": {
    "@meso/types": "file:../vendor/meso/meso-types",
    "@meso/ui": "file:../vendor/meso/meso-ui"
  }
}
```

这样无需修改 CI workflow，`npm ci` 直接使用 vendored 包。

## 前端组件替换范围

### 对话区域（chat window）— 全部替换为 Meso 组件

- `ThreeColumnLayout` 替换 Antd `Layout`
- `MessageList` + `ChatBubble` 替换自定义消息渲染
- `ThinkBlock` 替换自定义思考块
- `ArtifactPanel` 替换代码/图表渲染
- `useSSEStream` 替换自定义 SSE fetch 逻辑
- `StageTimeline` 替换阶段进度展示

### 业务页面（extraction、knowledge、vaults 等）— 保留 Antd

Meso 不提供通用表单/表格组件，业务页面继续使用 Antd。
两套组件可共存，CSS 变量命名空间不同（`--meso-*` vs Antd token）。

## 注意事项

### milestones 文件格式（不迁移）

落盘的 `.milestones` 文件使用独立的内部 JSONL 格式（由 `append_milestone_event` 写入），
与 SSE 流格式独立，**本次迁移不修改**。
`useConversationReplay.ts` 读取的是落盘格式，不受影响。

### stage 状态值对齐

- AI-KA 旧值：`start` / `end`
- Meso v1.0 要求：`active` / `done` / `error`
- 迁移时统一替换
