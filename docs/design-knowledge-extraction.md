# 设计文档：知识提取与隐性知识显化功能

**版本**：v0.3  
**日期**：2026-04-30  
**作者**：AI-KA 开发团队  
**变更**：重写 §三（权威模型三层）、§四（信号污染隔离）、§五（LLM 提问引擎）、§六（规则适用范围）、§七（规则回测）、§八（专家提取入口重设计）、§九（审查后追问模式）、§十（Review Queue 中枢架构）；原 Sprint 计划重写为 Phase 0–4。

---

## 一、背景与动机

AI-KA 当前功能以「项目文档审查」为核心：读入项目文档、围绕关注点分析、输出结构化发现。这套机制的底层能力——文档分块召回 + 多轮对话 + 结构化提取——同样适用于另一类高价值场景：

> **从非结构化/半结构化素材（访谈陈述、操作 SOP、项目复盘）中提取隐含知识，将其系统化为可复用的审查规则与 skill 包。**

**知识提取的最终目的是提升审查质量**，而不是建立独立的知识库。提取出的知识最终回流为：关注点（FocusPoint）规则、技能包（SkillPackage），或注入到审查会话的记忆片段。

---

## 二、与现有审查功能的关系

| 维度 | 项目审查（现有） | 知识提取（新建） |
|---|---|---|
| 目标 | 发现项目风险与问题 | 将专家隐性知识显化为规则 |
| 输入 | 项目文档（需求、蓝图、接口文档） | 访谈陈述、规则文档草稿、审查后追问 |
| 关注点 | 风险、需求完整性、接口 | 知识类型（规则、例外、适用范围、反例） |
| 输出 | 结构化「发现」（Finding） | 待审核规则提案（Pending Rule Proposal） |
| 多轮会话目的 | 追问风险细节、更新发现状态 | 澄清模糊规则、挖掘深层逻辑、验证规则边界 |
| 记忆演化 | evolve-hint → review queue | review queue → 专家审核 → 生效规则 |

**核心数据流**：

```
项目审查会话
    ↓ (项目特有事实)
项目记忆 [project/<pid>/*.md]
    ↓ (可泛化的行业/PM/产品规律)
Review Queue [.aika/review-queue/]
    ↓ (专家主动提取 / 审查后追问)
Pending Rule Proposals [status: pending]
    ↓ (资深顾问审核通过)
生效规则 [review_skill_packages/.../review_domain.md]
```

---

## 三、权威模型：三层而非二元

### 3.1 角色分层

```
Layer 0：平台内置策略（硬编码，任何人不可覆盖）
    ↓
Layer 1：资深顾问（Senior Expert）— 可创作规则提案
    ↓  
Layer 2：普通顾问（Regular Consultant）— 仅使用，产生反馈信号
```

**关键原则**：即使是资深顾问，所有新规则也必须先进入 Pending 状态，不能直接覆盖生效规则。原因：
- 顾问有行业/项目类型偏见（零售经验 ≠ 金融规则）
- 新规则可能与已有规则冲突
- 需要冲突检测步骤（LLM 辅助）

### 3.2 规则生命周期

```
创作 → [draft]
提交 → [pending]    ← 所有来源（含资深顾问）均在此等待
冲突检测 → [conflict_flagged] | 无冲突继续
资深顾问二审 → [approved]
生效 → [active]
废弃 → [deprecated]
```

### 3.3 各角色权限矩阵

| 动作 | 资深顾问 | 普通顾问 |
|---|---|---|
| 访问知识提取入口 | ✓ | ✗ |
| 提交规则提案（→ Pending） | ✓ | ✗ |
| Approve Pending 提案 | ✓（非自审）| ✗ |
| 标记发现状态（审查中）| ✓ | ✓ |
| 触发审查后追问 | ✓ | ✗ |
| 发起项目审查 | ✓ | ✓ |

### 3.4 现阶段实现说明

