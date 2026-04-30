# 设计文档：知识提取与隐性知识显化功能

**版本**：v0.1 草稿  
**日期**：2026-04-28  
**作者**：AI-KA 开发团队

---

## 一、背景与动机

AI-KA 当前功能以「项目文档审查」为核心：读入项目文档、围绕关注点分析、输出结构化发现。这套机制的底层能力——文档分块召回 + 多轮对话 + 结构化提取——同样适用于另一类高价值场景：

> **从非结构化/半结构化素材（会议纪要、访谈录音转写、操作 SOP、老员工经验陈述）中提取隐含知识，并将其系统化、可复用化。**

这正是「隐性知识（Tacit Knowledge）显化」的核心诉求——将只存在于人脑、无法直接检索的经验、判断规则、直觉转化为可记录、可传递、可迭代的显性知识。

---

## 二、与现有审查功能的关系

| 维度 | 项目审查（现有） | 知识提取（新建） |
|---|---|---|
| 目标 | 发现项目风险与问题 | 提炼、显化隐性知识 |
| 输入 | 项目文档（需求、蓝图、接口文档…） | 访谈记录、会议纪要、经验陈述、SOP草稿 |
| 关注点 | 风险、需求完整性、接口… | 知识类型（流程、判断规则、例外、背景…） |
| 输出 | 结构化「发现」（Finding） | 结构化「知识条目」（Knowledge Item） |
| 多轮会话目的 | 追问风险细节、更新发现状态 | 澄清模糊表述、挖掘深层逻辑、验证规则边界 |
| 记忆演化 | evolve-hint → 关注点改进 | 知识条目 → 个人/组织知识库 |

两套功能共用：文档索引与分块、embedding 召回、多轮上下文、SSE 流式输出、会话管理。  
区别主要在：**系统提示框架、输出结构、UI 展示侧重**。

---

## 三、UI 重构：左侧导航栏模式切换

### 3.1 现状

```
[+]  新对话
[💬] 审查历史
──
[📁] 项目初始化
[🔍] 审查域设定
      （空白）
[?]  帮助
[⚙]  设置
[👤] 用户
```

mainPanel 在 `"analyze" | "ingest" | "review_domain"` 三态切换。审查相关功能混合在同一平面。

### 3.2 目标结构：「模式」概念

引入顶层「应用模式（AppMode）」概念，左侧导航图标按模式分组：

```
[🔍] 项目审查  ←── 新增：模式图标，当前功能归入其下
[💡] 知识提取  ←── 新增：本文档的新功能
──
[?]  帮助
[⚙]  设置
[👤] 用户
```

每个模式图标点击后，主内容区切换为该模式的专属子视图（带自己的侧边二级导航）。

### 3.3 模式内部结构

**模式一：项目审查（现有功能打包）**

```
侧边二级区域：
  [+]    新审查会话
  [💬]   审查历史
  ──
  [📁]   项目初始化
  [🔍]   审查域设定

主内容区：
  当前 analyze / ingest / review_domain 三态
```

**模式二：知识提取（新功能）**

```
侧边二级区域：
  [+]    新提取会话
  [💬]   提取历史
  ──
  [📂]   素材管理
  [📚]   知识库浏览
  [⚙]    提取模板管理

主内容区：
  知识提取对话界面
```

---

## 四、知识提取功能详细设计

### 4.1 核心流程

```
用户上传素材文档
       ↓
索引与分块（复用现有 index-md + docs2md）
       ↓
选择「提取模板」（类似审查预设）
       ↓
多轮对话提取
  - 第一轮：全局梳理，按知识类型分类输出
  - 后续轮：聚焦追问（澄清/验证/反例挖掘）
       ↓
Knowledge Items 累积（类比 Findings）
       ↓
用户审核：确认/修改/合并/拒绝
       ↓
写入知识库（~/.aika/memory/ 或 <repo>/.aika/memory/）
       ↓
（可选）LLM 辅助结构化 → 生成 SOP / 规则文档
```

### 4.2 知识类型（Extraction Focus）

类比审查关注点，知识提取有自己的「提取维度」（ExtractionFocus）：

