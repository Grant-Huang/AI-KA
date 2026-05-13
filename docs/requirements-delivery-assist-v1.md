# 需求文档：AI 交付辅助三件套

**版本**：v1.0  
**日期**：2026-05-12  
**背景**：公司主营 MES/MOM 解决方案实施业务（项目型），存在上线后周期过长、方案质量参差、知识难沉淀等结构性问题。本文档定义三个 AI 辅助工具，嵌入现有交付流程的强制门控节点（Gate），以对话模式驱动，复用 AI-KA 现有对话、索引、流式输出基础设施。

---

## 一、整体定位

```
交付流程门控节点：

  [蓝图确认] ──── Gate 1：AI 产品匹配度报告  ← 本文档 Feature 1
       ↓                   （蓝图提交前必须完成）
  [二次开发] ──── Gate 2：AI 二开合规扫描    ← 本文档 Feature 2
       ↓                   （代码提交前必须完成）
  [项目验收] ──── Gate 3：AI 结构化复盘      ← 本文档 Feature 3
                           （验收申请前必须完成）
```

三个功能共用 AI-KA 的：对话引擎、文档索引、SSE 流式输出、Finding 结构、记忆写入机制。区别仅在系统提示框架、输入类型、输出结构。

---

## 二、Feature 1：AI 产品匹配度报告（Blueprint Match Report）

### 2.1 场景描述

实施顾问完成蓝图初稿后，提交蓝图文档，AI 对比公司产品功能知识库，输出结构化「产品匹配度报告」。顾问必须附上此报告，方可申请蓝图款。

**解决问题**：
- 方案中把标准配置项误列为二开需求（增加开发量、延长工期）
- 方案未充分利用产品已有功能特性
- 不同顾问对产品能力掌握深度差异大

### 2.2 输入

| 输入项 | 说明 |
|---|---|
| 蓝图文档 | 上传的 Word/Markdown，已有文档索引时可直接选择 |
| 产品功能知识库 | 系统内置，维护于 `<repo>/.aika/product-features/`，支持管理员更新 |
| 行业模板（可选） | 顾问选择行业（制造/离散/流程等），加载对应的评审权重 |

### 2.3 对话流程

```
[第 1 轮：全局扫描]
AI 读取蓝图，逐模块输出：
  - 该模块需求描述（摘要）
  - 匹配结论：标准功能 / 需配置 / 需二开 / 产品不支持
  - 匹配置信度：high / medium / low
  - 建议（若误判为二开则给出标准配置路径）

[第 2 轮：追问与澄清]
顾问可针对具体条目追问：
  "第3条需求，客户的要求是X，你说标准功能能满足，具体怎么配置？"
AI 回答具体配置路径，顾问根据回答决定是否修改方案。

[第 3 轮：生成报告]
顾问确认后，AI 汇总生成正式「产品匹配度报告」（结构化 Markdown，可导出 Word）。
```

### 2.4 输出结构（MatchFinding）

```typescript
interface MatchFinding {
  id: string;                  // mf-001
  module: string;              // 蓝图模块名
  requirement: string;         // 需求描述（摘要）
  match_type: "standard" | "config" | "custom_dev" | "not_supported";
  confidence: "high" | "medium" | "low";
  product_feature_ref?: string;  // 关联产品功能条目 ID
  standard_config_path?: string; // 若可标准配置，给出配置路径
  dev_complexity?: "simple" | "medium" | "complex";  // 若确需二开，复杂度预估
  risk_note?: string;            // 风险备注（如可能影响升级）
  status: "open" | "confirmed" | "revised";
}
```

报告摘要：
- 总需求条数 / 标准满足数 / 配置满足数 / 需二开数 / 不支持数
- 产品利用率分数（标准+配置 / 总数）
- 高风险二开条目列表

### 2.5 产品功能知识库维护