目前系统为单用户模式（无认证体系），角色通过 **配置标志** 而非登录实现：
- `AIKA_USER_ROLE=senior_expert` → 开启提取入口
- `AIKA_USER_ROLE=consultant`（默认） → 仅审查功能

多用户 RBAC 为未来版本（Phase 4）目标。

---

## 四、信号污染隔离

### 4.1 三类信号及其处理路径

| 信号类型 | 来源 | 目的地 | 权重 | 可直接改规则 |
|---|---|---|---|---|
| **知识提取**（Extraction） | 资深顾问主动陈述 / 上传文档 | → Pending 提案 | 高 | 否（需二审）|
| **审查后追问**（Post-Review） | 资深顾问在真实项目语境中的反馈 | → Pending 提案 | 高 | 否（需二审）|
| **发现反馈**（Finding Feedback）| 任何顾问标记发现状态 | → 发现置信度调整，仅项目记忆 | 低 | **否** |
| **LLM 自生成 evolve-hint** | 分析过程中 | → Review Queue（tagged: ai_generated）| 中 | **否**（需人工确认）|

### 4.2 evolve-hint 污染防护

**问题**：普通顾问的审查会话可能引导 LLM 往错误方向分析，导致 evolve-hint 积累错误方向的改进建议。

**当前 `evolution_queue.py` 缺失字段**，需扩展：

```python
# 当前（不足）
entry = {"focus_id": ..., "suggestion": ..., "conversation_id": ..., "turn": ..., "created_at": ...}

# 目标（扩展后）
entry = {
    "focus_id": ...,
    "suggestion": ...,
    "conversation_id": ...,
    "turn": ...,
    "created_at": ...,
    "source_role": "senior_expert" | "consultant" | "ai_self",  # 新增
    "source_type": "extraction" | "post_review" | "evolve_hint",  # 新增
    "status": "pending" | "approved" | "rejected",  # 新增
    "project_id": ...,  # 新增，便于隔离项目偏见
}
```

**处理规则**：
- `source_role=consultant` 的 evolve-hint → **只能进 Review Queue，永不自动提升**
- `source_role=ai_self` 的 evolve-hint → **需资深顾问显式 Approve**
- `source_role=senior_expert` 的提取 → **进 Pending，需另一位资深顾问二审**

### 4.3 发现反馈的隔离

普通顾问的「标记发现为误报/已知」动作仅影响：
- 该发现在当前项目会话中的置信度（降低/标注）
- 写入 `project/<pid>/feedback.md`（项目级，不影响全局规则）

**不允许**：发现反馈直接触发关注点（FocusPoint）文本的修改。

---

## 五、LLM 提问引擎（核心知识提取策略）

这是整个功能的核心难题：LLM 不知道自己不知道什么（unknown unknowns）。需要设计系统性的提问框架来提取隐性知识。

### 5.1 四种提问策略

#### 策略一：模糊信号检测（Fuzzy Signal Trigger）

**触发词**：「通常」「一般来说」「这要看情况」「大多数时候」「除非」「基本上」  
**追问模板**：
- "您说「一般来说」——在什么情况下会不一样？"
- "「这要看情况」——您能具体说说哪些情况会影响判断？"
- "什么时候这个原则会失效？"

LLM 在每轮响应中扫描专家回答，命中触发词时在下一问嵌入追问。

#### 策略二：规则空白填充（Gap-Based Questioning）

展示当前技能包中已有的规则给专家，然后问：
- "这套规则里，您认为最容易漏掉什么场景？"
- "您见过哪些项目失败，是这里没有覆盖到的？"
- "如果一个新顾问只用这套规则，他会在哪里栽跟头？"

**这是效率最高的提取方式**——不是从零开始，而是让专家审阅并补充现有规则的盲区。

#### 策略三：关键事件技术（Critical Incident Technique）

