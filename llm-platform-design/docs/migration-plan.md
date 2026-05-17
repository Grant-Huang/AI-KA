# 从 AI-KA 迁移计划

## 一、策略

**提取 + 精简**：从 AI-KA 复制平台层代码，剥离业务特性，重构为通用平台。AI-KA 的业务逻辑后续作为平台上的一个 App（`doc-reviewer`）回归。

```
AI-KA（现有）             llm-platform（新建）
─────────────────         ─────────────────────────
web/frontend/src/   →     web/frontend/src/        (UI框架层，去业务)
web/backend/        →     backend/                 (平台层，去业务)
review_skill_pkgs/  →     apps/doc-reviewer/       (业务迁移为 App)
docs/aika_spec/     →     docs/                    (架构文档重写)
```

---

## 二、阶段划分

### Phase 1：建立平台骨架（可运行）

**目标**：三栏布局 + 流式对话通跑，无业务功能。

前端任务：
- [ ] 复制 `styles.css`，保留布局/配色/字体相关 CSS，删除业务特定样式
- [ ] 复制 `App.tsx`，精简为三栏骨架（AppSidebar + SessionColumn + AppMain）
- [ ] 复制 `ChatWindow.tsx` → 重构为 `ChatPane.tsx`（去掉文档审查相关逻辑）
- [ ] 复制 `AllSessionsPanel.tsx`（直接复用）
- [ ] 复制 `api.ts`（SSE 客户端，直接复用）
- [ ] 复制 `BlockRenderer.tsx` / `SimpleMarkdown.tsx`（直接复用）
- [ ] 新增 `ArtifactPane.tsx`（新功能，Phase 1 仅搭骨架）
- [ ] 新增 `SplitLayout.tsx`（可拖动分隔条，Phase 1 实现）
- [ ] 保留 `pages/SettingsPage.tsx`（简化为 LLM 配置页）

后端任务：
- [ ] 复制 `streaming.py`（SSE 工具，直接复用）
- [ ] 复制 `llm_utils.py` / `llm_provider.py`（直接复用）
- [ ] 复制 `conversation_fsm.py`（去掉审查特定状态）
- [ ] 复制 `db/schema.py`（精简为平台表）
- [ ] 新建 `routers/chat.py`（通用流式对话端点）
- [ ] 新建 `routers/sessions.py`（会话 CRUD）
- [ ] 新建 `plugins/manifest.py`（App Manifest 加载）
- [ ] 内置一个 `chat-assistant` App（无知识库，无特殊 Skill）

Phase 1 完成标志：启动后可以进行多轮流式对话，会话历史可见。

---

### Phase 2：记忆系统

- [ ] 实现 `memory/short_term.py`：会话结束后写 `{session_id}.md`
- [ ] 实现 `memory/long_term.py`：Obsidian vault 文件读写
- [ ] 实现 `memory/recall.py`：混合召回（从 AI-KA `memory_recall.py` 改造）
- [ ] 前端：对话开始时显示"已召回 N 条记忆"状态条
- [ ] 前端：Composer 右键 → "存入记忆"
- [ ] 前端：设置页 → Obsidian vault 路径配置

Phase 2 完成标志：对话上下文能自动引用历史会话内容；用户偏好跨会话保持。

---

### Phase 3：应用插件系统

- [ ] 实现 `plugins/manifest.py`：解析 App Manifest，注册 App
- [ ] 实现 `plugins/knowledge.py`：知识库索引（从 AI-KA 文档索引逻辑改造）
- [ ] 实现 `plugins/tools_registry.py`：Tools 注册与执行框架
- [ ] 实现 `plugins/skill.py`：Skill 模板加载与变量填充
- [ ] 前端：AppSidebar 图标根据注册的 App 动态渲染
- [ ] 前端：Composer 工具栏根据当前 App 的 manifest 动态显示

Phase 3 完成标志：通过添加 manifest.json 可以注册新 App，无需修改平台代码。

---

### Phase 4：Artifact 面板

- [ ] 前端：实现可拖动 `SplitLayout`（60/40，记忆比例）
- [ ] 前端：`ArtifactPane` 完整实现（Tabs + 操作栏）
- [ ] 前端：`CodeArtifact`（highlight.js 代码高亮）
- [ ] 前端：`HtmlArtifact`（沙箱 iframe 实时预览）
- [ ] 前端：`MermaidArtifact`（mermaid.js 渲染）
- [ ] 前端：`MarkdownArtifact`（Markdown 预览）
- [ ] 后端：SSE 协议扩展 `artifact` 事件类型
- [ ] 后端：流式输出中识别 artifact fence，yield artifact_event

Phase 4 完成标志：LLM 输出代码块/HTML/Mermaid 时，自动在右侧 Artifact 面板渲染。