```
<repo>/.aika/product-features/
  ├── core/              # 核心功能模块
  │   ├── production-scheduling.md
  │   ├── material-tracking.md
  │   └── quality-management.md
  ├── extensions/        # 扩展配置项
  └── industry/          # 行业特化功能
      ├── discrete.md
      └── process.md
```

每个文件格式：
```markdown
---
module: production-scheduling
version: "3.2"
---
## 功能列表
### feat-001：工单自动下达
支持按计划自动触发工单，配置项：触发条件（时间/物料到位/上工序完工）
适用：所有行业
配置路径：系统参数 → 生产配置 → 工单触发策略
...
```

管理员通过「产品知识库管理」页面更新，更新后自动重建索引。

---

## 三、Feature 2：AI 二开合规扫描（Dev Compliance Scan）

### 3.1 场景描述

开发人员提交二次开发代码前，通过 AI 扫描，检查代码是否符合产品扩展规范，是否存在可复用的已有组件未被使用。形成「合规扫描报告」，作为代码 Review 的前置条件。

**解决问题**：
- 二开代码不符合产品扩展规范，导致产品升级时大规模冲突（这是上线后维护周期长的重要原因）
- 重复实现已有内部组件，代码复用率低
- 代码质量参差不齐，与产品架构风格不一致

### 3.2 输入

| 输入项 | 说明 |
|---|---|
| 代码文件 | 上传或粘贴，支持 Java/Python/JavaScript 等 |
| 需求说明 | 本次二开要实现的业务需求（用于上下文理解） |
| 合规规则包 | 系统内置，维护于 `<repo>/.aika/dev-rules/`，技术架构师维护 |
| 内部组件库索引 | 已有二开沉淀的组件清单，支持相似度检索 |

### 3.3 对话流程

```
[第 1 轮：合规扫描]
AI 读取代码，逐项输出：
  - 规则违反情况（按合规规则包逐条）
  - 可复用组件发现（"此逻辑已有内部组件 X 实现，建议复用"）
  - 产品升级风险点（直接侵入产品核心代码的位置）

[第 2 轮：开发者追问]
开发者可就具体问题追问：
  "你说这里应该用扩展点 Y，能给我看个实现示例吗？"
AI 基于合规规则包和内部组件库，提供具体代码建议。

[第 3 轮：修改确认]
开发者修改后可再次提交代码片段，AI 针对性复查。
```

### 3.4 输出结构（ComplianceFinding）

```typescript
interface ComplianceFinding {
  id: string;                 // cf-001
  file: string;               // 文件名（或代码片段标识）
  line_range?: string;        // 行号范围（如有）
  rule_id: string;            // 违反的规则 ID
  severity: "blocker" | "major" | "minor" | "suggestion";
  description: string;        // 问题描述
  suggestion: string;         // 修改建议
  reusable_component?: string; // 可复用的内部组件（如有）
  upgrade_risk: boolean;       // 是否存在升级兼容风险
  status: "open" | "fixed" | "accepted_risk";
}
```

报告摘要：
- Blocker 数 / Major 数 / Minor 数（Blocker 必须归零才能通过）
- 升级风险条目数
- 复用建议条目数（量化复用机会）

### 3.5 合规规则包维护

```
<repo>/.aika/dev-rules/
  ├── extension-points.md     # 产品扩展点规范（必须走哪些扩展接口）
  ├── forbidden-patterns.md   # 禁止改动的核心区域
  ├── code-style.md           # 代码风格规范
  └── reusable-components.md  # 内部已沉淀组件清单（含描述和使用方式）
```

技术架构师维护，更新后自动生效（无需重新部署）。

---

## 四、Feature 3：AI 结构化复盘（Project Retrospective）

### 4.1 场景描述

项目提交验收申请前，实施顾问和项目经理通过 AI 引导的多轮对话，完成结构化项目复盘。复盘产出：
1. 项目复盘报告（归档）
2. 知识条目（写入组织知识库，供后续项目复用）
3. 改进建议（推送至流程改进队列）