从具体真实案例倒推规则，比直接问规则更真实：
- "您能举一个项目，当时很多人没发现问题，但您当时就察觉到有风险？是什么让您察觉的？"
- "有没有遇到过：看似一切正常的项目，最后却出了问题？能说说那个案例吗？"
- "您做顾问这么多年，记忆最深的一次「差点犯错但及时发现」是什么情况？"

从案例中提取规则的后处理：
```
案例描述
    → LLM 提取结构化规则（IF-THEN）
    → 追问规则适用范围（什么情况下此规则生效）
    → 追问反例（什么情况下此规则不适用）
    → 生成 KnowledgeItem
```

#### 策略四：反向验证（Reverse Validation / Rule Stress-Testing）

拿现有规则给专家做「压力测试」：
- "我们有一条规则：[xxx]。您觉得在什么情况下这条规则是错的或有害的？"
- "如果完全按这条规则执行，会发生什么最坏的情况？"
- "哪类项目不应该应用这条规则？"

这既验证了规则的边界，也会提取出新的「适用范围」约束字段。

### 5.2 多轮满意度判断

每个知识条目的提取采用「满意度驱动」的多轮模式：

```
问题展示
    ↓
专家回答
    ↓ (LLM 内部评估)
满意度评分 [0.0-1.0]
    ├─ < 0.6 → 追问（选择策略一/二/三/四）
    ├─ 0.6-0.85 → 确认性追问（"您的意思是... 对吗？"）
    └─ > 0.85 → 生成结构化 KnowledgeItem，提交专家确认，进入下一条
```

**满意度判断依据**（LLM 内部）：
- 是否包含具体条件（IF 子句）
- 是否包含结果（THEN 子句）
- 是否有适用范围或边界条件
- 是否与现有规则有明确的关系（补充/替换/例外）

单条目最多 5 轮，超过后标记为 `clarification_needed` 并跳过。

### 5.3 提问序列设计（Review Queue 驱动）

LLM 根据 Review Queue 内容自动生成问题序列，而不是随机提问：

```
Review Queue Item:
  {
    "focus_id": "requirement_completeness",
    "suggestion": "在金融类项目中，监管合规需求通常被遗漏",
    "source_type": "evolve_hint",
    "occurrences": 3  // 在3个项目审查中出现
  }
```

→ LLM 基于此生成：
1. "我注意到在最近几个项目审查中，系统发现金融类项目的监管合规需求经常被遗漏。您是否遇到过类似情况？"
2. （策略二）"现有的需求完整性关注点里，您认为对金融项目来说最重要的监管维度是什么？"
3. （策略三）"能具体说一个监管合规缺失导致项目问题的案例吗？"

### 5.4 专家背景信息收集（首次 + 领域选择）

专家进入知识提取入口时，LLM 首先：

```
1. 基于 Review Queue 内容分析出涉及的领域（如：金融、零售、政府、制造...）
2. 显示多选框："您擅长哪些领域？"（从 Review Queue 话题自动生成选项）
3. 可附加自由文本："您的主要专业背景"
4. 保存到专家档案：~/.aika/memory/user/expert_profile.md
5. 下次访问自动加载，可修改
```

专家背景信息在提问时用于：
- 过滤不匹配领域的 Review Queue 条目
- 在 LLM 提示中注入专家背景（减少不必要的行业基础解释）

---

## 六、规则适用范围（Applicability Scope）

### 6.1 问题

现有关注点（FocusPoint）只有「是否触发」，没有「在什么条件下触发」。这导致：
- 规则太泛：对所有项目触发，误报率高
- 规则太窄：稍微泛化就失效

### 6.2 FocusPoint 数据模型扩展

在 `review_domain.md` 的关注点 YAML frontmatter 中增加 `scope` 字段：

```yaml
---
id: change_management_ccb
name: 变更委员会（CCB）机制
applicable_when:
  project_type: ["contract", "outsourced"]   # 合同型、外包
  duration_months_gt: 6
not_applicable_when:
  project_type: ["poc", "internal_agile"]    # PoC、内部敏捷
  team_size_lte: 5
scope_note: "小型内部敏捷项目通常不需要正式 CCB，变更通过 sprint review 即可管理"
---

（关注点提示词正文）
```

