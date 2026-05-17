# 记忆系统设计

## 一、概览

```
┌─────────────────────────────────────────────────────────┐
│                     记忆系统                             │
│                                                         │
│  ┌─────────────────────┐   ┌─────────────────────────┐  │
│  │     短期记忆         │   │       长期记忆            │  │
│  │  ~/.llm-platform/   │   │   Obsidian Vault         │  │
│  │  memory/short-term/ │   │   （用户指定路径）         │  │
│  └─────────────────────┘   └─────────────────────────┘  │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐│
│  │              召回引擎（Recall Engine）               ││
│  │   关键词匹配（BM25） + 向量相似度 → 混合排序         ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

---

## 二、存储结构

### 2.1 短期记忆（本地 .md 文件）

位置：`~/.llm-platform/memory/short-term/`

```
~/.llm-platform/
├── config.json                        # 全局配置（含 Obsidian vault 路径）
├── memory/
│   ├── short-term/
│   │   ├── sessions/
│   │   │   └── {session_id}.md        # 每次会话结束后的摘要快照
│   │   ├── user-preferences.md        # 用户偏好（交互习惯、语言风格等）
│   │   └── quick-facts.md             # 快速事实（频繁引用的简短信息）
│   └── obsidian-config.json           # Obsidian 连接配置
└── apps/
    └── {app_id}/
        └── settings.json              # 应用级配置
```

**会话快照格式**（`{session_id}.md`）

```markdown
---
session_id: abc123
app_id: my-app
title: 讨论数据库优化方案
created_at: 2026-05-17T10:30:00
tags: [数据库, 性能优化, PostgreSQL]
---

## 摘要
用户讨论了 PostgreSQL 慢查询问题，最终决定为 orders 表的 user_id 列添加复合索引。

## 关键决策
- 选择 B-tree 索引而非 Hash 索引，原因：支持范围查询
- 暂缓分区表方案，待数据量达到 1000 万行后再评估

## 提取的知识
- orders 表当前数据量：约 300 万行
- 主要慢查询：按用户 ID + 时间范围过滤订单列表
```

### 2.2 长期记忆（Obsidian Vault）

Obsidian vault 路径由用户在 `~/.llm-platform/config.json` 中配置。

**约定的目录结构**（平台在 vault 内创建并维护）：

```
{obsidian_vault}/
└── llm-platform/                      # 平台专用目录（不污染用户其他笔记）
    ├── user/
    │   ├── preferences.md             # 长期用户偏好
    │   └── profile.md                 # 用户背景（职业、技术栈等）
    ├── knowledge/
    │   ├── {topic}.md                 # 按主题归档的知识片段
    │   └── ...
    └── projects/
        └── {project_name}/
            ├── overview.md            # 项目概述
            ├── decisions.md           # 技术决策记录
            └── glossary.md            # 项目术语
```

**写入策略**：
- 平台**只读写** `llm-platform/` 子目录，不影响用户其他 Obsidian 笔记
- 每次写入前读取现有内容，追加而非覆盖（防止丢失已有笔记）
- 写入时机：用户手动触发（"存入记忆"按钮）或对话结束后的自动提炼（可配置开关）

---

## 三、记忆分类

| 类别 | 存储位置 | 示例内容 |
|------|----------|----------|
| `preference` | 短期 + 长期 | "用户偏好简洁回答，不喜欢过长引言" |
| `fact` | 短期 + 长期 | "项目使用 PostgreSQL 15，部署在 k8s" |
| `decision` | 长期 | "2026-05 决定不引入 GraphQL，保持 REST" |
| `feedback` | 短期 | "上次回答太详细，用户说太长了" |
| `session_summary` | 短期 | 会话摘要快照 |

---

## 四、召回引擎

### 4.1 触发时机

每次发送消息时，系统自动执行召回：
1. 取用户当前消息作为查询
2. 从短期记忆（.md 文件）召回最相关片段
3. 从长期记忆（Obsidian）召回最相关片段
4. 去重、截断，注入 system prompt

### 4.2 召回算法

```python
score = 0.35 * keyword_score + 0.65 * semantic_score

# keyword_score: BM25 变体，基于词频/逆文档频率
# semantic_score: 余弦相似度（需要配置 embedding 模型时启用）
# 未配置 embedding 时：退化为纯关键词匹配
```

召回限制：
- 短期记忆：最多 `4` 条
- 长期记忆：最多 `2` 条
- 语义相似度阈值：`0.50`（低于此值的向量匹配结果丢弃）

### 4.3 注入格式

注入到 system prompt 的末尾：

```
--- 相关记忆 ---
[用户偏好] 偏好简洁回答，代码示例要包含注释
[项目背景] 当前项目使用 PostgreSQL 15，部署环境为 Kubernetes
[上次讨论] 2026-05-15 讨论了索引优化，决定为 orders.user_id 添加复合索引
```

---

## 五、内容提取与写入记忆

### 5.1 手动提取（用户触发）

在对话中，用户可以：
1. **选中文字** → 右键菜单 → "存入记忆" → 选择类别
2. **点击 Artifact 操作栏** → "存入记忆" → Artifact 全文写入

### 5.2 自动提炼（对话结束后）

对话结束后（用户停止输入超过 5 分钟，或手动关闭会话），后台触发：
- 调用 LLM 对本次会话生成结构化摘要
- 按上述格式写入 `{session_id}.md`
- 识别新的 `fact` / `decision` 类型内容，追加到对应 Obsidian 文件

此功能默认**关闭**，用户可在设置中开启。

### 5.3 记忆审批（可选）

自动提炼的内容默认进入"待审批"队列，用户在侧栏的记忆管理页面确认后才真正写入。
（与 AI-KA 的 review_queue 机制同源）

---

## 六、配置文件格式

`~/.llm-platform/config.json`

```json
{
  "obsidian": {
    "vault_path": "/Users/grant/Documents/MyVault",
    "enabled": true,
    "auto_write": false,
    "write_approval": true
  },
  "memory": {
    "short_term_enabled": true,
    "auto_summarize": false,
    "max_recall_short": 4,
    "max_recall_long": 2,
    "semantic_threshold": 0.50
  },
  "embedding": {
    "enabled": false,
    "provider": "openai_compatible",
    "base_url": "",
    "model": ""
  }
}
```
