# 设计文档：知识提取系统 v2

**版本**：v2.0  
**日期**：2026-05-12  
**基于**：v0.1 草稿 + 架构评审补充  

---

## 一、架构定位重申

### 1.1 两个入口，职责分离

| 入口 | 访问者 | 记忆写入目标 | 泛化知识去向 |
|---|---|---|---|
| 项目审查 | 所有顾问 | 项目专属记忆 `<repo>/.aika/memory/project/` | 自动打标进 Review Queue（不直接写规则） |
| 知识提取 | **仅资深顾问** | Pending Rule Pool | 经审核后写入 skill package |

**核心原则**：项目审查是「使用环境」，它不修改规则，只沉淀项目事实。规则的演化路径唯一：`Review Queue → 知识提取对话 → Pending → 审核 → Active`。

### 1.2 gen-hint：两个入口之间的信号桥梁

审查会话中，LLM 遇到可泛化的模式时，在响应流中内嵌标记（不展示给顾问）：

```
<!-- gen-hint: {
  "category": "pm_method",
  "raw": "需求变更频繁时项目经理未设立变更委员会，导致范围蔓延",
  "signal_type": "anti_pattern",
  "project_type_hint": "contract",
  "trust": "low"
} -->
```

后端解析后写入 `review_queue.json`。普通顾问的审查会话产生 `trust: low`，资深顾问产生 `trust: medium`。**gen-hint 永远不直接修改规则**。

---

## 二、三层权威模型

### 2.1 角色定义

```
知识管理员（Admin）
  ├── 审批 / 拒绝 Pending Rule
  ├── 配置提取模板与规则回测
  └── 查看全局 Review Queue 和污染风险报告

资深顾问（Senior Consultant）
  ├── 访问知识提取入口（唯一拥有此权限）
  ├── Q&A 会话 → 产出 KnowledgeItem → 进 Pending
  ├── 主动提交规则文档 → 进 Pending
  ├── 审查后追问（Post-Review Extraction）
  └── 审查会话的 gen-hint trust = "medium"

普通顾问（Regular Consultant）
  ├── 项目审查（只读规则）
  ├── 标记 Finding 状态（finding-feedback 信号）
  └── 审查会话的 gen-hint trust = "low"
```

### 2.2 强制 Pending 机制

**即使资深顾问直接陈述的知识，也必须先进 Pending，不得直接覆盖 Active 规则。**

原因：
- 顾问有行业偏见（零售经验 ≠ 金融规则）
- 新规则可能与现有规则冲突
- 需要 LLM 辅助冲突检测

Pending 状态流转：
```
gen-hint / Q&A输出 / 文档提交
        ↓
  Pending Rule Pool
    ├─ LLM 自动冲突检测
    ├─ 与现有规则对比差异展示
    └─ 知识管理员（或另一资深顾问）审批
        ↓
   Active Rule（写入 skill package）
```

---

## 三、信号分层与 evolve-hint 污染隔离

### 3.1 三类信号权重表

| 信号类型 | 来源 | 路径 | 权重 | 能否直接改规则 |
|---|---|---|---|---|
| `gen-hint`（审查自动产生） | 任何顾问的审查会话 | → Review Queue | low / medium | 否 |
| `expert-submission`（专家主动提交） | 资深顾问 Q&A 或文档 | → Pending | high | 否（需审批） |
| `finding-feedback`（发现状态标记） | 任何顾问 | → Finding 置信度调整 | 影响发现，不影响规则 | 否 |

### 3.2 evolve-hint 污染隔离规则

现有问题：LLM 在审查过程中自生成 evolve-hint，若普通顾问的项目导向错误分析，evolve-hint 会积累为「错误方向的改进建议」。

解决方案：

1. **按会话角色打信任戳**：`trust: low`（普通顾问）、`trust: medium`（资深顾问审查）、`trust: high`（资深顾问知识提取）
2. **Review Queue 聚合去噪**：同类 gen-hint 需达到阈值（如 3 个 medium 或 5 个 low）才提升为「提取候选」
3. **知识管理员定期污染审计**：系统统计各信号来源分布，若某普通顾问产生的 low-trust gen-hint 占比异常高，触发警告

---

## 四、Review Queue 数据结构