项目档案（`project/<pid>/profile.md`）提供匹配所需的维度：

```yaml
project_type: contract      # contract | agile | internal | poc | outsourced
duration_months: 8
team_size: 12
industry: finance
```

分析时 `build_system_prompt` 在选取关注点时预先过滤不适用的规则，并在系统提示中注明「该项目类型下，以下规则不适用」。

### 6.3 知识提取时必须追问适用范围

在提取任何规则时，LLM 必须询问：
- "这条规则适用于哪类项目？"
- "有没有项目类型是例外的？"
- "规模大小会影响这条规则的适用性吗？"

生成的 KnowledgeItem 必须包含 `applicable_when` / `not_applicable_when` 才能进入 Pending。

---

## 七、规则回测验证机制

### 7.1 设计目标

新规则提案进入 Pending 后，在资深顾问二审前，可以先对历史项目文档做干跑（dry run），验证：
- 该规则是否能识别出已知发生过的问题？
- 该规则在历史无问题项目上是否会产生大量误报？

### 7.2 历史项目档案格式

在项目档案中增加结果标注：

```yaml
# .aika/memory/project/<pid>/outcome.md
---
type: project_outcome
---
项目结果：延期交付，原因：需求变更未受控
已知问题：
  - 需求变更超过 30%，无 CCB 机制
  - 关键干系人识别不完整
  - 上线计划未与基础设施团队对齐
```

### 7.3 回测流程

```
新规则提案 (Pending)
    ↓ 触发回测
选择历史项目（有 outcome.md 的项目）
    ↓
在历史项目文档上执行规则（不写入任何东西）
    ↓
对比输出发现 vs 已知问题
    ↓
生成回测报告：
  - 命中率：规则识别出已知问题的比例
  - 误报率：规则在无该类问题的项目上的触发比例
  - 示例：[命中的发现] vs [已知问题]
    ↓
报告附在 Pending 提案上，供资深顾问二审参考
```

### 7.4 实现约束

- 回测为异步后台任务，不阻塞提案流程
- 回测结果不自动 Approve/Reject，仅供参考
- 历史项目参与回测需用户显式标记（`aika project mark-for-backtesting`）

---

## 八、专家知识提取入口（重设计）

### 8.1 核心工作流

```
专家进入 /extraction 入口
    ↓
Step 1：领域定位（可跳过已有档案）
  - LLM 基于 Review Queue 展示涉及领域（多选框）
  - 专家选择 → 保存到 ~/.aika/memory/user/expert_profile.md

    ↓
Step 2a：Review Queue 驱动的逐条问答
  - LLM 按优先级（出现次数 × 上次触发距今天数）排序 Review Queue
  - 逐条展示候选知识，设计问题（策略一~四）
  - 多轮对话直到满意度 > 0.85 或 5 轮超时
  - 专家确认 → 生成 KnowledgeItem → 进入 Pending

Step 2b：专家主动上传规则文档
  - 上传 Markdown / Word / PDF
  - LLM 读取文档，映射到现有关注点
  - 针对文档内容设计澄清问题（策略二/四为主）
  - 提取隐性知识（文档行间的假设、例外、适用条件）
  - 同样产出 KnowledgeItem → Pending

    ↓
Step 3：冲突检测（自动）
  - LLM 检查新 KnowledgeItem 是否与现有规则冲突
  - 冲突 → 标记 conflict_flagged，展示冲突对比
  - 无冲突 → 直接 pending

    ↓
Step 4：资深顾问二审（另一位）
  - 看到 Pending 列表（含回测报告、冲突标注）
  - Approve → active；Reject → archived with reason
```

### 8.2 Review Queue 数据结构扩展

在 `evolution_queue.py` 基础上扩展：

