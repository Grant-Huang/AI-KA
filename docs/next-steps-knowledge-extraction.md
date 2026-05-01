# 下一步工作计划：知识提取功能

**日期**：2026-04-30  
**对应设计文档**：`design-knowledge-extraction.md` v0.3

---

## 当前状态（代码审查结论）

### 已有基础
- `evolution_queue.py`：JSONL 追加队列，可扩展
- `personal_memory.py`：`~/.aika/memory/` 结构，可存专家档案
- `conversation_fsm.py`：会话状态机，可加 `EXTRACTING` 模式
- `finding_parser.py`：HTML 注释解析，可仿写 `ki_parser.py`
- `skill_manifest.py` + `review_skill_packages/`：技能包结构就绪

### 缺失的关键部分
1. `evolution_queue.py` 无 `source_role`/`source_type`/`status` 字段——**无法区分信号来源，污染风险存在**
2. `FocusPoint` 无 `applicable_when` 字段——**规则无条件触发**
3. 无 Review Queue 独立 DB 表——**候选知识无管理界面**
4. 无角色模型——**知识提取入口对所有人开放**（未来问题）
5. 无 Pending 规则提案流程——**规则无审核机制**

---

## 优先级排序原则

> **先堵漏洞，再建新功能。**  
> Phase 0 修 evolve-hint 污染问题是最高优先级，因为当前每次审查都在累积未受控的改进建议。

---

## Phase 0：堵漏洞——信号溯源（1-2 周）

**目标**：让所有写入 Review Queue 的信号都有来源标记，为后续权重控制打基础。

### 任务清单

| ID | 任务 | 文件 | 工时估算 |
|---|---|---|---|
| P0-1 | 扩展 `append_evolve_hint()`：加 `source_role`、`source_type`、`status`、`project_id` 参数 | `evolution_queue.py` | 0.5d |
| P0-2 | 创建 DB 表 `review_queue`（见设计文档 §12.2）；从 evolve-hint JSONL 迁移数据 | `db.py` | 1d |
| P0-3 | Review Queue CRUD API：GET（按优先级排序）、PATCH status、DELETE | `routers/review_queue.py` | 1d |
| P0-4 | 在 `main.py` 的 evolve-hint 写入点，注入 `source_role`（从环境变量 `AIKA_USER_ROLE` 读取）| `main.py` | 0.5d |
| P0-5 | 补测试：`test_review_queue.py` | `tests/` | 0.5d |

**验收**：
- `pytest tests/test_review_queue.py` 全过
- evolve-hint 写入后在 `/api/v1/review-queue` 可见，且有 `source_role` 字段

---

## Phase 1：审查后追问模式（2-3 周）

**目标**：最小可用的知识提取入口——不需要额外工具，利用真实项目语境。

### 任务清单

| ID | 任务 | 文件 | 工时估算 |
|---|---|---|---|
| P1-1 | `post-review-extraction/stream` SSE 端点（复用 analyze/stream 骨架） | `routers/extraction.py` | 2d |
| P1-2 | 追问提示框架（策略一 + 策略三，见设计文档 §5.1）| `prompt_builder.py` | 1d |
| P1-3 | `ki_parser.py`：解析 `<!-- ki: {...} -->` 和 `<!-- satisfaction: x.x -->` 标记 | `ki_parser.py` | 1d |
| P1-4 | 追问会话输出写入 Review Queue（`source_type: "post_review"`）| `routers/extraction.py` | 0.5d |
| P1-5 | 前端：审查输出底部追问入口（`AIKA_USER_ROLE=senior_expert` 时显示） | `App.tsx` | 1d |
| P1-6 | 前端：追问对话 UI（复用现有对话组件，新加 KnowledgeItem 侧边卡片）| `App.tsx` | 1.5d |

**验收**：
- 完成一次项目审查后，资深顾问可在审查结果底部输入追问
- 追问对话结束后，知识条目出现在 Review Queue，有 `source_type: post_review`

---

## Phase 2：LLM 提问引擎（3-4 周）

**目标**：独立的知识提取入口，Review Queue 驱动的结构化问答。

### 任务清单

| ID | 任务 | 文件 | 工时估算 |
|---|---|---|---|
| P2-1 | `knowledge_models.py`：KnowledgeItem、ReviewQueueItem dataclasses（含新字段）| `knowledge_models.py` | 1d |
| P2-2 | 四种提问策略 prompt 模板实现（见设计文档 §5.1）| `prompt_builder.py` | 2d |
| P2-3 | 满意度驱动的多轮控制逻辑（`<!-- satisfaction: x.x -->` → 自动推进或追问）| `routers/extraction.py` | 1.5d |
| P2-4 | Review Queue 优先级排序（`occurrences × days_since_last × confidence`）| `routers/review_queue.py` | 0.5d |
| P2-5 | 专家档案 API：GET/PUT `/api/v1/expert-profile`，存 `~/.aika/memory/user/expert_profile.md` | `routers/extraction.py` | 0.5d |
| P2-6 | 前端：知识提取模式侧边导航（Review Queue 列表、专家档案）| `App.tsx` | 1d |
| P2-7 | 前端：专家领域多选框（首次进入时触发）| `App.tsx` | 0.5d |
| P2-8 | 前端：Review Queue 驱动的逐条问答 UI | `App.tsx` | 2d |
| P2-9 | 补测试 | `tests/` | 1d |