**解决问题**：
- 项目经验不沉淀，下个项目从零踩坑
- 资深顾问的经验无法传递给新人
- 上线后周期长的根因没有被系统记录和分析

### 4.2 复盘维度框架

AI 按以下六个维度依次引导对话（每个维度 2-4 轮），顾问可跳过不相关维度：

| 维度 | 核心问题 | 输出 |
|---|---|---|
| **时间复盘** | 计划 vs 实际各阶段工期，最大偏差发生在哪里？ | 工期偏差分析 |
| **方案质量** | 蓝图确认后有多少次方案变更？变更根因是什么？ | 方案稳定性评分 |
| **产品利用** | 实际二开量 vs 当初估计？哪些二开事后看可以用标准功能？ | 产品利用率回溯 |
| **客户协作** | 客户配合度、需求变更频率、关键决策节点有无延误？ | 客户协作评分 |
| **团队执行** | 哪些环节执行顺畅？哪些出现了问题？人员能力有哪些短板？ | 团队能力记录 |
| **可复用知识** | 这个项目有什么踩坑/最佳实践，下次同类项目应该注意什么？ | **→ 写入知识库** |

### 4.3 对话设计

复盘对话采用「资深顾问追问模式」（参见 design-knowledge-extraction-v2.md 第六节），AI 主动追问，不只等待顾问填表：

```
[时间复盘维度示例对话]

AI：我看到这个项目的蓝图确认耗时 45 天，计划是 20 天。
    您觉得主要延误在哪个环节？

顾问：客户那边决策层一直在变，方案改了 3 次。

AI：这 3 次方案变更，是因为客户需求本身变了，
    还是我们的初版方案没有准确把握客户意图？

顾问：两个都有，主要是第一次调研只拜访了一个部门，
    遗漏了仓储部门的需求。

AI：好，我记录下来：「调研覆盖不全导致蓝图返工」。
    您认为这是这个项目的特殊情况，还是一个我们可以
    预防的系统性问题？

顾问：我觉得可以系统性预防，以后调研应该有个强制核查清单
    确保覆盖所有相关部门。

AI：这是一条有价值的改进建议，我把它标记为「可提炼为流程规则」，
    您待会确认后可以提交到规则库。
```

### 4.4 输出结构

**复盘报告（归档）**：
```typescript
interface RetrospectiveReport {
  project_id: string;
  project_name: string;
  industry: string;
  duration_planned_days: number;
  duration_actual_days: number;
  
  dimensions: {
    timeline: TimelineReview;
    blueprint_quality: BlueprintQualityReview;
    product_utilization: ProductUtilizationReview;
    client_collaboration: ClientCollaborationReview;
    team_execution: TeamExecutionReview;
  };
  
  knowledge_items: RetrospectiveKnowledgeItem[];  // 提炼出的可复用知识
  process_improvement_suggestions: string[];       // 推送至流程改进队列
  
  overall_health_score: number;  // 0-100，供管理层横向对比
  created_at: string;
  participants: string[];
}
```

**知识条目**（写入组织知识库）：

```typescript
interface RetrospectiveKnowledgeItem {
  id: string;
  category: "risk_pattern" | "best_practice" | "anti_pattern" | "process_rule";
  title: string;
  content: string;           // IF-THEN 格式
  applicable_industries: string[];
  applicable_project_types: string[];
  source_project: string;    // 匿名化后的来源项目
  confidence: "high" | "medium" | "low";
  status: "pending_review" | "approved";  // 需知识管理员审批后进 Active
}
```

### 4.5 与知识提取系统集成

复盘中产出的 `RetrospectiveKnowledgeItem` 直接进入 Review Queue（参见 design-knowledge-extraction-v2.md），流转路径：

```
复盘对话 → RetrospectiveKnowledgeItem（trust: high）
                    ↓
             Review Queue（status: candidate）
                    ↓
         资深顾问知识提取入口审核（Phase 1 Q&A）
                    ↓
              Pending Rule Pool
                    ↓
           知识管理员审批 → Active Rule
```