```python
@dataclass
class ReviewQueueItem:
    id: str                          # rq-001, rq-002
    focus_id: str                    # 对应的关注点
    suggestion: str                  # 建议内容（可泛化的规律）
    source_role: str                 # "senior_expert" | "consultant" | "ai_self"
    source_type: str                 # "extraction" | "post_review" | "evolve_hint"
    status: str                      # "pending_review" | "in_review" | "approved" | "rejected"
    occurrences: int                 # 在多少个项目中触发过
    project_ids: list[str]           # 涉及项目（去重后脱敏展示）
    created_at: str
    reviewed_by: str | None
    reviewed_at: str | None
    reject_reason: str | None
```

### 8.3 KnowledgeItem 数据结构（更新）

```python
@dataclass
class KnowledgeItem:
    id: str                           # ki-001
    extraction_focus_id: str          # 目标关注点
    title: str                        # ≤20 字
    content: str                      # IF-THEN 格式规则正文
    source_evidence: str              # 来源（专家陈述片段 / 文档引用）
    confidence: str                   # "high" | "medium" | "low"
    status: str                       # "pending" | "approved" | "rejected" | "active"
    tags: list[str]
    applicable_when: dict             # 新增：适用条件
    not_applicable_when: dict         # 新增：排除条件
    scope_note: str                   # 新增：自然语言说明
    source_role: str                  # "senior_expert"
    source_type: str                  # "extraction" | "post_review"
    backtest_result: dict | None      # 新增：回测结果摘要
    conflict_with: list[str]          # 新增：冲突的现有规则 id
    extraction_strategy: str          # 新增：使用了哪种提问策略
    clarification_questions: list[str]
```

### 8.4 LLM 系统提示框架（Extraction Prompt）

```
[角色]
你是知识工程师，负责从资深顾问的陈述中提取和显化隐性知识。你的目标是
将隐含的判断规则、例外条件、适用范围提炼为结构化的 IF-THEN 规则条目。

[当前专家背景]
{expert_profile}

[当前 Review Queue 候选条目]
{current_item}  // 本轮聚焦的候选规律

[已有关注点规则（相关）]
{relevant_focus_points}  // 用于规则空白填充策略

[提取策略]
本轮使用策略：{strategy}  // fuzzy_signal | gap_based | critical_incident | reverse_validation

[提取规则]
1. 专家回答中出现「通常/一般/除非」等词时，下一问必须追问例外条件
2. 每条规则必须有适用范围（IF 条件）和结果（THEN 行为）
3. 规则充分时输出结构化标记：
   <!-- ki: {"focus": "...", "title": "...", "applicable_when": {...}, "confidence": "high"} -->
4. 仍有未澄清的部分时输出：
   <!-- clarify: {"strategy": "gap_based", "questions": ["问题1"]} -->
5. 满意度评分（内部用，不展示给专家）：
   <!-- satisfaction: 0.7 -->

[已提取条目（避免重复）]
{existing_knowledge_items}
```

---

## 九、审查后追问模式（Post-Review Extraction）

### 9.1 设计动机

「审查后追问」是提取隐性知识最高效的模式：
- **语境具体**：专家针对真实项目发现进行点评，知识最具体
- **不污染审查**：专家输入独立于审查主流程，不影响审查结论
- **自然触发**：不需要专家切换到独立工具，降低使用门槛

### 9.2 触发条件

审查会话结束后，系统检测：
- 当前环境 `AIKA_USER_ROLE=senior_expert`
- 会话有至少一条发现（Finding）

满足时在审查输出底部显示入口：
> **[资深顾问]** 系统分析了 X 个发现，您认为还有哪些未被发现的风险或者被误判的问题？

### 9.3 追问会话设计

```
展示本次审查发现列表（标题 + 风险等级）
    ↓
LLM 提问："您认为这份分析遗漏了什么？为什么 LLM 没有发现这些？"
    ↓
专家回答
    ↓
LLM 追问（使用策略一/三）：提取遗漏原因中的规律
    ↓
LLM 追问（使用策略二）：展示相关现有规则，问是否有补充
    ↓ （满意度 > 0.85）
生成 KnowledgeItem（source_type: "post_review"）
    ↓
进入 Pending（同上述流程）
```

