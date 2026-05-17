# 应用插件系统

## 一、核心概念

**一个"应用"= 一个 App Manifest**

平台本身不包含业务逻辑。每个应用通过一个 `manifest.json` 文件声明：
- 用什么**提示词模板**（Skill）
- 挂载哪些**知识库**（Knowledge）
- 可以调用哪些**工具**（Tools）
- 特有的 **UI 扩展**（如额外菜单项、自定义 Artifact 类型）

```
apps/
├── chat-assistant/           # 通用对话助手
│   └── manifest.json
├── doc-reviewer/             # 文档审查（AI-KA 的业务逻辑迁移至此）
│   ├── manifest.json
│   ├── skills/
│   │   └── review-domain.md
│   └── knowledge/
│       └── (indexed docs)
└── code-assistant/           # 代码助手
    └── manifest.json
```

---

## 二、App Manifest 格式

`apps/{app_id}/manifest.json`

```json
{
  "schema_version": "1.0",
  "id": "doc-reviewer",
  "name": "文档审查",
  "description": "基于知识库和审查规则的文档智能审查",
  "icon": "FileSearchOutlined",
  "version": "1.0.0",

  "ui": {
    "artifact_types": ["markdown", "table"],
    "composer_placeholder": "描述要审查的问题，或上传文档后直接发送...",
    "session_col_visible": true,
    "split_mode_default": true
  },

  "skill": {
    "system_prompt_file": "skills/review-domain.md",
    "focus_points": [
      {
        "id": "completeness",
        "name": "完整性检查",
        "prompt": "检查文档是否覆盖所有必要章节..."
      }
    ]
  },

  "knowledge": {
    "enabled": true,
    "index_dirs": [],
    "chunk_strategy": "structured",
    "chunk_size": 800
  },

  "tools": [
    "read_file",
    "search_knowledge",
    "extract_findings"
  ],

  "memory": {
    "recall_categories": ["preference", "fact", "project"],
    "auto_save_category": "fact"
  }
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | ✓ | 唯一标识，用于路由和数据隔离 |
| `name` | ✓ | 显示名称（侧栏菜单） |
| `icon` | — | Ant Design 图标名 |
| `ui.split_mode_default` | — | 默认是否开启 60/40 分屏 |
| `ui.artifact_types` | — | 此 App 可能产出的 Artifact 类型 |
| `skill.system_prompt_file` | — | 相对于 manifest.json 的路径 |
| `skill.focus_points` | — | 可选的焦点列表（用户在 Composer 选择） |
| `knowledge.index_dirs` | — | 相对路径列表，平台会索引这些目录 |
| `tools` | — | 引用 platform tools registry 中的 tool id |
| `memory.recall_categories` | — | 召回时过滤的记忆类别 |

---

## 三、Skill（提示词模板）

Skill 文件为 Markdown 格式，支持模板变量：

`apps/doc-reviewer/skills/review-domain.md`

```markdown
# 文档审查助手

你是一个专业的文档审查专家。

## 审查原则
- 检查文档的完整性、一致性和准确性
- 发现问题时给出具体的位置和改进建议
- 使用 [HIGH] / [MEDIUM] / [LOW] 标注问题严重程度

{{#if focus_points}}
## 本次审查重点
{{#each focus_points}}
- **{{name}}**：{{prompt}}
{{/each}}
{{/if}}

{{#if knowledge_snippets}}
## 参考知识
{{knowledge_snippets}}
{{/if}}
```

模板变量由 `prompt_builder.py` 在运行时填充：

| 变量 | 来源 |
|------|------|
| `{{focus_points}}` | 用户在 Composer 选择的焦点 |
| `{{knowledge_snippets}}` | 知识库召回结果 |
| `{{memory_snippets}}` | 记忆系统召回结果 |
| `{{open_findings}}` | 本会话已发现的问题列表 |

---

## 四、知识库（Knowledge）

### 索引流程

```
App 启动 / 用户触发重建索引
    ↓
扫描 knowledge.index_dirs 下的文档
    ↓
文件类型识别：
  .md / .txt    → 直接读取
  .pdf / .docx  → 调用 markitdown 转换
    ↓
按 chunk_strategy 切片（blank / structured）
    ↓
（可选）调用 embedding 模型生成向量
    ↓
写入 SQLite knowledge_chunks 表
```

### 检索

用户发送消息时，从 `knowledge_chunks` 中检索：
- BM25 关键词匹配（始终启用）
- 向量相似度（仅配置了 embedding 时启用）
- 结果注入 system prompt 的 `{{knowledge_snippets}}`

### 知识库管理 UI

Artifact 面板的"知识库"Tab（可选，App manifest 中声明）：
- 显示当前索引状态（文件数 / chunk 数 / 最后更新时间）
- 手动触发重建索引
- 预览 chunks 内容

---

## 五、Tools（工具）

### 平台内置 Tools

| Tool ID | 说明 |
|---------|------|
| `read_file` | 读取指定路径的文件内容 |
| `search_knowledge` | 在当前 App 的知识库中搜索 |
| `save_memory` | 将指定内容写入记忆系统 |
| `extract_findings` | 从当前对话中提取结构化发现（findings） |
| `write_file` | 写入文件（需显式权限） |

### 自定义 Tools

App 可在 `apps/{app_id}/tools/` 目录下添加自定义 Tool：

```python
# apps/doc-reviewer/tools/export_docx.py

TOOL_SPEC = {
    "id": "export_docx",
    "name": "导出 Word 文档",
    "description": "将审查结果导出为 .docx 格式",
    "parameters": {
        "findings": {"type": "array", "description": "发现的问题列表"},
        "output_path": {"type": "string", "description": "输出路径"}
    }
}

async def execute(findings: list, output_path: str) -> dict:
    # 实现导出逻辑
    ...
    return {"success": True, "path": output_path}
```

平台在启动时扫描并注册所有 App 的自定义 Tools。

---

## 六、内容提取路由

对话过程中，`extraction/detector.py` 实时扫描流式输出，识别可提取内容：

```
流式文本 chunk
    ↓
检测是否包含结构化内容标记：
  [HIGH] / [MEDIUM] / [LOW]    → FindingItem
  ## 决策 / ## 结论             → DecisionItem  
  - [ ] / - [x]                → TaskItem
  > 摘要：                      → SummaryItem
    ↓
yield extraction_event（类型 + 内容）
    ↓
前端：
  FindingItem  → FindingsPanel 右侧面板
  DecisionItem → 可存入 Obsidian decisions.md
  TaskItem     → 显示 Task 提取弹窗
  SummaryItem  → 可存入短期记忆
```

用户可在设置中自定义检测规则（正则 + 分类标签）。

---

## 七、App 切换行为

切换 App 时，平台执行：

1. 保存当前 App 的 Composer 状态（选中的知识库 / 焦点）
2. 加载新 App 的 manifest
3. 更新 Composer 工具栏（知识库按钮 / 焦点选择器是否显示）
4. 切换 SessionColumn 显示新 App 的会话历史
5. 若新 App `ui.split_mode_default: true` 且存在历史 Artifact，恢复分屏布局

会话数据按 `app_id` 隔离，各 App 互不干扰。
