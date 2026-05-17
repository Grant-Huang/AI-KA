# LLM Platform

基于流式对话的 AI 应用基础框架。提供统一的 UI 规范、流式对话核心、可插拔的应用能力（知识库 / Tools / 提示词），以及分层记忆系统。

## 定位

```
llm-platform          ← 本 repo：平台层（UI框架 + 流式对话 + 记忆 + 插件机制）
      ↑
各业务应用             ← 基于平台构建，只需提供 App Manifest
（AI-KA / 新项目 / ...）
```

**平台层不包含业务逻辑。** 每个应用通过 App Manifest 声明自己需要的知识库、工具、提示词，平台负责将它们注入流式对话。

## 文档

| 文档 | 内容 |
|------|------|
| [架构总览](docs/architecture.md) | 系统分层、模块划分、数据流 |
| [UI 规范](docs/ui-spec.md) | 布局、配色、字体、组件规范 |
| [记忆系统](docs/memory-system.md) | 短期/长期记忆设计、Obsidian 集成 |
| [应用插件系统](docs/app-plugin-system.md) | App Manifest、知识库、Tools、Skill |
| [迁移计划](docs/migration-plan.md) | 从 AI-KA 提取平台层的步骤 |

## 技术栈

- **前端**: React 18 + TypeScript + Ant Design 5 + Vite
- **后端**: Python 3.12 + FastAPI + SQLite
- **流式**: Server-Sent Events (SSE)
- **记忆**: 本地 `~/.llm-platform/` + Obsidian Vault（文件读写）