### 9.4 与「知识提取入口」的区别

| 维度 | 独立提取入口 | 审查后追问 |
|---|---|---|
| 触发时机 | 专家主动访问 | 审查自然结束后 |
| 知识来源 | Review Queue 条目 / 专家上传文档 | 刚完成的审查发现列表 |
| 语境 | 抽象规律讨论 | 具体真实项目 |
| 适合提取 | 系统性规则、行业通识 | 发现遗漏原因、边界条件 |
| 效率 | 中（需准备素材）| 高（即时、有语境）|

两者互补，不互斥。

---

## 十、Review Queue 作为知识中枢

### 10.1 架构定位

Review Queue 是整个知识演化系统的**缓冲区和工作台**，而不仅仅是一个等待队列。

```
输入端：
  项目审查（evolve-hint）  →
  审查后追问               →  Review Queue
  知识提取入口             →
  普通顾问反馈信号         →（只读，不写 proposals）

Review Queue 内容：
  - 候选规律（待验证的泛化规则）
  - 冲突规则（需要解决的矛盾）
  - 适用范围待澄清的条目
  - 待回测的规则提案

输出端：
  → Pending 提案（资深顾问确认后）
  → 项目记忆（项目特有，不泛化）
  → 归档（判断为无效的信号）
```

### 10.2 Review Queue 优先级排序

LLM 在专家提取入口中按以下规则排序展示候选条目：

```python
priority_score = (
    occurrences * 3          # 跨项目出现次数权重最高
    + days_since_last * 0.5  # 最近触发时间加权
    + confidence_avg * 2     # 平均置信度
    - already_reviewed * 10  # 已被审核过的降权
)
```

### 10.3 项目记忆 vs Review Queue 的分流规则

在审查会话中，LLM 在 evolve-hint 时自动判断：

| 信号特征 | 去向 |
|---|---|
| 提到项目特有名词（系统名、团队名、特定时间节点）| → 项目记忆 |
| 涉及行业通识（"金融类项目通常..."）| → Review Queue |
| 涉及项目管理方法（"敏捷项目不需要..."）| → Review Queue |
| 纯粹的文档质量问题（"该文档格式混乱"）| → 丢弃 |
| 涉及具体客户信息 | → **丢弃**（隐私保护）|

---

## 十一、UI 设计

### 11.1 应用模式切换（沿用 v0.1 设计）

```
左侧栏：
  [🔍] 项目审查  （现有功能）
  [💡] 知识提取  （新功能，仅 senior_expert 可见）
  ──
  [?]  帮助
  [⚙]  设置
  [👤] 用户
```

### 11.2 知识提取模式侧边二级导航

```
[+]    新提取会话
[💬]   提取历史
──
[📋]   Review Queue（候选条目管理）
[⏳]   待审核提案（Pending）
[📚]   已生效规则（Active）
[👤]   专家档案
```

### 11.3 Review Queue 面板

- 按领域分组的候选条目列表
- 每条显示：触发次数、涉及项目数（脱敏）、来源类型标签
- 点击进入对话式审核
- 批量操作：归档选中项、转入提案

### 11.4 Pending 提案面板

- 提案列表（含回测结果、冲突标注）
- 每条提案：
  - 规则内容预览
  - 适用范围标签
  - 回测命中率/误报率
  - 冲突规则高亮
- 操作：Approve（跳转到规则编辑确认）/ Reject（填写原因）

### 11.5 审查后追问入口

审查输出区底部追加（仅 senior_expert 可见）：

```
─────────────────────────────
💡 资深顾问追问
您认为本次审查还遗漏了哪些问题？（此反馈仅您可见，将进入规则改进队列）
[输入框] [提交]
─────────────────────────────
```

---

## 十二、后端架构扩展