---

## 五、UI 设计

### 5.1 导航扩展

在现有「项目审查」模式下，新增三个子入口（侧边二级导航）：

```
项目审查模式：
  [+]    新审查会话
  [💬]   审查历史
  ──
  [📁]   项目初始化
  [🔍]   审查域设定
  ──  ← 新增分隔线
  [📊]   产品匹配度报告   ← Feature 1
  [🔎]   二开合规扫描     ← Feature 2
  [📋]   项目复盘         ← Feature 3
```

三个功能复用现有主内容区对话界面，仅 Finding 面板样式不同。

### 5.2 各功能 Finding 面板差异

| 属性 | 审查 Finding | 匹配度报告 | 合规扫描 | 复盘 |
|---|---|---|---|---|
| 颜色体系 | 高/中/低风险 | 标准/配置/二开/不支持 | Blocker/Major/Minor | 维度分类 |
| 核心操作 | 标记状态 | 确认匹配结论 | 标记已修复/接受风险 | 确认知识条目 |
| 报告导出 | 审查报告 | 产品匹配度报告 | 合规扫描报告 | 复盘报告 + 知识条目 |

### 5.3 Gate 标记

每个门控功能完成后，在项目状态面板显示通过标记：

```
项目：XX制造MES实施
  ✅ 产品匹配度报告  已完成 2026-03-15  产品利用率 78%
  ✅ 二开合规扫描    已完成 2026-04-20  Blocker: 0 / Major: 2
  ⏳ 项目复盘        待完成（验收申请前必须完成）
```

---

## 六、后端架构扩展

### 6.1 新增 ConversationMode 枚举值

```python
class ConversationMode(str, Enum):
    REVIEWING = "reviewing"        # 现有
    CLARIFYING = "clarifying"      # 现有
    REFINING = "refining"          # 现有
    GENERATING = "generating"      # 现有
    BLUEPRINT_MATCHING = "blueprint_matching"   # Feature 1
    CODE_SCANNING = "code_scanning"             # Feature 2
    RETROSPECTIVE = "retrospective"             # Feature 3
```

### 6.2 新增数据模型

```python
# web/backend/match_models.py
@dataclass
class MatchFinding:
    id: str
    module: str
    requirement: str
    match_type: str   # standard / config / custom_dev / not_supported
    confidence: str
    product_feature_ref: str | None
    standard_config_path: str | None
    dev_complexity: str | None
    risk_note: str | None
    status: str       # open / confirmed / revised

# web/backend/compliance_models.py
@dataclass
class ComplianceFinding:
    id: str
    file: str
    line_range: str | None
    rule_id: str
    severity: str     # blocker / major / minor / suggestion
    description: str
    suggestion: str
    reusable_component: str | None
    upgrade_risk: bool
    status: str       # open / fixed / accepted_risk

# web/backend/retrospective_models.py
@dataclass
class RetrospectiveKnowledgeItem:
    id: str
    category: str
    title: str
    content: str
    applicable_industries: list[str]
    applicable_project_types: list[str]
    source_project: str
    confidence: str
    status: str       # pending_review / approved
```

### 6.3 新增标记格式（复用 finding_parser.py 模式）

```
产品匹配：  <!-- match: {"module": "...", "type": "standard", ...} -->
合规问题：  <!-- compliance: {"rule_id": "...", "severity": "blocker", ...} -->
复盘知识：  <!-- retro-ki: {"category": "best_practice", "title": "...", ...} -->
复盘追问：  <!-- retro-clarify: ["问题1", "问题2"] -->
```

### 6.4 新增知识库目录

```
<repo>/.aika/
  ├── product-features/    # Feature 1：产品功能知识库（管理员维护）
  ├── dev-rules/           # Feature 2：二开合规规则包（架构师维护）
  └── retrospective/       # Feature 3：复盘报告归档 + 知识条目待审队列
      ├── reports/
      └── pending-knowledge/
```