```python
@dataclass
class ReviewQueueItem:
    id: str                        # rq-001, rq-002...
    source_type: str               # "gen_hint" | "expert_qa" | "doc_submission"
    source_session_id: str         # 来源会话 ID
    source_project_id: str         # 来源项目（gen_hint 专有）
    category: str                  # "industry_pattern" | "pm_method" | "product_pattern"
                                   # | "risk_signal" | "anti_pattern" | "process_rule"
    raw_text: str                  # 原始提取文本
    context_snippet: str           # 来源上下文（便于专家理解）
    trust: str                     # "low" | "medium" | "high"
    occurrence_count: int          # 相似信号聚合次数
    expert_domain_tags: list[str]  # 关联专家领域（用于分发给对应专家）
    status: str                    # "raw" | "candidate" | "in_extraction" | "promoted" | "dismissed"
    created_at: str
    promoted_to_pending_id: str | None
```

---

## 五、专家画像

资深顾问首次访问知识提取时，LLM 根据当前 Review Queue 内容的 category 分布，动态生成领域选项（多选框）：

```json
// ~/.aika/expert-profile.json
{
  "user_id": "consultant_001",
  "display_name": "张顾问",
  "domains": ["manufacturing_mes", "pm_contract", "product_blueprint"],
  "seniority": "senior",
  "profile_updated_at": "2026-05-12T10:00:00Z",
  "extraction_preferences": {
    "max_items_per_session": 10,
    "auto_advance_threshold": 0.75
  }
}
```

下次进入知识提取时，自动按专家领域过滤 Review Queue，仅展示匹配条目。

---

## 六、LLM 提问策略

这是整个系统的知识引擎，v0.1 没有展开，本节完整设计。

### 6.1 四种核心策略及触发条件

| 策略 | 触发信号 | 示例问题 |
|---|---|---|
| **模糊信号追问** | raw_text 含「通常」「一般来说」「这要看情况」「大多数」「除非」 | "您说'一般来说'需要变更委员会——在什么情况下可以不设？" |
| **规则空白填充** | Review Queue 条目与现有 skill 中已有相关规则 | "我们现有规则覆盖了X，但您认为这里最容易漏掉什么？您见过哪些项目失败是这里没覆盖到的？" |
| **关键事件技术** | source_type = "gen_hint" 且 signal_type = "anti_pattern" 或 "risk_signal" | "您能举一个具体项目，当时很多人没发现问题，但您已察觉风险？是什么让您察觉的？" |
| **反向验证** | 已有 Pending 规则需压力测试 | "我们有一条规则：[XXX]。在什么情况下这条规则是错的或有害的？" |

### 6.2 策略选择逻辑

```python
def select_strategy(queue_item: ReviewQueueItem, existing_rules: list[FocusPoint]) -> str:
    text = queue_item.raw_text.lower()
    fuzzy_signals = ["通常", "一般来说", "这要看情况", "大多数情况", "除非", "视情况"]
    
    if any(s in text for s in fuzzy_signals):
        return "fuzzy_signal"
    
    related_rules = find_related_rules(queue_item, existing_rules)
    if related_rules:
        return "rule_gap"
    
    if queue_item.signal_type in ("anti_pattern", "risk_signal"):
        return "critical_incident"
    
    return "reverse_validation"
```

### 6.3 满意度模型（自动推进机制）

每轮 Q&A 后，LLM 内部评估当前条目的完成度，输出隐藏标记：

```
<!-- qa-eval: {
  "rule_stated_clearly": true,
  "scope_defined": false,
  "counterexample_found": true,
  "confidence_determinable": true,
  "satisfaction_score": 0.75
} -->
```

满意度评估维度（各占 0.25 分）：

| 维度 | 达成标准 |
|---|---|
| 规则表述清晰 | 能提炼为「IF [条件] THEN [行动]」格式 |
| 适用范围已界定 | 明确了 project_type / industry / 规模条件 |
| 已发现例外或反例 | 专家提到了至少一个不适用场景 |
| 置信度可确定 | 专家的语气/表述可推断为 high / medium / low |

当 `satisfaction_score >= auto_advance_threshold`（默认 0.75）时，系统提示「本条知识已提炼完整，是否进入下一条？」并自动生成 KnowledgeItem 草稿。

### 6.4 多轮对话设计