### 12.1 新增文件

```
web/backend/
  knowledge_models.py      # KnowledgeItem, ReviewQueueItem dataclasses
  ki_parser.py             # 提取 <!-- ki: ... --> 和 <!-- clarify: ... --> 标记
  rule_conflict_detector.py # 新规则与现有规则的冲突检测（LLM 辅助）
  backtest_runner.py       # 规则回测异步任务

web/backend/routers/
  extraction.py            # 知识提取 API 路由
  review_queue.py          # Review Queue CRUD
  pending_rules.py         # Pending 提案 CRUD
```

### 12.2 数据库扩展

```sql
-- 知识条目
CREATE TABLE knowledge_items (
    id TEXT PRIMARY KEY,
    extraction_focus_id TEXT,
    title TEXT,
    content TEXT,
    source_evidence TEXT,
    confidence TEXT,
    status TEXT,      -- pending|approved|rejected|active
    tags_json TEXT,
    applicable_when_json TEXT,   -- 新增
    not_applicable_when_json TEXT,  -- 新增
    scope_note TEXT,             -- 新增
    source_role TEXT,
    source_type TEXT,
    backtest_result_json TEXT,   -- 新增
    conflict_with_json TEXT,     -- 新增
    extraction_strategy TEXT,    -- 新增
    project_id TEXT,
    conversation_id INTEGER,
    created_at TEXT,
    updated_at TEXT
);

-- Review Queue（扩展 evolution_queue）
CREATE TABLE review_queue (
    id TEXT PRIMARY KEY,
    focus_id TEXT,
    suggestion TEXT,
    source_role TEXT,    -- 新增
    source_type TEXT,    -- 新增
    status TEXT,         -- pending_review|in_review|approved|rejected
    occurrences INTEGER DEFAULT 1,  -- 新增
    project_ids_json TEXT,          -- 新增
    created_at TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    reject_reason TEXT
);

-- 专家档案（存 SQLite 或文件均可）
CREATE TABLE expert_profiles (
    user_id TEXT PRIMARY KEY,
    domains_json TEXT,    -- 领域列表
    background TEXT,
    created_at TEXT,
    updated_at TEXT
);
```

### 12.3 API 端点

```
# 知识提取会话
POST /api/v1/projects/{pid}/conversations          # mode="extracting"
POST /api/v1/projects/{pid}/conversations/{cid}/extract/stream

# Knowledge Items
GET   /api/v1/projects/{pid}/conversations/{cid}/knowledge-items
PATCH /api/v1/projects/{pid}/conversations/{cid}/knowledge-items/{kid}
POST  /api/v1/projects/{pid}/conversations/{cid}/knowledge-items/{kid}/submit  # → Pending

# Review Queue
GET   /api/v1/review-queue                      # 按优先级排序
GET   /api/v1/review-queue/{id}
PATCH /api/v1/review-queue/{id}                 # status 变更
DELETE /api/v1/review-queue/{id}               # 归档

# Pending 提案
GET   /api/v1/pending-rules
POST  /api/v1/pending-rules/{id}/approve        # 写入 review_domain.md
POST  /api/v1/pending-rules/{id}/reject

# 审查后追问
POST /api/v1/projects/{pid}/conversations/{cid}/post-review-extraction/stream

# 专家档案
GET   /api/v1/expert-profile
PUT   /api/v1/expert-profile

# 回测
POST  /api/v1/pending-rules/{id}/backtest       # 异步触发
GET   /api/v1/pending-rules/{id}/backtest-result
```

### 12.4 evolve_queue.py 扩展

```python
# 在 append_evolve_hint 中增加必填字段
def append_evolve_hint(
    repo_root: Path,
    *,
    focus_id: str,
    suggestion: str,
    source_role: str,   # 新增：必填
    source_type: str,   # 新增：必填
    project_id: str | None = None,  # 新增
    conversation_id: int | None = None,
    turn: int = 0,
) -> None:
```

---

