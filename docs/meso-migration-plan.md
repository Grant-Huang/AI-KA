# AI-KA → Meso 平台迁移计划

**版本**: V1.0（草稿，待 meso 平台细节补全）  
**日期**: 2026-05-22  
**分支**: `claude/meso-migration-plan-Th7Hl`

> **说明**: 本文档基于对 AI-KA 代码库的完整分析起草。带 `[MESO待确认]` 标记的条目需在获取 meso 平台详细 API/接口后补全。

---

## 目录

1. [现状分析](#1-现状分析)
2. [迁移目标与范围](#2-迁移目标与范围)
3. [系统模块映射](#3-系统模块映射)
4. [分阶段迁移计划](#4-分阶段迁移计划)
5. [数据迁移方案](#5-数据迁移方案)
6. [接口契约保全策略](#6-接口契约保全策略)
7. [前端迁移策略](#7-前端迁移策略)
8. [测试策略](#8-测试策略)
9. [风险与依赖](#9-风险与依赖)
10. [待确认事项（meso 侧）](#10-待确认事项meso-侧)

---

## 1. 现状分析

### 1.1 AI-KA 技术栈总览

| 层次 | 当前实现 | 规模 |
|------|---------|------|
| CLI 核心库 | Python 3.12，`src/aika/` | ~4,500 行 |
| Web 后端 | FastAPI + Uvicorn，`web/backend/` | ~9,900 行 |
| Web 前端 | React 18 + TypeScript + Ant Design 5，`web/frontend/` | ~8,500 行 |
| 数据库 | SQLite（WAL 模式），单文件 `projects.db` | 25 张表 |
| 文件存储 | 本地文件系统（`.aika/`、`review_skill_packages/`、`~/.aika/`） | — |
| LLM 接入 | OpenAI-Compatible REST API（自建 `urllib` 实现，无第三方依赖） | — |
| 向量/嵌入 | 可选，同一 OpenAI-Compatible 端点 | — |
| 导出 | `epic-doc`（外部 Python 库，生成 docx） | — |
| 部署 | Docker + docker-compose，单容器 | — |

### 1.2 核心子系统

```
┌─────────────────────────────────────────────────────────────┐
│                        Web 前端 (React/TS)                   │
│  App.tsx · ChatWindow · ExtractionPage · FindingsPanel      │
│  AllSessionsPanel · ReviewQueueDrawer · navigation.ts       │
└───────────────────────────┬─────────────────────────────────┘
                            │ REST + SSE
┌───────────────────────────▼─────────────────────────────────┐
│                    FastAPI 后端 (Python)                      │
│                                                              │
│  routers/                  services/                        │
│  ├─ conversations          ├─ outputs_files_service         │
│  ├─ extraction             └─ outputs_index_service         │
│  ├─ project_init           skills/                          │
│  ├─ review_queue           ├─ packages.py                   │
│  ├─ review_knowledge       ├─ focus_point_io.py             │
│  ├─ outputs                └─ review_domain_io.py           │
│  ├─ vaults                 hooks/                           │
│  ├─ auth                   ├─ registry.py                   │
│  └─ expert_profile         └─ builtin.py                    │
│                            tools/                           │
│  streaming.py  llm_utils.py  memory_recall.py               │
│  prompt_builder.py  context_builder.py                      │
│  conversation_fsm.py  intent_classifier.py                  │
│  embedding_service.py  obsidian_service.py                  │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│               CLI 核心库 (aika package)                       │
│  db.py · indexer.py · llm.py · analyze.py                  │
│  epic_doc.py · skill_manifest.py · paths.py                 │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 数据模型（SQLite 25 张表）

**核心实体**:
- `projects` — 项目（name, root_path）
- `documents` — 扫描到的文件（sha256 增量）
- `document_chunks` — 文本分块（含 `locator_json`）
- `conversations` — 会话（含 mode/state FSM）
- `messages` — 会话消息（含 `metadata_json` 存储 findings）
- `analysis_runs` — 分析执行记录
- `knowledge_items` — 提取的知识条目（含审核状态）
- `review_queue` — 待审规则建议
- `obsidian_vaults` — Obsidian 金库注册
- `app_settings` — 用户配置（focus_points, preset_combos, 模型设置等）
- `memory_file_embeddings` — 记忆文件向量缓存

### 1.4 关键业务流程

```
文档分析主流程
  用户选择项目 + 关注点预设
    → POST /api/v1/projects/{pid}/conversations/{cid}/analyze/stream
    → 召回记忆 recall_combined()
    → build_system_prompt() （注入 focus_definitions + memory_snippets）
    → build_user_prompt_from_entries() （注入 chunks + 索引表）
    → LLM 流式输出 → SSE 事件
    → finding_parser 解析结构化发现 → 落库 messages.metadata_json
    → 生成 docx / Markdown 导出

知识提取流程
  POST /api/v1/extraction/stream
    → LLM 主动提问专家 → ki_parser 解析知识条目
    → POST /knowledge-items → 人工审核 → 知识库

技能包系统
  review_skill_packages/{package_id}/
    ├─ manifest.json
    ├─ review_domain.md  （v1：单文件解析 focus blocks + combo table）
    └─ focus-points/*.md  （v2：每个关注点独立文件）
```

---

## 2. 迁移目标与范围

### 2.1 迁移动机

| 问题点 | 当前状态 | meso 平台预期改善 |
|--------|---------|-----------------|
| 前后端语言割裂 | Python 后端 + TS 前端 | `[MESO待确认]` 统一技术栈？ |
| LLM 集成 | 手写 urllib，无 SDK | `[MESO待确认]` meso AI 层 |
| 流式 SSE | 自实现 | `[MESO待确认]` meso 流式抽象 |
| 状态管理 | React useState 分散 | `[MESO待确认]` meso 状态方案 |
| 路由 | 自实现 URL 解析 | `[MESO待确认]` meso 路由 |
| 组件库 | Ant Design 5 | `[MESO待确认]` meso UI 组件 |
| 部署 | 单容器 Docker | `[MESO待确认]` meso 部署目标 |

### 2.2 迁移范围（完整功能列表）

**必须迁移（核心功能）**:
- [ ] 项目管理（创建/注册/切换）
- [ ] 文档上传与格式转换（.docx/.pdf/.xlsx → .md）
- [ ] 文档索引与分块（blank/structured 两种策略）
- [ ] 会话对话（多轮 LLM 流式审查）
- [ ] 关注点 + 预设组合系统（focus_points + combo presets）
- [ ] 技能包加载（v1/v2 格式）
- [ ] 记忆召回（关键词 + 向量混合）
- [ ] 知识提取（AI 主动提问 → KI 解析 → 审核）
- [ ] 发现 (Finding) 结构化存储与状态追踪
- [ ] 审查队列（Review Queue）工作流
- [ ] 导出（Markdown + docx via epic-doc）
- [ ] 设置页（模型配置、关注点编辑、预设组合）
- [ ] 会话历史（分页、搜索、收藏）

**可选/后续迁移**:
- [ ] Obsidian 金库集成
- [ ] 个人记忆（`~/.aika/`）
- [ ] Native 文件夹选择器
- [ ] Hooks 系统
- [ ] 向量嵌入索引（目前为可选功能）

**不迁移（保持兼容）**:
- CLI 工具 `aika` 命令行（独立于 Web，保留原 Python 实现）
- `epic-doc` 库（外部依赖，保持不变）

---

## 3. 系统模块映射

### 3.1 后端模块对应关系

| AI-KA 模块 | 职责 | meso 迁移策略 |
|-----------|------|-------------|
| `src/aika/db.py` | SQLite CRUD，25 张表，~2,938 行 | `[MESO待确认]` 使用 meso 数据层？保留 SQLite？ |
| `src/aika/indexer.py` | 文件扫描 + 分块（blank/structured） | `[MESO待确认]` 迁移为 TS 模块 or 保留 Python 微服务 |
| `src/aika/llm.py` | OpenAI-Compatible 流式调用 | `[MESO待确认]` 替换为 meso AI provider |
| `web/backend/prompt_builder.py` | 系统提示 + 用户提示构建 | 迁移为 TS，逻辑完整保留 |
| `web/backend/conversation_fsm.py` | 对话状态机 | 迁移为 TS，状态机逻辑不变 |
| `web/backend/memory_recall.py` | 混合召回（关键词 35% + 向量 65%） | 迁移为 TS，算法不变 |
| `web/backend/skills/` | 技能包发现/解析 | 迁移为 TS |
| `web/backend/streaming.py` | SSE 格式化 | `[MESO待确认]` 使用 meso streaming |
| `web/backend/embedding_service.py` | 向量计算（numpy-free） | 迁移为 TS（已是纯数值运算） |
| `web/backend/obsidian_service.py` | Obsidian 金库集成 | 二期迁移 |
| `web/backend/routers/extraction.py` | 知识提取 API（~1,305 行） | 拆分为多个 meso handler |
| `web/backend/routers/conversations.py` | 会话 CRUD | 迁移 |
| `web/backend/routers/review_queue.py` | 审查队列 | 迁移 |
| `web/backend/hooks/` | 钩子注册/触发 | 二期，`[MESO待确认]` meso 钩子机制 |

### 3.2 前端模块对应关系

| AI-KA 组件 | 职责 | meso 迁移策略 |
|-----------|------|-------------|
| `App.tsx`（~225KB） | 主 Shell + 全部页面逻辑（过大）| **必须拆分**：按页面/功能模块拆解 |
| `api.ts`（~26KB） | 所有 API 调用 + SSE 消费 | `[MESO待确认]` meso API client 层 |
| `navigation.ts` | URL 解析/构建 | `[MESO待确认]` meso 路由 |
| `ChatWindow.tsx` | 对话消息气泡 | 迁移为 meso 组件 |
| `ExtractionPage.tsx`（~52KB） | 知识提取页（过大）| **必须拆分**：Wizard + QA + Review 三部分 |
| `FindingsPanel.tsx` | 发现列表展示 | 迁移 |
| `ReviewQueueDrawer.tsx` | 审查队列抽屉 | 迁移 |
| `AllSessionsPanel.tsx` | 会话历史 | 迁移 |
| `BlockRenderer.tsx` | Markdown 渲染 | `[MESO待确认]` meso Markdown 支持 |
| `pages/system_setting.tsx` | 设置页 | 迁移 |

---

## 4. 分阶段迁移计划

### Phase 0：准备（1 周）

**目标**: 不改变任何功能，为迁移建立基础设施。

- [ ] **0.1** 了解 meso 平台全部 API 及接口约定（补全本文档所有 `[MESO待确认]` 项）
- [ ] **0.2** 确定迁移后的技术栈决策：
  - 后端：Python FastAPI 保留 or 迁移至 meso 的 Node.js/TS 后端？
  - 数据库：SQLite 保留 or 迁移至 meso 数据层？
  - 前端：Ant Design 保留 or 迁移至 meso UI 组件？
- [ ] **0.3** 建立端到端测试基线：录制当前 API 的 request/response 快照
- [ ] **0.4** 梳理 meso 的 monorepo 结构，确定 AI-KA 作为哪个 package 接入
- [ ] **0.5** 建立迁移后的 CI 流水线

**交付物**: 更新后的迁移计划（本文档 V1.1）

---

### Phase 1：数据层迁移（2 周）

**目标**: 将 SQLite 数据模型迁移到 meso 平台数据层（或确认保留）。

**前提**: `[MESO待确认]` meso 是否提供 ORM/数据访问层？

**方案 A（meso 有数据层）**:
- [ ] **1.1** 将 25 张 SQLite 表映射到 meso 数据模型
- [ ] **1.2** 编写数据迁移脚本（SQLite → meso 存储）
- [ ] **1.3** 迁移 `src/aika/db.py` 的 CRUD 接口（按表分模块）
- [ ] **1.4** 保留 `db_path()` / `connect()` / `ensure_schema()` 的兼容层，支持现有测试

**方案 B（meso 无数据层，保留 SQLite）**:
- [ ] **1.1** 将 `src/aika/db.py` 封装为独立微服务 or 保留作为内部模块
- [ ] **1.2** 确保 meso 应用可调用 SQLite 层（Python 进程 or HTTP）

**关键迁移顺序（按依赖关系）**:
```
projects → documents → document_chunks
    ↓
conversations → messages → analysis_runs
    ↓
knowledge_items → review_queue
    ↓
app_settings → obsidian_vaults
```

---

### Phase 2：LLM 与流式层迁移（1 周）

**目标**: 将 LLM 调用和 SSE 流式机制切换到 meso 平台。

**当前实现分析**:
- `src/aika/llm.py`：纯 Python，无第三方依赖，手动解析 SSE 流
- `web/backend/llm_utils.py`：`stream_and_collect_iter()` 逐 chunk yield
- `web/backend/streaming.py`：`sse_event(obj)` / `sse_stage(name, state)`

**迁移步骤**:
- [ ] **2.1** `[MESO待确认]` 确认 meso AI provider 的调用接口（是否兼容 OpenAI Chat Completions 格式？）
- [ ] **2.2** `[MESO待确认]` 确认 meso 的流式/SSE 机制（前端消费方式）
- [ ] **2.3** 将 `LLMProvider` 接口适配为 meso provider（保留 `MockProvider` 用于测试）
- [ ] **2.4** 将 `stream_and_collect_iter` 迁移为 meso 流式调用

**注意事项**:
- 现有前端的 `consumeSseFromResponse()` 依赖特定的 SSE 事件格式（`type`, `content`, `stage` 等），迁移时需要保持格式兼容或同步修改前端
- 嵌入（embedding）调用使用同一端点，需一并适配

---

### Phase 3：后端核心逻辑迁移（3 周）

**目标**: 将 FastAPI 路由和业务逻辑迁移到 meso 框架。

#### 3a: 提示词与对话系统（1 周）

- [ ] **3a.1** 迁移 `prompt_builder.py`（系统提示构建，含 focus_definitions + memory 注入）
- [ ] **3a.2** 迁移 `conversation_fsm.py`（状态机：REVIEWING/CLARIFYING/REFINING/GENERATING/EXTRACTING）
- [ ] **3a.3** 迁移 `context_builder.py`（滚动上下文，build_rolling_context）
- [ ] **3a.4** 迁移 `intent_classifier.py`（规则优先意图分类，中文正则）
- [ ] **3a.5** 迁移 `finding_parser.py`（从 LLM Markdown 输出提取结构化 Finding）

#### 3b: 记忆与技能系统（1 周）

- [ ] **3b.1** 迁移 `memory_recall.py`（关键词 35% + cosine 65% 混合召回）
- [ ] **3b.2** 迁移 `personal_memory.py`（`~/.aika/memory/` 个人记忆）
- [ ] **3b.3** 迁移 `skills/packages.py`（技能包发现，v1/v2 格式）
- [ ] **3b.4** 迁移 `skills/review_domain_io.py`（review_domain.md 严格解析）
- [ ] **3b.5** 迁移 `skills/focus_point_io.py`（focus-points/*.md 加载）
- [ ] **3b.6** 迁移 `embedding_service.py`（向量计算，纯数值，无 numpy）

#### 3c: API 路由迁移（1 周）

按优先级顺序：

| 优先级 | 路由文件 | 端点数 | 备注 |
|--------|---------|--------|------|
| P1 | `conversations.py` | 6 | 核心对话 CRUD |
| P1 | `project_init.py` | 2 | 项目初始化 + 文件上传 |
| P1 | `main.py` (analyze/stream) | 3 | **最核心**：分析流式端点 |
| P2 | `extraction.py` | 10 | 知识提取（最大，~1305行） |
| P2 | `review_queue.py` | 5 | 审查队列 |
| P2 | `review_knowledge.py` | 4 | 知识审核 |
| P3 | `outputs.py` | 4 | 导出文件 |
| P3 | `auth.py` | 3 | 认证 |
| P3 | `expert_profile.py` | 2 | 专家档案 |
| P4 | `vaults.py` | 8 | Obsidian 集成 |
| P4 | `pending_rules.py` | 3 | 规则审批 |

---

### Phase 4：前端重构（3 周）

**目标**: 将 React/Ant Design 前端迁移到 meso 平台 UI 方案。

**当前问题**:
- `App.tsx` 单文件 225KB（严重超标，包含几乎全部业务逻辑）
- `ExtractionPage.tsx` 52KB（单页过大）
- `api.ts` 26KB（单文件 API 客户端）
- 路由为手写 URL hash 解析，无框架支持

#### 4a: 拆分 App.tsx（必须先做）

按功能域拆分为独立页面组件：

```
src/
├── pages/
│   ├── ProjectAnalysis/       ← App.tsx 主分析页
│   │   ├── index.tsx
│   │   ├── AnalysisForm.tsx
│   │   ├── AnalysisStream.tsx
│   │   └── FindingsView.tsx
│   ├── KnowledgeExtraction/   ← ExtractionPage.tsx
│   │   ├── index.tsx
│   │   ├── InterviewWizard.tsx
│   │   ├── KIReviewList.tsx
│   │   └── QualityReport.tsx
│   ├── Sessions/              ← AllSessionsPanel
│   ├── ReviewQueue/           ← ReviewQueueDrawer
│   └── Settings/              ← system_setting.tsx
├── components/
│   ├── ChatMessage.tsx        ← ChatWindow
│   ├── FindingCard.tsx        ← FindingsPanel
│   └── MarkdownBlock.tsx      ← BlockRenderer
└── api/
    ├── conversations.ts       ← api.ts 拆分
    ├── extraction.ts
    ├── projects.ts
    └── streaming.ts
```

#### 4b: 适配 meso 组件 `[MESO待确认]`

- [ ] **4b.1** 确认 meso UI 组件库与 Ant Design 的对应关系（Button, Modal, Drawer, Table, Form 等）
- [ ] **4b.2** 确认 meso 路由方案（替换手写 `navigation.ts`）
- [ ] **4b.3** 确认 meso 状态管理（替换 React useState/useRef 散装状态）
- [ ] **4b.4** 确认 meso SSE/streaming 消费 API（替换 `consumeSseFromResponse`）

#### 4c: 功能迁移顺序（按业务价值）

1. **项目选择 + 分析流式** （最核心 UX 路径）
2. **会话历史 + 多轮对话**
3. **设置页**（模型配置 + focus points 编辑）
4. **知识提取页**
5. **审查队列**
6. **导出功能**
7. **帮助页**

---

### Phase 5：集成测试与上线（1 周）

- [ ] **5.1** 端到端回归测试（与 Phase 0 基线对比）
- [ ] **5.2** 性能测试（流式响应延迟、大文档分块性能）
- [ ] **5.3** 数据迁移演练（现有用户数据）
- [ ] **5.4** `[MESO待确认]` meso 平台部署流程
- [ ] **5.5** 切流策略（灰度 or 全量切换）
- [ ] **5.6** 回滚方案：保留 AI-KA Docker 镜像作为回退

---

## 5. 数据迁移方案

### 5.1 SQLite 表迁移优先级

| 优先级 | 表名 | 数据量估计 | 迁移方式 |
|--------|-----|-----------|---------|
| 必须 | projects | 小 | 全量迁移 |
| 必须 | conversations | 中 | 全量迁移 |
| 必须 | messages | 大（含 LLM 输出） | 全量迁移 |
| 必须 | knowledge_items | 中 | 全量迁移 + 关联 |
| 必须 | app_settings | 小 | 全量迁移 |
| 必须 | review_queue | 小 | 全量迁移 |
| 可选 | documents | 中 | 可重新索引 |
| 可选 | document_chunks | 大 | **可重新索引**（无需迁移，重跑 indexer 更简单） |
| 可选 | memory_file_embeddings | 中 | 可重新计算 |
| 可延后 | obsidian_vaults | 小 | Phase 2 迁移 |

### 5.2 文件系统迁移

| 目录 | 内容 | 迁移策略 |
|------|------|---------|
| `review_skill_packages/` | 技能包定义（MD + JSON） | 原样复制，路径配置化 |
| `.aika/memory/` | 项目记忆文件 | 原样复制 |
| `~/.aika/memory/` | 个人记忆文件 | 原样复制 |
| `.aika/meta/quality.jsonl` | 质量报告 | 可选迁移 |
| `conversation_outputs/` | 历史导出文件 | 原样复制 |

### 5.3 迁移脚本模板

```python
# scripts/migrate_to_meso.py（待实现）
"""
SQLite → meso 数据迁移脚本
运行前先备份：cp projects.db projects.db.bak
"""
import sqlite3
from aika.db import connect, db_path

def migrate_projects(conn_src, meso_client):
    rows = conn_src.execute("SELECT * FROM projects").fetchall()
    for row in rows:
        meso_client.projects.create({
            "id": row["id"],
            "name": row["name"],
            "root_path": row["root_path"],
            "created_at": row["created_at"],
        })
    print(f"Migrated {len(rows)} projects")

# TODO: 补充其他表的迁移逻辑
```

---

## 6. 接口契约保全策略

### 6.1 需保持兼容的关键 API 端点

以下端点被前端大量调用，迁移时需保持路径和响应格式不变（或提供兼容层）：

```
POST /api/v1/projects/{pid}/conversations/{cid}/analyze/stream    ← 核心流式分析
POST /api/v1/projects/{pid}/conversations/{cid}/agent/stream      ← 自动编排流式
POST /api/v1/extraction/stream                                     ← 知识提取流式
GET  /api/v1/conversations                                         ← 会话列表
GET  /api/v1/projects                                              ← 项目列表
GET  /api/v1/settings                                              ← 应用设置
POST /api/v1/settings                                              ← 保存设置
GET  /api/v1/skill-packages                                        ← 技能包列表
```

### 6.2 SSE 事件格式（必须保持）

前端解析依赖以下 SSE 事件类型：

```typescript
// 文本内容块
{ type: "content", text: string }

// 阶段更新
{ type: "stage", name: string, state: "start" | "done" | "error", detail?: string }

// 发现条目
{ type: "finding", finding: Finding }

// 错误
{ type: "error", code: string, message: string }

// 流结束
{ type: "done", run_id?: number }
```

### 6.3 响应体格式（必须保持）

```typescript
// 所有 REST 端点
{ status: "success" | "error", data: T, message?: string }
```

---

## 7. 前端迁移策略

### 7.1 App.tsx 拆分方法论

`App.tsx` 当前包含 ~8,000 行代码，需要系统性拆分：

1. **提取状态**：将全局 state（项目、会话、设置）提取到 Context 或 meso 状态管理
2. **提取 API 调用**：将所有 `apiJson`/`fetch` 调用集中到 `src/api/` 目录
3. **提取页面组件**：按 URL 路由分割，每个页面独立文件
4. **提取共享组件**：ChatWindow, FindingCard, MarkdownBlock 等

### 7.2 流式消费迁移

当前 `consumeSseFromResponse` 实现：
```typescript
// api.ts 中的 SSE 消费逻辑
async function* consumeSseFromResponse(response: Response) {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  // 解析 "data: {...}\n\n" 格式
  ...
}
```

`[MESO待确认]` meso 是否提供等价的流式消费 API？如有，替换此实现；如无，保留并封装。

### 7.3 Markdown 渲染

当前 `BlockRenderer.tsx` + `SimpleMarkdown.tsx` 是自实现的 Markdown 渲染器（无第三方依赖）。

`[MESO待确认]` meso 是否内置 Markdown 支持？如有，替换；如无，保留现有实现。

---

## 8. 测试策略

### 8.1 现有测试（需全部通过）

```
tests/
├── test_acceptance_scenarios.py      ← 端到端场景测试
├── test_analyze_stream_api.py        ← 分析流式 API
├── test_conversations_api.py         ← 会话 API
├── test_knowledge_extraction_api.py  ← 知识提取 API
├── test_memory_recall.py             ← 记忆召回
├── test_skill_manifest.py            ← 技能包解析
├── test_indexer_sync.py              ← 索引器
├── test_ki_parser.py                 ← 知识条目解析器
├── test_finding_parser.py            ← 发现解析器（间接覆盖）
└── ... (共 19 个测试文件)
```

### 8.2 迁移测试策略

| 阶段 | 测试类型 | 工具 |
|------|---------|------|
| 每个 Phase | 单元测试（迁移模块） | pytest / vitest |
| Phase 3 完成 | API 契约测试 | httpx + 快照对比 |
| Phase 4 完成 | UI 冒烟测试 | `[MESO待确认]` |
| Phase 5 | 端到端回归 | 复用现有 acceptance tests |

### 8.3 迁移验收标准

- [ ] 所有现有 Python 测试（pytest）通过
- [ ] 所有现有前端测试（vitest）通过
- [ ] 分析流式 API 端到端延迟 ≤ 现有基线 +10%
- [ ] 大文档（500 chunks）分析不超时
- [ ] 知识提取完整流程可运行
- [ ] 技能包加载（v1/v2 格式均支持）
- [ ] 数据迁移后现有会话历史可查看

---

## 9. 风险与依赖

### 9.1 高风险项

| 风险 | 影响 | 概率 | 缓解策略 |
|------|------|------|---------|
| `App.tsx` 拆分引入回归 | 高 | 高 | 拆分前补充 UI 截图基线；小步提交 |
| LLM 流式格式不兼容 | 高 | 中 | Phase 0 先对齐 meso AI provider 格式 |
| SQLite 事务语义差异 | 高 | 低 | 数据迁移后全量回归测试 |
| `review_domain.md` 解析破坏 | 中 | 中 | 现有 `test_repo_review_domain_load.py` 覆盖 |
| 中文正则 `intent_classifier` 失效 | 中 | 低 | 迁移时 100% 复制规则，补充中文测试用例 |

### 9.2 外部依赖

| 依赖 | 当前版本 | 迁移影响 |
|------|---------|---------|
| `epic-doc` (GitHub) | 固定 commit | 保持不变，迁移后仍调用 Python 进程 |
| `markitdown[xlsx]` | ≥0.1.0 | 文件转换保留 Python 端 |
| Ant Design | ^5.22.0 | `[MESO待确认]` 是否被 meso UI 替换 |
| React | ^18.3.1 | `[MESO待确认]` meso 前端框架基础 |

### 9.3 不可并行执行的约束

```
Phase 0（确认 meso 接口）
    ↓ 必须完成才能开始
Phase 1（数据层）← 与 Phase 2 可并行
Phase 2（LLM 层）← 与 Phase 1 可并行
    ↓ 两者完成后
Phase 3（后端逻辑）
    ↓ Phase 3 完成后
Phase 4（前端重构）← 但拆分 App.tsx 可提前开始
    ↓
Phase 5（集成测试）
```

---

## 10. 待确认事项（meso 侧）

在开始实际迁移代码之前，需要从 meso 平台文档/代码中确认以下问题：

### 平台基础

- [ ] **M1** meso 的 packages/ 目录包含哪些包？各自的职责是什么？
- [ ] **M2** meso 是否提供后端框架？（Node.js/TS API server？还是仅前端？）
- [ ] **M3** meso demo 应用是什么形态？用于参考迁移目标架构。

### AI/LLM 层

- [ ] **M4** meso 是否有内置 LLM provider？调用接口是什么？
- [ ] **M5** meso 是否支持 OpenAI-Compatible API 格式？
- [ ] **M6** meso 的流式/SSE 抽象：前端如何消费 LLM 流？

### 数据层

- [ ] **M7** meso 是否有内置 ORM 或数据访问层？
- [ ] **M8** meso 支持哪些数据库？是否支持 SQLite？
- [ ] **M9** meso 的文件存储抽象：如何处理本地文件系统访问？

### 前端

- [ ] **M10** meso 的 UI 组件库：是否有对应 Ant Design 的组件？
- [ ] **M11** meso 的路由方案：如何替换现有 URL hash 路由？
- [ ] **M12** meso 的状态管理：全局状态如何管理？
- [ ] **M13** meso 是否内置 Markdown 渲染支持？
- [ ] **M14** meso 是否有 Drawer/Modal/Table 等布局组件？

### 部署

- [ ] **M15** meso 的目标部署环境（Docker？云平台？）
- [ ] **M16** meso 的构建/打包方式

---

## 附录 A：AI-KA 关键代码位置速查

| 主题 | 文件路径 | 关键函数/类 |
|------|---------|-----------|
| 数据库 schema | `src/aika/db.py:1-150` | `SCHEMA_SQL`, `ensure_schema()` |
| 分块策略 | `src/aika/indexer.py` | `CHUNK_STRATEGY_BLANK/STRUCTURED` |
| LLM Provider | `src/aika/llm.py` | `LLMProvider`, `OpenAICompatibleProvider` |
| 系统提示构建 | `web/backend/prompt_builder.py` | `build_system_prompt()` |
| 用户提示构建 | `web/backend/prompt_builder.py` | `build_user_prompt_from_entries()` |
| 对话状态机 | `web/backend/conversation_fsm.py` | `transition()` |
| 记忆召回 | `web/backend/memory_recall.py` | `recall_combined()` |
| 意图分类 | `web/backend/intent_classifier.py` | `classify_intent()` |
| 发现解析 | `web/backend/finding_parser.py` | — |
| 知识条目解析 | `web/backend/ki_parser.py` | `extract_ki_items()` |
| SSE 格式化 | `web/backend/streaming.py` | `sse_event()`, `sse_stage()` |
| LLM 流式调用 | `web/backend/llm_utils.py` | `stream_and_collect_iter()` |
| 技能包发现 | `web/backend/skills/packages.py` | `list_skill_packages()` |
| review_domain 解析 | `web/backend/skills/review_domain_io.py` | `review_domain_strict_schema_error()` |
| 向量计算 | `web/backend/embedding_service.py` | `cosine_similarity()`, `hybrid_score()` |
| 前端 API 客户端 | `web/frontend/src/api.ts` | `consumeSseFromResponse()` |
| 前端路由 | `web/frontend/src/navigation.ts` | `parseUrl()`, `buildUrl()` |

---

*文档将在获取 meso 平台详情后更新为 V1.1，补全所有 `[MESO待确认]` 标注。*