```
第1轮：LLM 呈现 queue_item 原文 + 相关现有规则（如有）
       → 根据策略设计主问题

第2轮：跟进追问（如果满意度不足）
       优先追问未达成的维度：
       - scope_defined=false → "这个规则适用于什么类型的项目？"
       - counterexample_found=false → "有没有您见过的例外情况？"
       - confidence_determinable=false → "这是强制要求还是建议做法？"

第3轮（可选）：规则草稿确认
       "根据您的描述，我提炼的规则是：[草稿]。这准确吗？有需要修正的地方？"

自动结束条件：satisfaction_score >= threshold 或达到 max_turns（默认 5）
```

---

## 七、专家知识提取三阶段流程

### 7.1 Phase 0：专家画像初始化

**首次访问**：
1. LLM 分析当前 Review Queue 的 category 分布
2. 生成动态多选框（最多 8 个领域选项）
3. 专家勾选 → 写入 `expert-profile.json`

**再次访问**：
1. 加载 `expert-profile.json`，展示「上次选择：[领域列表]，是否继续？」
2. 专家可一键确认或修改
3. 按专家领域过滤 Review Queue，优先展示高 occurrence_count 的候选

### 7.2 Phase 1：Queue 驱动的逐条 Q&A

```
FOR EACH queue_item in filtered_candidates (按 trust × occurrence_count 排序):
  1. 展示给专家：
     - 条目原文
     - 来源项目背景（匿名化）
     - 现有相关规则（如有）
  2. 选择策略 → 设计主问题
  3. 多轮对话（最多 max_turns 轮）
  4. 实时计算 satisfaction_score
  5. 达到阈值 → 生成 KnowledgeItem 草稿 → 专家确认 → 写入 Pending
  6. 未达到阈值 → 标记「需进一步澄清」，下次继续
  7. 专家可随时跳过当前条目
```

### 7.3 Phase 2：专家主动提交规则文档

专家上传 SOP / 经验文档 / 规则清单：

```
文档上传
  ↓
LLM 扫描：识别文档中的规则条目（IF-THEN 结构、编号列表、要求/禁止等）
  ↓
生成「规则条目清单」（类比 gen-hint，但 trust = high）
  ↓
逐条进入澄清对话：
  - 与现有 skill 对比：「您文档中 Rule-3 与我们现有规则 X 有重叠，您的版本有何不同？」
  - 追问适用范围：「这条规则是针对所有项目还是特定类型？」
  - 追问例外：「这里有'通常'，例外情况是什么？」
  ↓
生成 KnowledgeItem → 专家确认 → 写入 Pending
```

### 7.4 审查后追问模式（Post-Review Extraction）

资深顾问完成一次项目审查后，系统触发独立追问窗口：

```
[系统]：本次审查输出了以下发现：
  - [Finding-001] 需求文档缺少变更管理章节（高风险）
  - [Finding-002] 接口文档版本不一致（中风险）
  - ...

根据您的经验：
1. LLM 漏掉了哪些风险？
2. 上述发现中，哪些您认为严重性被高估或低估了？
3. 您当时审查类似项目时，是什么信号让您察觉到了这类问题？
```

此模式的优势：
- 在真实项目语境下提取，知识最具体
- 资深顾问的输入独立于审查过程，不污染普通顾问的审查
- 无需单独打开知识提取入口，降低摩擦

产出的 KnowledgeItem 自动关联 `source_project_id`，增强溯源能力。

---

## 八、规则适用范围字段

现有 FocusPoint 缺少适用范围，导致规则要么过泛（什么项目都触发）要么过窄。

### 8.1 扩展 FocusPoint YAML frontmatter

```yaml
---
id: ccb-required
name: 变更委员会必要性
applicability:
  project_types: ["contract"]          # "contract" | "internal" | "*"
  min_duration_months: 6               # 项目工期下限
  industries: ["*"]                    # 或 ["manufacturing", "retail"]
  contract_models: ["fixed_price"]     # "fixed_price" | "tm" | "*"
  excluded_when: "agile AND team_size < 10"  # 排除条件（自由文本，LLM 判断）
trust_level: "high"
source: "expert_qa"
pending_since: "2026-04-01"
approved_by: "admin_001"
---
```

### 8.2 审查时适用范围过滤

```python
def filter_focus_points(
    focus_points: list[FocusPoint],
    project_context: ProjectContext,
) -> list[FocusPoint]:
    applicable = []
    for fp in focus_points:
        if not fp.applicability:
            applicable.append(fp)
            continue
        a = fp.applicability
        if a.project_types != ["*"] and project_context.project_type not in a.project_types:
            continue
        if a.min_duration_months and project_context.duration_months < a.min_duration_months:
            continue
        # excluded_when 由 LLM 判断（in-context）
        applicable.append(fp)
    return applicable
```

