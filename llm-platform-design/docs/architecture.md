# 架构总览

## 一、系统分层

```
┌─────────────────────────────────────────────────────────────┐
│                        业务应用层                            │
│   App Manifest（知识库 + Tools + Skill + 提示词模板）        │
├─────────────────────────────────────────────────────────────┤
│                       平台服务层                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ 流式对话  │  │ 记忆系统  │  │ 插件引擎  │  │ 内容提取   │  │
│  │  Core    │  │ Memory   │  │ Plugin   │  │ Extraction │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                        UI 框架层                             │
│   三栏布局 / 流式渲染 / Artifact面板 / 会话历史              │
├─────────────────────────────────────────────────────────────┤
│                      基础设施层                              │
│   LLM Provider 抽象 / SQLite / SSE / 文件系统               │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、前端模块划分

### 2.1 布局框架

```
AppLayout
├── AppSidebar          # 左栏：图标菜单（可折叠 126px ↔ 48px）
├── SessionColumn       # 中栏：会话历史（260px，可隐藏）
└── AppMain             # 右栏：主工作区
    ├── PageHeader      # 顶部标题栏
    ├── ChatPane        # 流式对话区（纯模式：全宽；分屏模式：60%）
    ├── SplitDivider    # 可拖动分隔条（分屏模式）
    └── ArtifactPane    # Artifact 展示区（分屏模式：40%）
```

### 2.2 流式对话组件树

```
ChatPane
├── ChatThread          # 消息列表（滚动区）
│   ├── ChatBubble      # 用户消息气泡
│   └── AssistantBubble # AI 回复（含 Markdown / Think block / 流式光标）
├── StatusBar           # 思考状态 / 阶段进度
└── Composer            # 输入区
    ├── ComposerTextarea
    └── ComposerToolbar # 工具栏（知识库选择 / Tools 开关 / 发送）
```

### 2.3 Artifact 面板

```
ArtifactPane
├── ArtifactTabs        # 多 Artifact 标签（一次对话可产出多个）
└── ArtifactRenderer    # 按类型渲染：
    ├── CodeArtifact    # 代码高亮（highlight.js）
    ├── HtmlArtifact    # HTML 实时预览（沙箱 iframe）
    ├── MermaidArtifact # Mermaid 图表渲染
    ├── MarkdownArtifact# Markdown 预览
    └── TableArtifact   # 表格数据
```

Artifact 的识别：LLM 输出中约定特定 fence 标记，流式解析时实时路由到 ArtifactPane。

````
支持的 fence 标记示例：
```html preview     → HtmlArtifact
```mermaid          → MermaidArtifact  
```artifact:table   → TableArtifact
```

### 2.4 应用切换

```
AppSidebar
└── AppNav             # 图标列表，每个图标对应一个注册的 App
    └── onClick → AppContext.switchApp(appId)
                    ↓
              加载对应 App Manifest
              重置 ComposerToolbar 的工具集
              切换会话列表（按 appId 过滤）
```

---

## 三、后端模块划分

### 3.1 目录结构（目标）

```
backend/
├── main.py                  # FastAPI 入口，路由注册
├── routers/
│   ├── chat.py              # 流式对话 API
│   ├── sessions.py          # 会话 CRUD
│   ├── memory.py            # 记忆读写 API
│   ├── extraction.py        # 内容提取 API
│   └── apps.py              # App Manifest 注册/查询
├── core/
│   ├── streaming.py         # SSE 生成器工具函数
│   ├── llm_provider.py      # LLM Provider 抽象（openai_compatible / mock）
│   ├── conversation_fsm.py  # 多轮对话状态机
│   ├── prompt_builder.py    # 系统提示词构建（注入记忆 + 知识 + tools）
│   └── context_builder.py   # 滚动上下文窗口管理
├── memory/
│   ├── short_term.py        # 本地 .md 快照读写
│   ├── long_term.py         # Obsidian vault 文件读写
│   └── recall.py            # 混合召回（关键词 + 向量）
├── plugins/
│   ├── manifest.py          # App Manifest 解析与校验
│   ├── knowledge.py         # 知识库索引与检索
│   ├── tools_registry.py    # Tools 注册与执行
│   └── skill.py             # Skill（提示词模板）加载
├── extraction/
│   ├── detector.py          # 从流式输出中识别可提取内容
│   └── router.py            # 提取内容路由（存记忆 / 传功能模块）
└── db/
    ├── schema.py             # SQLite 建表
    └── queries.py            # 常用查询封装