| id | 名称 | 描述 |
|---|---|---|
| `process` | 操作流程 | 步骤化、可重复执行的操作序列 |
| `rule` | 判断规则 | IF-THEN 形式的判断逻辑、业务规则 |
| `exception` | 例外情况 | "正常情况下…但如果…则…"的边界条件 |
| `background` | 背景知识 | 理解系统所需的前提假设与上下文 |
| `best_practice` | 最佳实践 | 从经验中沉淀出的有效做法 |
| `anti_pattern` | 反面案例 | 已知会出错或低效的做法 |
| `terminology` | 术语定义 | 领域专有名词、缩写、口语约定 |

用户可在「提取模板」中组合这些维度，形成针对特定场景的提取预设（如「运维交接知识提取」、「新员工入职知识整理」）。

### 4.3 Knowledge Item 数据结构

```typescript
interface KnowledgeItem {
  id: string;              // ki-001, ki-002...
  extraction_focus_id: string;  // "process" | "rule" | "exception" ...
  title: string;           // 条目标题（≤20字）
  content: string;         // 完整知识内容（结构化 Markdown）
  source_evidence: string; // 来源片段引用
  confidence: "high" | "medium" | "low";  // 提取置信度
  status: "pending" | "confirmed" | "revised" | "rejected";
  tags: string[];
  // 澄清追问生成
  clarification_questions?: string[];  // AI 建议的追问问题
}
```

后端存储：类比 Finding，通过 `message.metadata_json` 在 assistant 消息中携带，同时可导出到知识库文件。

### 4.4 LLM 系统提示框架（Extraction Prompt Architecture）

```
[角色]
你是一名知识工程师，专门从口述/非结构化文本中提取和显化隐性知识。

[任务]
对用户提供的素材，按指定的提取维度（ExtractionFocus）逐一分析，将隐含的流程、规则、例外和经验提炼为结构化知识条目。

[提取规则]
1. 每个值得记录的知识点，必须附上结构化标记：
   <!-- ki: {"focus": "rule", "title": "...", "confidence": "high", "evidence": "..."} -->
2. 对模糊表述主动提出澄清问题（最多3个）：
   <!-- clarify: ["问题1", "问题2"] -->
3. 区分「描述现象」和「说明规律」——只提取后者
4. 注意言下之意：说话人的停顿、「一般来说」「通常」「除非」等词汇往往暗示例外规则

[已提取条目]（避免重复）
{existing_knowledge_items}

[素材片段]
{document_chunks}
```

### 4.5 多轮对话策略

与审查功能类似，但重心不同：

| 轮次 | 审查功能 | 知识提取 |
|---|---|---|
| 第1轮 | 全局审查 → 发现列表 | 全局梳理 → 知识条目草稿 + 澄清问题 |
| 第2轮 | 追问风险细节 | 回答澄清问题 → 补充/修正知识条目 |
| 第3轮 | 更新发现状态 | 验证边界条件：「这个规则在X情况下还适用吗？」|
| 深度模式 | 自我批评：发现是否充分 | 自我批评：知识是否完整、有无矛盾 |

引入「追问引导模式」：AI 主动呈现 3 个建议追问，用户选择/修改后一键发送，降低用户思考成本。

### 4.6 知识库写入（与 Sprint 6 个人记忆集成）

提取完成后，AI 自动生成「知识写入建议」（类比 Sprint 6 的 memory suggestion）：

- **个人知识**（个人经验/偏好）→ 建议写入 `~/.aika/memory/`
- **项目知识**（项目特有规则/流程）→ 建议写入 `<repo>/.aika/memory/project/<id>/`
- **组织知识**（跨项目通用经验）→ 建议写入 `~/.aika/memory/` 下的专属目录

用户在「知识条目面板」中逐条确认写入，不自动写。

---

## 五、后端架构扩展

### 5.1 新增数据结构

```python
# web/backend/knowledge_models.py
@dataclass
class KnowledgeItem:
    id: str
    extraction_focus_id: str
    title: str
    content: str
    source_evidence: str
    confidence: str  # "high" | "medium" | "low"
    status: str      # "pending" | "confirmed" | "revised" | "rejected"
    tags: list[str]
    clarification_questions: list[str]

@dataclass
class ExtractionFocus:
    id: str
    name: str
    prompt: str  # 与 FocusPoint 同构，直接复用 focus_point_io.py
```