### 8.3 知识提取时强制追问适用范围

在 Phase 1 / Phase 2 的对话中，若当前 KnowledgeItem 的 `scope_defined = false`，LLM 必须在进入下一条之前追问：

> "这条规则是否适用于所有项目类型？还是仅限于合同型项目、工期超过半年的情况？"

---

## 九、规则回测验证机制

### 9.1 目标

新规则进入 Pending 后，在正式 Approve 之前，用历史项目验证其有效性，避免「规则看起来合理但实际无效」。

### 9.2 流程

```
Pending Rule
  ↓
选择回测数据集（已完成项目，需标注「已知结果」）
  ↓
Trial Run（不写入 Active，只对比输出）：
  对每个历史项目文档运行该规则
  ↓
输出回测报告：
  - 命中已知问题项目数 / 总问题项目数（召回率）
  - 误报数 / 总成功项目数（精确率）
  - 典型命中案例 + 典型误报案例
  ↓
知识管理员审阅报告 → 决定 Approve / 修改 / Reject
```

### 9.3 数据结构

```python
@dataclass
class BacktestReport:
    pending_rule_id: str
    dataset_size: int
    recall: float          # 命中已知问题 / 总问题项目
    precision: float       # 1 - 误报率
    hit_cases: list[str]   # 项目 ID 列表（命中）
    miss_cases: list[str]  # 项目 ID 列表（漏检）
    false_positive_cases: list[str]
    generated_at: str
    verdict: str           # "recommended" | "needs_refinement" | "reject"
```

### 9.4 历史项目档案要求

历史项目需额外标注：
```json
{
  "project_id": "proj_2024_001",
  "outcome": "failed",
  "known_issues": ["scope_creep", "no_ccb", "late_requirement_change"],
  "is_backtest_eligible": true
}
```

Admin 管理历史项目档案，普通顾问不可见。

---

## 十、KnowledgeItem v2 数据结构

```typescript
interface KnowledgeItem {
  id: string;                    // ki-001
  extraction_focus_id: string;   // "rule" | "exception" | "anti_pattern" ...
  title: string;                 // ≤20 字
  content: string;               // 结构化 Markdown，含 IF-THEN 格式
  source_evidence: string;       // 来源片段
  source_queue_item_id: string;  // 关联的 ReviewQueueItem
  source_project_id?: string;    // 来源项目（gen-hint 路径）
  
  // 适用范围（v2 新增）
  applicability: {
    project_types: string[];
    min_duration_months?: number;
    industries: string[];
    excluded_when?: string;
  };
  
  confidence: "high" | "medium" | "low";
  trust_source: "expert_qa" | "doc_submission" | "post_review" | "gen_hint";
  
  status: "pending" | "approved" | "revised" | "rejected";
  
  // Q&A 质量追踪
  qa_eval: {
    rule_stated_clearly: boolean;
    scope_defined: boolean;
    counterexample_found: boolean;
    confidence_determinable: boolean;
    satisfaction_score: number;
  };
  
  tags: string[];
  created_at: string;
  approved_by?: string;
  backtest_report_id?: string;
}
```

---

## 十一、新增 API 端点

```
# 专家画像
GET  /api/v1/expert-profile
PUT  /api/v1/expert-profile

# Review Queue
GET  /api/v1/review-queue                         # 按领域过滤、按权重排序
PATCH /api/v1/review-queue/{rqid}                 # 更新状态（dismiss / promote）

# 知识提取会话（Phase 1 / Phase 2）
POST /api/v1/extraction/sessions                  # 创建提取会话
POST /api/v1/extraction/sessions/{sid}/stream     # Q&A 流式输出（SSE）
GET  /api/v1/extraction/sessions/{sid}/eval       # 当前条目满意度评估
POST /api/v1/extraction/sessions/{sid}/advance    # 手动推进下一条

# 审查后追问
POST /api/v1/projects/{pid}/conversations/{cid}/post-review-extraction/stream

# Pending Rule Pool
GET  /api/v1/pending-rules
POST /api/v1/pending-rules/{rid}/approve          # Admin 专用
POST /api/v1/pending-rules/{rid}/reject           # Admin 专用
POST /api/v1/pending-rules/{rid}/backtest         # 触发回测

# 规则回测
GET  /api/v1/backtest/reports/{report_id}
GET  /api/v1/backtest/dataset                     # 历史项目档案列表（Admin）
```