## 十三、实现路径（Phase 划分）

### Phase 0：基础设施（2 周）
- P0-1：扩展 `evolution_queue.py`，加入 `source_role`、`source_type`、`status`、`project_id`
- P0-2：`ReviewQueueItem` dataclass + DB 表 `review_queue`
- P0-3：Review Queue CRUD API
- P0-4：`AIKA_USER_ROLE` 环境变量支持（senior_expert / consultant）
- **验收**：evolve-hint 写入时携带来源角色；Review Queue 可增删查改

### Phase 1：审查后追问模式（3 周）
- P1-1：`post-review-extraction/stream` SSE 端点
- P1-2：审查输出底部追问入口 UI（仅 senior_expert 可见）
- P1-3：追问会话提示框架（含策略一/三）
- P1-4：追问结果写入 Review Queue（`source_type: "post_review"`）
- **验收**：资深顾问完成审查后可追问，结果出现在 Review Queue

### Phase 2：LLM 提问引擎（4 周）
- P2-1：四种提问策略 prompt 模板实现
- P2-2：满意度评分解析（`<!-- satisfaction: x.xx -->`）
- P2-3：Review Queue 优先级排序算法
- P2-4：专家档案 API + UI（领域多选框）
- P2-5：知识提取入口 UI（Review Queue 驱动问答）
- **验收**：专家可通过逐条问答完成 5 条 Review Queue 条目审核

### Phase 3：规则质量保障（3 周）
- P3-1：规则适用范围字段（`applicable_when` / `not_applicable_when`）加入 FocusPoint 解析
- P3-2：冲突检测（`rule_conflict_detector.py`，LLM 辅助比对）
- P3-3：Pending 提案面板 UI
- P3-4：Approve 流程（写入 `review_domain.md`）
- P3-5：规则回测基础实现（`backtest_runner.py`，异步）
- **验收**：提案经二审可写入 skill 包；冲突规则有标注

### Phase 4：专家上传文档提取（2 周）
- P4-1：素材上传 API（复用现有 ingest 管线）
- P4-2：文档驱动提取提示框架（策略二/四为主）
- P4-3：文档与现有规则映射展示
- **验收**：上传规则文档后可对话式澄清并产出 KnowledgeItem

---

## 十四、关键设计决策与权衡

### 决策 1：Review Queue 是否独立于 evolution_queue

**选择**：DB 表独立（`review_queue`），文件格式与 `evolution_queue` JSONL 分开。  
**理由**：`evolution_queue` 是「LLM 自生成的改进建议」；`review_queue` 是「人工验证的中间状态」，语义不同，分开便于独立查询和权重控制。

### 决策 2：规则适用范围的表达方式

**选择**：YAML 结构化 `applicable_when` + 自然语言 `scope_note` 并存。  
**理由**：结构化字段支持机器过滤（分析前预筛选）；自然语言供人阅读和 LLM 提示注入。

### 决策 3：审查后追问与知识提取入口的关系

**选择**：两者并存，共用后端 knowledge_models 和 Review Queue，但 UI 入口分离。  
**理由**：审查后追问效率高但依赖项目语境；独立提取入口支持系统性的规则库建设。

### 决策 4：Pending 提案的二审人数

**选择**：当前阶段为单人（资深顾问自审，或另一位资深顾问审）；未来多用户时约束「不可自审」。  
**理由**：现阶段无多用户系统，强制他审无法实施；先建立流程，权限体系后补。

---

## 十五、未来扩展方向

1. **多用户 RBAC**：角色认证系统，资深顾问角色通过登录获取而非环境变量
2. **规则知识图谱**：知识条目之间的依赖/矛盾关系可视化
3. **自动回测 CI**：新规则合并到 skill 包时自动触发历史项目回测
4. **跨组织知识共享**：`<org>/.aika/shared-skills/` 组织级技能包（需隐私隔离）
5. **提问策略学习**：记录哪种策略对哪类专家效果最好，自动调整