### 5.2 新增 API 端点

```
# 提取会话（复用现有 conversations 表，通过 mode 字段区分）
POST /api/v1/projects/{pid}/conversations             # 已有，mode="extracting"
POST /api/v1/projects/{pid}/conversations/{cid}/extract/stream  # 新增，类比 analyze/stream

# 知识条目管理
GET  /api/v1/projects/{pid}/conversations/{cid}/knowledge-items
PATCH /api/v1/projects/{pid}/conversations/{cid}/knowledge-items/{kid}
POST  /api/v1/projects/{pid}/conversations/{cid}/knowledge-items/{kid}/commit  # 写入记忆

# 提取模板（复用 skill packages 机制）
GET  /api/v1/extraction-templates
POST /api/v1/extraction-templates/{tid}/focus-points/migrate
```

### 5.3 复用现有基础设施

| 组件 | 复用方式 |
|---|---|
| `db.py` | conversations/messages 表，mode 字段加 "extracting" 枚举值 |
| `context_builder.py` | `build_rolling_context()` 直接复用 |
| `embedding_service.py` | 素材文档 embedding 完全复用 |
| `finding_parser.py` | 类比新建 `ki_parser.py`，提取 `<!-- ki: ... -->` 标记 |
| `conversation_fsm.py` | 新增 `ConversationMode.EXTRACTING` |
| `personal_memory.py` | `add_memory_suggestion()` 直接复用 |
| `focus_point_io.py` | ExtractionFocus 与 FocusPoint 同构，共用文件格式 |

---

## 六、前端设计

### 6.1 组件结构

```
AppMode selector (侧边栏图标)
├── ReviewMode（项目审查）
│   ├── 现有全部 UI 不变
│   └── side-nav 二级：[+新对话] [💬历史] [📁项目初始化] [🔍审查域]
└── ExtractionMode（知识提取）
    ├── ExtractionComposer（输入区）
    │   ├── 追问引导面板（建议问题 chips）
    │   └── 深度模式 toggle（同审查功能）
    ├── KnowledgeItemsPanel（知识条目面板）
    │   ├── 按 ExtractionFocus 分组显示
    │   ├── 每条：标题 + 内容折叠 + 置信度标签
    │   └── 操作：确认 / 修改 / 拒绝 / 写入记忆
    └── ClarificationPanel（待澄清问题列表）
        └── 点击问题 → 自动填入输入框
```

### 6.2 KnowledgeItemsPanel 与 FindingsPanel 对比

| 属性 | FindingsPanel | KnowledgeItemsPanel |
|---|---|---|
| 颜色体系 | 高/中/低风险（红/橙/绿） | 流程/规则/例外… 各一色 |
| 状态流转 | open → acknowledged → resolved | pending → confirmed / revised / rejected |
| 核心操作 | 标记已知、标记已解决 | 确认、编辑内容、写入记忆 |
| 报告生成 | 生成审查报告 | 生成知识文档（SOP / 知识库条目） |

### 6.3 状态管理扩展

```typescript
// 新增 AppMode 概念
type AppMode = "review" | "extraction";
const [appMode, setAppMode] = useState<AppMode>("review");

// 知识提取专有状态
const [knowledgeItems, setKnowledgeItems] = useState<KnowledgeItem[]>([]);
const [pendingClarifications, setPendingClarifications] = useState<string[]>([]);
const [extractionTemplate, setExtractionTemplate] = useState<string>("general");
```

---

## 七、实现路径（推荐 Sprint 划分）

### Sprint A：UI 重构（导航栏模式切换）
- A-1：引入 `AppMode` 类型，左侧栏拆为 Review / Extraction 两个模式图标
- A-2：现有审查功能归入 Review 模式，原有行为零改动
- A-3：Extraction 模式占位（空内容区）
- **验收**：切换图标不影响审查功能