---

## 十二、实现路径（Sprint 划分）

在 v0.1 Sprint A-E 基础上，新增以下 Sprint：

### Sprint F：信号分层基础设施
- F-1：gen-hint 标记解析（`<!-- gen-hint: {...} -->`）
- F-2：`review_queue.json` 写入与聚合（trust × occurrence_count）
- F-3：按顾问角色打信任戳（需 session user_role 字段）
- F-4：evolve-hint 污染审计日志
- **验收**：审查会话产生 gen-hint → 正确写入 queue，普通/资深顾问 trust 不同

### Sprint G：专家画像与 Queue 驱动 Q&A
- G-1：`expert-profile.json` 读写 API
- G-2：动态领域多选框（基于 queue category 分布）
- G-3：Phase 1 Q&A 流程（策略选择 + 满意度模型）
- G-4：satisfaction_score 隐藏标记解析与自动推进
- **验收**：专家画像保存 → 下次加载 → Q&A 满意后自动推进

### Sprint H：规则适用范围 + 文档提交
- H-1：FocusPoint YAML applicability 字段扩展
- H-2：审查时适用范围过滤器
- H-3：Phase 2 文档提交流程（上传 → 规则识别 → 澄清对话）
- H-4：KnowledgeItem applicability 字段 + 强制追问逻辑
- **验收**：applicability 过滤生效，文档提交可产出 KnowledgeItem

### Sprint I：Pending + 回测 + 审查后追问
- I-1：Pending Rule Pool API + Admin 审批界面
- I-2：LLM 辅助冲突检测（新规则 vs 现有规则）
- I-3：历史项目档案标注（outcome / known_issues）
- I-4：回测 Trial Run 模式（不写 Active）+ BacktestReport
- I-5：审查后追问入口（资深顾问审查结束后触发）
- **验收**：Pending 规则可触发回测，回测报告可读，Admin 可基于报告审批

---

## 十三、自学习飞轮设计（v2 增强）

### 13.1 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    KE-v2 学习飞轮全景                             │
│                                                                  │
│  [Admin]──批准规则──→ [Pending Rule Pool] ←──提交──[资深顾问]    │
│     ↑                       ↓ 批准后                             │
│  宏观报告              [知识卡库 / 规则库]                        │
│     ↑                       ↓ 矛盾检测       ↑ 下游使用反馈      │
│  [跨会话分析]←───── [会话质量报告库]    [普通顾问引用]           │
│                             ↑ meta-reflect                       │
│                       [提取会话] ←── 注入 ── [问题策略库(RAG)]  │
│                       Scale-1: 上下文内实时适应                  │
└──────────────────────────────────────────────────────────────────┘
```

三个时间尺度的学习机制各司其职，共同构成闭环飞轮：

| 尺度 | 机制 | 延迟 | 存储依赖 |
|------|------|------|---------|
| 尺度1：会话内实时适应 | 专家建模协议（in-context） | 即时（轮次级） | 无 |
| 尺度2：会话间经验沉淀 | 场边教练 + 会话后元反思 | 轮次级 / 天级 | session_quality_reports, question_strategy_patterns |
| 尺度3：长期模式涌现 | 跨会话宏观分析 | 月/季度级 | 以上两表 + 知识卡库 |

---

### 13.2 尺度1：会话内实时适应（专家建模协议）

**实现方式**：在 System Prompt 中注入专家建模协议，无需外部存储。

```
【专家建模协议 - 实时适应】
在对话过程中，持续维护对当前专家的隐式心理模型，追踪以下信号：

观察维度：
• 回答风格：是否倾向举具体案例（检测"比如/有一次/上个项目"）或倾向抽象原则
• 回答密度：字数突增→触到真实领域；字数过少→方向偏离
• 不确定信号："通常/一般/这要看情况"→必须追问例外条件
• 防御信号："这个说不好/不方便说"→切换为正向案例先行
• 自我修正："不对，应该说/更准确地说"→高价值知识点，立即深挖