---

## 七、实现计划

### Sprint 1：基础设施（2 周）
- 1-1：新增三个 `ConversationMode` 枚举值，FSM 支持对应跳转
- 1-2：`match_parser.py` / `compliance_parser.py` / `retro_parser.py`：各自的标记解析器
- 1-3：`product_knowledge_service.py`：产品功能知识库索引读取
- 1-4：`dev_rules_service.py`：合规规则包读取
- 1-5：新增三个 SSE 流式端点（骨架，复用 analyze/stream 结构）
- **验收**：mock provider 下三个端点可跑通，标记可解析

### Sprint 2：Feature 1 — 产品匹配度报告（2 周）
- 2-1：产品功能知识库目录结构 + 初始内容（核心模块 5 个，作为 POC）
- 2-2：Blueprint Matching 系统提示框架
- 2-3：`MatchFinding` 面板前端组件（类比 FindingsPanel）
- 2-4：匹配度报告导出（Markdown → Word）
- 2-5：产品利用率分数计算
- **验收**：上传一份真实蓝图，能产出可读的匹配度报告

### Sprint 3：Feature 2 — 二开合规扫描（2 周）
- 3-1：合规规则包目录结构 + 初始内容（禁止改动区域、扩展点规范）
- 3-2：Code Scanning 系统提示框架（含代码输入特殊处理）
- 3-3：`ComplianceFinding` 面板前端组件（Blocker 高亮）
- 3-4：代码输入方式：粘贴文本 + 文件上传（≤ 500 行/次）
- 3-5：合规扫描报告导出
- **验收**：提交一段故意违规的二开代码，能正确识别 Blocker

### Sprint 4：Feature 3 — 结构化复盘（3 周）
- 4-1：复盘六维度提示框架 + 追问逻辑
- 4-2：`RetrospectiveKnowledgeItem` 面板（含「提交至规则库」按钮）
- 4-3：满意度推进机制（复用 design-knowledge-extraction-v2.md 方案）
- 4-4：写入 Review Queue（trust: high）
- 4-5：复盘报告导出（含六维度摘要 + 健康度分数）
- 4-6：项目状态面板 Gate 标记
- **验收**：走通一个完整复盘对话，报告可导出，知识条目进 Review Queue

### Sprint 5：Gate 集成 + 管理后台（2 周）
- 5-1：项目状态面板显示三个 Gate 完成情况
- 5-2：产品知识库管理页面（管理员上传/更新功能文档）
- 5-3：合规规则包管理页面（架构师维护）
- 5-4：复盘知识条目审批界面（知识管理员）
- 5-5：横向对比看板（多项目健康度分数趋势）
- **验收**：完整走通一个项目的三个门控节点，管理员可维护规则

---

## 八、关键设计原则

### 8.1 对话优先，不是填表
三个功能都以多轮对话驱动，AI 主动提问，而不是给用户一张表格让他填。原因：顾问在对话中说出的比填表更真实、更完整，AI 也能在对话中动态追问，挖掘出填表无法获得的隐性信息。

### 8.2 Gate 必须有摩擦，但摩擦要有价值
门控节点的存在意义是让用户产生有价值的输出，而不是走流程拿个通过戳。设计时保证：每次 Gate 产出的报告，对顾问自己都是有用的（反思工具），而不只是管理层的监控工具。

### 8.3 知识库是活的，不是一次性输入
产品功能知识库、合规规则包随产品版本迭代。需要版本号管理，每次更新后重建索引，确保 AI 使用最新知识。

### 8.4 顾问是老师也是学生
- **作为学生**：顾问通过 AI 报告学习产品能力（"原来这个功能标准配置就能做"）、学习合规要求、学习历史项目踩坑
- **作为老师**：复盘中顾问陈述的经验，经 AI 提炼后进入组织知识库，让下一个顾问受益

这个双向设计是系统长期价值的核心：每次使用都在给系统喂知识，系统越用越聪明。