### Sprint B：知识提取后端基础
- B-1：`knowledge_models.py` — KnowledgeItem, ExtractionFocus dataclasses
- B-2：`ki_parser.py` — 提取 `<!-- ki: ... -->` 和 `<!-- clarify: ... -->` 标记
- B-3：`extract/stream` SSE 端点（复用 analyze/stream 骨架）
- B-4：ConversationMode 增加 "extracting"，conversations 表 mode 枚举扩展
- **验收**：mock provider 返回可解析的 ki 标记

### Sprint C：知识提取前端对话
- C-1：`ExtractionComposer` 组件（输入区 + 追问建议 chips）
- C-2：`KnowledgeItemsPanel` 组件（类比 FindingsPanel）
- C-3：SSE `ki` / `clarify` 事件处理
- C-4：知识条目状态管理（confirm/revise/reject）
- **验收**：端到端对话流程可运行（mock LLM）

### Sprint D：知识写入与记忆集成
- D-1：`/knowledge-items/{id}/commit` 端点 → 调用 `add_memory_suggestion()`
- D-2：前端「写入记忆」按钮，触发 commit，显示建议队列入口
- D-3：提取模板（ExtractionFocus 文件，复用 focus-points/ 格式）
- **验收**：知识条目可写入 `~/.aika/memory/`

### Sprint E：深度提取模式
- E-1：深度模式下的自我批评 pass（「此知识条目是否完整/有矛盾？」）
- E-2：LLM 辅助生成知识文档（SOP / 规则表格）
- E-3：知识条目演化（`evolve-hint` 机制复用）

---

## 八、关键设计决策与权衡

### 决策 1：共用 conversations 表 vs 独立表
**选择**：共用，通过 `mode` 字段区分。  
**理由**：避免重复基础设施；历史记录和权限管理统一；会话上下文逻辑可复用。  
**代价**：mode 枚举扩大，需注意对现有查询的向后兼容。

### 决策 2：ExtractionFocus 与 FocusPoint 共用文件格式
**选择**：同构，均使用 `focus-*.md` + YAML frontmatter，放在独立的 `extraction-focuses/` 目录。  
**理由**：`focus_point_io.py` 零改动复用；CLI 命令 `aika skill evolve` 可直接演化提取维度。  
**代价**：需在 UI 上区分「审查关注点」和「提取维度」，避免混淆。

### 决策 3：追问建议的生成时机
**选择**：在每轮 LLM 响应完成后，从 `<!-- clarify: [...] -->` 标记中实时解析，不做单独 LLM 调用。  
**理由**：节省 token；让 LLM 在同一次输出中自然生成，质量更高。  
**代价**：LLM 必须严格遵守 `<!-- clarify: ... -->` 格式，需在系统提示中强制要求。

### 决策 4：知识写入的用户控制
**选择**：永不自动写入，必须用户显式「确认」。  
**理由**：与 Sprint 6 personal memory 设计一致；知识质量需人工把关。  
**代价**：增加操作步骤，需设计好 UX 降低摩擦（批量确认、默认确认等）。

---

## 九、与审查功能的数据流对比

```
审查功能：
文档 → 分块 → [系统提示:审查框架] → LLM → Markdown + <!-- finding: {...} --> → FindingsPanel

知识提取：
素材 → 分块 → [系统提示:提取框架] → LLM → Markdown + <!-- ki: {...} --> 
                                                       + <!-- clarify: [...] -->
                                             ↓
                                    KnowledgeItemsPanel + ClarificationPanel
                                             ↓
                                    用户确认 → 写入 memory suggestion → 个人/项目知识库
```

---

## 十、未来扩展方向

1. **知识图谱**：将 KnowledgeItems 构建成图结构（实体-关系），支持「这个规则和哪些流程相关？」类查询
2. **知识冲突检测**：新提取的规则与已有知识库条目矛盾时自动提示
3. **跨项目知识迁移**：「此项目的经验哪些可复用到其他项目？」
4. **知识健康度监控**：知识条目的访问频率、更新频率、置信度趋势
5. **团队知识共享**：`<org>/.aika/shared-memory/` 组织级知识层（需要权限管理）