---

### Phase 5：内容提取路由

- [ ] 后端：`extraction/detector.py`（规则引擎，识别 findings / decisions / tasks）
- [ ] 前端：`FindingsPanel`（从 AI-KA 直接复用，简化）
- [ ] 前端：Artifact 操作栏 → "存入记忆"按钮
- [ ] 前端：提取内容的审批队列 UI（从 AI-KA `ReviewQueueDrawer` 改造）

---

### Phase 6：doc-reviewer App 回归

将 AI-KA 的核心业务逻辑迁移为平台上的一个 App：

- [ ] 创建 `apps/doc-reviewer/manifest.json`
- [ ] 迁移 `review_skill_packages/` → `apps/doc-reviewer/skills/`
- [ ] 迁移文档索引 + 审查流程 → 平台 knowledge + tools
- [ ] 验证 AI-KA 原有功能在平台上完整可用

---

## 三、文件对照表

### 前端：直接复用（少量改名）

| AI-KA 文件 | 平台文件 | 改动 |
|------------|----------|------|
| `src/api.ts` | `src/api.ts` | 更新 API 路径 |
| `src/BlockRenderer.tsx` | `src/BlockRenderer.tsx` | 直接复用 |
| `src/SimpleMarkdown.tsx` | `src/SimpleMarkdown.tsx` | 直接复用 |
| `src/AllSessionsPanel.tsx` | `src/AllSessionsPanel.tsx` | 直接复用 |
| `src/styles.css` | `src/styles.css` | 删除业务特定样式 |

### 前端：重构

| AI-KA 文件 | 平台文件 | 改动 |
|------------|----------|------|
| `src/App.tsx` | `src/App.tsx` | 去掉文档审查路由，改为 App 插件路由 |
| `src/ChatWindow.tsx` | `src/ChatPane.tsx` | 去掉审查特定逻辑，通用化 |
| `src/FindingsPanel.tsx` | `src/FindingsPanel.tsx` | 通用化（不强绑审查业务） |

### 前端：新增

| 平台文件 | 说明 |
|----------|------|
| `src/ArtifactPane.tsx` | Artifact 面板（新功能） |
| `src/SplitLayout.tsx` | 可拖动分割布局 |
| `src/AppContext.tsx` | App 插件上下文 Provider |

### 后端：直接复用

| AI-KA 文件 | 平台文件 | 改动 |
|------------|----------|------|
| `backend/streaming.py` | `core/streaming.py` | 直接复用 |
| `backend/llm_utils.py` | `core/llm_provider.py` | 直接复用 |
| `backend/embedding_service.py` | `core/embedding_service.py` | 直接复用 |

### 后端：重构

| AI-KA 文件 | 平台文件 | 改动 |
|------------|----------|------|
| `backend/main.py` | `backend/main.py` | 去掉审查特定路由 |
| `backend/conversation_fsm.py` | `core/conversation_fsm.py` | 去掉审查状态 |
| `backend/prompt_builder.py` | `core/prompt_builder.py` | 通用模板变量注入 |
| `backend/memory_recall.py` | `memory/recall.py` | 扩展支持 Obsidian |
| `backend/personal_memory.py` | `memory/short_term.py` | 重构为 .md 文件存储 |

### 后端：业务代码迁移为 App

| AI-KA 文件 | 迁移目标 |
|------------|----------|
| `backend/routers/` (审查相关) | `apps/doc-reviewer/` |
| `backend/finding_parser.py` | `apps/doc-reviewer/tools/` |
| `backend/epic_mapper.py` | `apps/doc-reviewer/tools/` |
| `review_skill_packages/` | `apps/doc-reviewer/skills/` |

---

## 四、不迁移的部分

以下 AI-KA 特有功能**不**进入平台层：

| 功能 | 原因 |
|------|------|
| `epic-doc` Word 导出 | 强业务依赖，留在 doc-reviewer App |
| `docs2md` 文档转换 | 文档审查特有，留在 doc-reviewer App |
| `DOCX` 报告生成 | 同上 |
| 审查域 Markdown 格式 | 留在 doc-reviewer App 的 skills/ |

---

## 五、AI-KA 与平台的长期关系

```
阶段 0（现在）：AI-KA 独立运行
阶段 1（平台完成 Phase 1-3 后）：
  - llm-platform 可独立运行，含通用对话能力
  - AI-KA 继续独立运行，不受影响
阶段 2（可选，未来）：
  - AI-KA 将业务代码整理为 doc-reviewer App manifest
  - AI-KA 引用 llm-platform 为底层（submodule 或 vendor 复制）
  - AI-KA 专注维护 doc-reviewer 业务逻辑
```