```

### 3.2 核心 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/stream` | 流式对话（SSE），接受 appId + messages + context |
| GET  | `/api/v1/sessions` | 会话列表（支持 appId 过滤） |
| POST | `/api/v1/sessions` | 新建会话 |
| GET  | `/api/v1/sessions/{id}/messages` | 历史消息 |
| POST | `/api/v1/memory/recall` | 主动召回记忆 |
| POST | `/api/v1/memory/save` | 保存记忆片段 |
| GET  | `/api/v1/apps` | 已注册的 App 列表 |
| GET  | `/api/v1/apps/{appId}/manifest` | App Manifest 详情 |

### 3.3 流式对话数据流

```
POST /api/v1/chat/stream
    │
    ├─ 1. 解析 appId → 加载 App Manifest
    │
    ├─ 2. 召回记忆（短期 .md + 长期 Obsidian）
    │
    ├─ 3. 检索知识库（App 挂载的知识索引）
    │
    ├─ 4. 构建提示词
    │       system = platform_base + skill_prompt + memory_snippets + knowledge_snippets
    │       user   = 当前消息
    │
    ├─ 5. 调用 LLM Provider，流式迭代 chunks
    │       ├─ 实时解析 Artifact fence → yield artifact_event
    │       ├─ 实时解析 Think block   → yield think_event
    │       └─ 普通文本               → yield text_event
    │
    ├─ 6. 完成后：保存消息到 SQLite
    │
    └─ 7. 异步：触发内容提取器，识别可存入记忆的内容
```

---

## 四、SSE 事件协议

所有流式事件格式统一为：

```
data: {"type": "<event_type>", "payload": {...}}\n\n
```

| event_type | payload | 说明 |
|------------|---------|------|
| `text` | `{"delta": "..."}` | 普通文本增量 |
| `think` | `{"delta": "...", "done": bool}` | 思考过程文本 |
| `artifact` | `{"id": "...", "lang": "...", "delta": "...", "done": bool}` | Artifact 内容增量 |
| `stage` | `{"name": "...", "state": "active\|done\|error"}` | 阶段进度 |
| `memory` | `{"snippets": [...]}` | 本次召回的记忆摘要（展示用） |
| `error` | `{"message": "..."}` | 错误 |
| `done` | `{}` | 流结束 |

---

## 五、数据库 Schema（SQLite）

```sql
-- 会话
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,
    app_id      TEXT NOT NULL,
    title       TEXT,
    created_at  INTEGER,
    updated_at  INTEGER
);

-- 消息
CREATE TABLE messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,   -- user | assistant | system
    content     TEXT NOT NULL,
    metadata    TEXT,            -- JSON: artifacts, stage_log, etc.
    created_at  INTEGER
);

-- 知识库片段
CREATE TABLE knowledge_chunks (
    id          TEXT PRIMARY KEY,
    app_id      TEXT NOT NULL,
    source_path TEXT,
    content     TEXT NOT NULL,
    embedding   BLOB,
    chunk_index INTEGER,
    created_at  INTEGER
);

-- 记忆条目（短期）
CREATE TABLE memory_items (
    id          TEXT PRIMARY KEY,
    app_id      TEXT,            -- NULL 表示全局
    category    TEXT,            -- preference | fact | project | feedback
    content     TEXT NOT NULL,
    source      TEXT,            -- session_id / manual
    embedding   BLOB,
    created_at  INTEGER
);
```

---

## 六、环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_PROVIDER` | `openai_compatible` | `openai_compatible` \| `mock` |
| `LLM_BASE_URL` | — | OpenAI 兼容 API 地址 |
| `LLM_API_KEY` | — | API 密钥 |
| `LLM_MODEL` | — | 模型名称 |
| `PLATFORM_DATA_DIR` | `~/.llm-platform` | 用户数据根目录 |
| `PLATFORM_APPS_DIR` | `./apps` | App Manifest 目录 |
| `PLATFORM_HOST` | `127.0.0.1` | 后端监听地址 |
| `PLATFORM_PORT` | `8765` | 后端监听端口 |