**验收**：
- 专家首次进入知识提取入口，看到领域多选框（从 Review Queue 话题生成）
- 专家逐条回答 Review Queue 候选条目，多轮到满意度达标自动进入下一条
- 产出的 KnowledgeItem 包含 `applicable_when` 字段（若未追问到则标记为 `scope_unclear`）

---

## Phase 3：规则质量保障（3 周）

**目标**：Pending 审核流程 + 适用范围字段 + 冲突检测。

### 任务清单

| ID | 任务 | 文件 | 工时估算 |
|---|---|---|---|
| P3-1 | FocusPoint 解析支持 `applicable_when` / `not_applicable_when` YAML 字段 | `skills/focus_point_io.py` | 1d |
| P3-2 | `build_system_prompt` 注入前按项目档案过滤不适用规则 | `prompt_builder.py` | 1d |
| P3-3 | `rule_conflict_detector.py`：LLM 辅助比对新规则与现有规则 | `rule_conflict_detector.py` | 1.5d |
| P3-4 | Pending 提案 CRUD API + Approve 写入 `review_domain.md` 逻辑 | `routers/pending_rules.py` | 2d |
| P3-5 | 前端：Pending 面板（规则预览 + 适用范围标签 + 冲突高亮 + Approve/Reject 操作）| `App.tsx` | 2d |
| P3-6 | `backtest_runner.py` 基础实现（异步任务，对历史项目 dry-run）| `backtest_runner.py` | 2d |
| P3-7 | 补测试 | `tests/` | 1d |

**验收**：
- 提案审核流：KnowledgeItem → Submit → Pending（含冲突标注）→ Approve → 写入 skill 包
- `applicable_when` 字段可在设置页关注点编辑界面看到和修改

---

## Phase 4：专家上传文档提取（2 周）

**目标**：支持专家上传规则文档，LLM 基于文档设计澄清问题。

| ID | 任务 | 文件 | 工时估算 |
|---|---|---|---|
| P4-1 | 素材上传端点（复用 `docs2md_runner.py` + ingest 管线）| `routers/extraction.py` | 1d |
| P4-2 | 文档驱动提取提示框架（策略二/四，见设计文档 §5.1）| `prompt_builder.py` | 1.5d |
| P4-3 | 文档内容与现有关注点的映射展示（"您文档中的 X 对应现有规则 Y"）| `routers/extraction.py` | 1d |
| P4-4 | 前端：素材上传 + 文档驱动问答 UI | `App.tsx` | 1.5d |

---

## 关键依赖与风险

### 依赖关系
```
Phase 0（evolve-hint 溯源）
    ↓
Phase 1（审查后追问）← 可以先独立启动
    ↓
Phase 2（提问引擎）
    ↓
Phase 3（规则质量保障）← P3-1 需要 Phase 2 的 applicable_when 字段
    ↓
Phase 4（文档提取）← 可以并行 Phase 3 后半段
```

### 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 满意度评分不稳定（LLM 输出 satisfaction 值波动大）| Phase 2 提问引擎体验差 | 先用固定轮数（3轮）兜底，满意度作为优先判断 |
| `applicable_when` 字段在提取时难以稳定输出 | Phase 2/3 规则质量 | 提取时允许缺省（`scope_unclear`），在 Pending 审核时由专家手填 |
| 冲突检测漏报（LLM 视角的语义相似性有限）| Phase 3 规则冗余 | 冲突检测为辅助提示，不阻断 Approve 流程 |
| 回测项目档案不足（历史项目无 `outcome.md`）| Phase 3 回测功能价值有限 | Phase 3 回测作为可选功能，有历史档案才触发 |

---

## 不做的事（边界）

- **不做多用户认证系统**：角色通过环境变量控制，RBAC 是未来版本目标
- **不做知识图谱可视化**：知识条目间关系以纯文本冲突提示为主
- **不做自动 Approve**：任何规则变更必须有人工审核动作
- **不把普通顾问的发现反馈变成规则**：发现反馈只影响该项目记忆，不影响全局 skill

---

## 与现有 m1-m6 里程碑的关系

| 现有里程碑 | 知识提取 Phase | 关系 |
|---|---|---|
| m5-recall（记忆检索）| Phase 2 前置 | 专家档案存入 `~/.aika/memory/`，复用 recall 机制 |
| m3-hooks（钩子）| Phase 1 可用 | 审查后追问入口可注册为 `on_after_analyze` 钩子 |
| m4-tool-registry | Phase 3 | 冲突检测器、回测任务可注册为内部 Tool |
| m6-test-gate | 每个 Phase | 每 Phase 末尾要求 pytest 全量通过 |