动态调整规则：
• 检测到"案例型"专家 → 多用"给我说一个最难处理的..."
• 检测到"原则型"专家 → 多用"这个原则在什么情况下会失效？"
• 检测到防御模式 → 先问成功案例，再从侧面切入失败
• 每3轮自检：当前方向是否还在产出新信息？若停滞，主动转换
```

本质是 **In-Context Learning**：同一会话内，前面的对话是 few-shot 示例，AI 从中学到"对这个人，这种问法有效"。

---

### 13.3 尺度2-A：场边教练（会话进行中）

**设计原则**：教练是场边观察员，不是替补球员。它观察、分析、向操作者耳语，但不替代对话 Agent 提问。

```
┌──────────────────────────────────────────────────────┐
│                 教练 Agent 职责边界                   │
├──────────────────────┬───────────────────────────────┤
│      应该做           │         不应该做              │
├──────────────────────┼───────────────────────────────┤
│ 检测对话质量信号      │ 直接生成下一个问题替代对话Agent│
│ 追踪知识覆盖地图      │ 频繁打断（每轮都介入）        │
│ 识别专家状态变化      │ 推翻对话Agent的当前判断       │
│ 触发策略切换建议      │ 管理对话节奏和礼貌            │
│ 维护会话元数据        │ 与专家直接交互                │
└──────────────────────┴───────────────────────────────┘
```

**MVP 实现（每5轮触发）**：

```
触发时机：round_number % 5 == 0
输入：完整对话记录 + 已提取知识卡列表
独立 LLM 调用（不在对话上下文中）
输出 SSE 事件：{type: "coach_hint", expert_type_signal, coverage_gaps, 
                 current_momentum, whisper, flag}
```

教练耳语（whisper）作为提示展示给**操作者**，操作者决定是否采纳，可一键将建议填入输入框。

**Coach Prompt**（精简、结构化输出）：
```
你是提问质量观察员，不参与对话，只做客观分析。
输入：对话记录 + 已提取知识卡

输出 JSON（200字以内）：
{
  "expert_type_signal": "A型（原则型）/B型（案例型）/C型（防御型）/未确定",
  "coverage_gaps": ["尚未覆盖的知识区域"],
  "current_momentum": "good|fading|stuck",
  "whisper": "一句话的提问方向建议（≤80字）",
  "flag": null  // 或 "strategy_switch" | "expert_fatigue" | "topic_exhausted"
}
```

**为什么用同一个 LLM 而非不同模型**：独立性来自**空上下文**，不是模型身份。新 session 读取完整对话记录时，没有对"当时为什么这么问"的记忆，天然形成外部观察者视角。

---

### 13.4 尺度2-B：会话后元反思（Meta-Reflection）

每次会话结束后，触发独立 LLM 分析调用（不同于教练，是更完整的回顾）：

**输入**：完整会话记录 + 知识卡列表（含确认/拒绝状态）

**任务**：
1. 标注哪些问题产生了高价值知识卡，哪些没有
2. 分析高价值问题的共同特征（策略类型、表达方式）
3. 找出哪些知识类型仍然空白，下次应该优先覆盖
4. 提炼 3-5 条「针对此类专家的提问改进建议」

**输出**：存入 `session_quality_reports` 表，触发 `question_strategy_patterns` 效果分更新。

**效果分更新公式（EMA）**：
```python
# 避免早期数据永久锁定分数
new_score = old_score * 0.85 + session_ki_yield_rate * 0.15
```

---

### 13.5 问题策略库（Strategy Library）

策略库是教练和元反思的共同输出目的地，也是下次会话的输入来源（形成闭环）。

**Schema**：

```sql
CREATE TABLE question_strategy_patterns (
  id TEXT PRIMARY KEY,
  pattern TEXT NOT NULL,            -- 问题模板
  strategy_type TEXT NOT NULL,      -- gap_based/fuzzy_signal/critical_incident/reverse_validation
  applicable_when TEXT,             -- JSON: {expert_type, knowledge_target, session_stage}
  effectiveness_score REAL DEFAULT 0.5,
  ki_yield_rate REAL DEFAULT 0.0,   -- 平均每次产出知识卡数
  usage_count INTEGER DEFAULT 0,
  sample_triggers TEXT,             -- JSON: 触发过好回答的真实问题变体
  failure_contexts TEXT,            -- JSON: 失效场景记录
  created_from TEXT DEFAULT 'bootstrap',  -- "bootstrap"|"meta_reflect"|"admin_manual"
  updated_at TEXT,
  created_at TEXT
);
```

**下次会话注入**：启动会话时，按 `effectiveness_score` 检索 top-5 匹配策略，注入到 System Prompt：

```
【本次推荐策略（基于历史会话经验）】
1. [效果 0.87] "能说一个当时判断最难的节点吗？你是怎么判断的？"
   → 适用：B型专家，开场破冰后使用
2. [效果 0.81] "这个规则在什么情况下会出错？"
   → 适用：所有类型，已有初步规则陈述后使用
```

---

### 13.6 尺度3：长期模式涌现（批处理，月/季度级）

| 分析任务 | 触发方式 | 产出 |
|---------|---------|------|
| 知识地图空白发现 | 月度 cron 或 Admin 手动 | 空白区域列表 + 针对性探针问题 |
| 专家分型聚类 | 积累 5+ 个会话质量报告后 | 专家类型档案（A/B/C型） |
| 知识卡矛盾检测 | 新知识卡入库时触发 | 矛盾记录 + 追问任务注入下次会话 |

**矛盾检测的价值**：矛盾不是错误，是"背后有未被提取的条件变量"的信号。矛盾本身成为下一轮提问的输入，形成闭环。

```
专家A: "蓝图阶段应尽快推动确认"
专家B: "蓝图阶段宁可多花时间也要确保理解"
→ 自动生成追问任务：下次见任何专家，问"什么情况下你会选择加速，什么情况下会延长？"
```

---

### 13.7 核心设计哲学

> **让知识库反哺提问，而不只是让提问产出知识库**

单向流动：`提问 → 产出知识卡`（大多数系统止步于此）
闭环飞轮：
- 知识库越丰富，AI 越知道"哪里还有空白" → 问题越有针对性
- 知识卡之间的矛盾，成为最有价值的追问线索
- 已验证有效的知识卡，反向标注了产生它的问题策略有多好

这个闭环一旦运转，提问质量会随知识库成熟而持续提升——不是因为模型变聪明了，而是因为**它知道的越多，越清楚自己不知道什么**。

---

### 13.8 Sprint 6 实现范围

| 编号 | 任务 | 对应尺度 |
|------|------|---------|
| 6.1 | 专家建模协议注入 System Prompt | 尺度1 |
| 6.2 | 新增 DB 表：question_strategy_patterns, session_quality_reports | 尺度2基础 |
| 6.3 | 场边教练（每5轮触发，独立 LLM 调用，coach_hint SSE 事件） | 尺度2-A |
| 6.4 | 元反思端点：`POST /api/v1/extraction/meta-reflect` | 尺度2-B |
| 6.5 | 策略库端点：`GET /api/v1/extraction/strategies` + 效果分更新 | 尺度2-B |
| 6.6 | Bootstrap 种子策略（12条，覆盖4种策略类型） | 尺度2基础 |
| 6.7 | 前端 coach_hint 事件处理 + 教练提示 UI | 尺度2-A |

---

## 十四、关键设计决策

### 决策 1：教练与元反思使用同一 LLM，不同 Session

独立性来自**空上下文窗口**，不是模型身份。新 session 读取完整对话记录时形成外部观察者视角，不会受到"当时为什么这么问"的锚定效应影响。换不同模型只在刻意对比模型差异时才有价值，当前阶段不必要。

### 决策 2：Review Queue 是中央缓冲层，不是临时文件
Review Queue 是系统的知识积压池（backlog），长期存在，不随审查会话结束而清空。所有进入 Active 的规则都必须经过它。

### 决策 2：满意度阈值可配置
`auto_advance_threshold` 放在 `expert-profile.json` 中，资深顾问可调整（默认 0.75）。追求严谨的专家可提高到 0.9，快速过一遍 queue 时可降低到 0.6。

### 决策 3：审查后追问独立于审查会话
Post-Review Extraction 产生的 KnowledgeItem 不混入审查会话的 message 流，单独存储，避免污染审查报告的上下文。

### 决策 4：回测是推荐步骤而非强制
Admin 可选择跳过回测直接审批（例如历史档案不足时），但系统会记录「未经回测直接审批」标记，供后续质量追踪。

### 决策 5：普通顾问不感知 Review Queue
普通顾问的 UI 中不显示任何 Queue / Pending 相关入口，gen-hint 标记对其完全透明，避免引起混淆或规避行为。
