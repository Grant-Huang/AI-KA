# ProjectLens（AI-KA）
智能项目分析与评审平台

详细设计文档（Detailed Design）

V1.3  |  2026-04-12

---

## 版本历史

| 版本 | 日期 | 修改内容 | 作者 |
| :-- | :-- | :-- | :-- |
| V1.3 | 2026-04-12 | 活动规则文件「组合使用建议」固定 **五列表** 解析/写回；`focus_combo_tips` / `focus_presets` 含 `review_role`、`review_goals_principles`、`output_requirements`；`build_system_prompt` 用预设三字段覆盖默认角色/原则/输出段落；`POST …/analyze/stream`（及会话流）请求体可选传入上述三字段；环境变量 `AIKA_RULES_FILENAME` 切换规则文件 | AI 协作 |
| V1.2 | 2026-04-10 | 索引器双策略、`locator_json` 扩展字段；`list_chunk_entries`；`build_user_prompt_from_entries` 块头；`analyze/stream` 追加索引表；`GET/POST /api/v1/settings` 的 `chunk_strategy`；`index-md` 传入策略 | AI 协作 |
| V1.1 | 2026-03-25 | 基于《需求与设计文档 V1.0》补齐详细设计：模块边界、数据模型、接口契约、时序、异常与审计 | AI 协作 |

---

## 1. 设计目标与原则

### 1.1 目标

- 在不改变 V1.0 需求意图的前提下，把核心能力拆成可实现的模块，并明确：
  - **服务边界**（谁负责什么，禁止跨层复制逻辑）
  - **接口契约**（统一输入输出、错误码、幂等）
  - **数据模型**（最小可行表结构与索引建议）
  - **关键流程时序**（索引/分析/报告）
  - **安全与审计**（最小可用）

### 1.2 设计原则（必须遵守）

- **统一接口调用**：LLM、Embedding、向量库、文档解析、报告导出均通过 Provider/Adapter 接口封装。
- **证据优先**：任何自动生成结论，必须能回链到原文 chunk（或标记“需人工核实”）。
- **失败可恢复**：长流程按阶段持久化中间状态，可从断点恢复。
- **最小改动/渐进式**：先支持 `.md/.txt` 与基础提取，逐步扩展 `.docx/.pdf/.xlsx`。
- **不在日志中输出敏感信息**：密钥、原文全文、个人信息默认不记录。
- **报告生成外置**：docx 输出由 `epic-doc` 完成，本项目只生成 JSON/块结构并调用。

---

## 2. 逻辑架构与模块划分

### 2.1 逻辑模块（后端）

- **Project Service**
  - 项目元数据、标签、快照、审计入口
- **Document Service**
  - 文档扫描、解析、结构化、分块、索引
- **Embedding Service**
  - Chunk 向量化（Provider）
- **Vector Store Service**
  - 向量入库/检索（Adapter）
- **LLM Gateway**
  - 统一调用不同模型（Provider），含重试/限流/统计
- **Analysis Orchestrator**
  - 分析任务编排：按文档/按 chunk 并行执行，聚合结果落库
- **Annotation Service**
  - 标注 CRUD、版本/审阅、证据链接
- **Report Service**
  - 报告章节结构、引用/表格/图表数据组装，调用 `epic-doc` 生成 docx

### 2.2 统一 Provider/Adapter 接口（契约）

> 注意：此处仅定义接口形状与约束，不实现重复逻辑。

- `LLMProvider`
  - `chat(prompt, context, params) -> LLMResult`
  - 约束：支持超时、重试、fallback；返回 token 用量（若可得）
- `DocumentParser`
  - `parse(file_path) -> ParsedDocument`
  - 约束：输出统一的“段落/标题/表格/图片占位”结构
- `Chunker`
  - `chunk(parsed_document, strategy) -> list[Chunk]`
  - 约束：chunk 必须携带可回溯定位信息（段落 id / 偏移）
- `EmbeddingProvider`
  - `embed(texts: list[str]) -> list[vector]`
- `VectorStoreAdapter`
  - `upsert(chunks_with_vectors)`
  - `query(vector, filters, top_k)`
- `ReportRenderer`（外置）
  - `render_epic_doc(config_json) -> docx_bytes/path`

---

## 3. 数据模型（建议：关系库 + 向量库）

### 3.1 关系库表（最小可行）

> 说明：字段名与类型为建议形状，具体实现可按 SQLite/PG 调整。

#### 3.1.1 projects

| 字段 | 类型 | 约束 | 说明 |
| :-- | :-- | :-- | :-- |
| id | uuid | PK | 项目 ID |
| name | text | not null | 项目名称 |
| root_path | text | not null | 文件根目录 |
| industry | text |  | 行业 |
| scale | text |  | 规模 |
| tags_json | text/json |  | 标签 |
| created_at | datetime | not null | 创建时间 |
| updated_at | datetime | not null | 更新时间 |

索引建议：
- `(updated_at)`
- `(industry)`

#### 3.1.2 documents

| 字段 | 类型 | 约束 | 说明 |
| :-- | :-- | :-- | :-- |
| id | uuid | PK | 文档 ID |
| project_id | uuid | FK | 项目 |
| stage | text |  | 阶段（调研/蓝图/设计…） |
| path | text | not null | 相对路径（相对 root_path） |
| ext | text | not null | 扩展名 |
| sha256 | text |  | 文件指纹（用于增量） |
| mtime | datetime |  | 修改时间 |
| status | text | not null | indexed/chunked/embedded/analyzed/error |
| parse_error | text |  | 错误摘要（不含敏感全文） |

索引建议：
- `(project_id, stage)`
- `(project_id, status)`
- `(project_id, sha256)`

#### 3.1.3 document_chunks

| 字段 | 类型 | 约束 | 说明 |
| :-- | :-- | :-- | :-- |
| id | uuid | PK | chunk ID |
| document_id | uuid | FK | 文档 |
| chunk_index | int | not null | 顺序 |
| text | text | not null | chunk 文本（可裁剪存储/或外置） |
| token_count | int |  | 估算 token |
| locator_json | text/json |  | 定位信息（段落 id、偏移、页码等） |

**locator_json（当前实现补充）**：除 `start_line` / `end_line` / `paragraph_count` 外，可含 `kind`（`blank` | `md_structured` | `txt_plain`）、`heading_path`（字符串数组）、`section_level`、`section_title`；`blank` 策略下章节类字段可为空，下游展示时用「—」占位。

索引建议：
- `(document_id, chunk_index)`

#### 3.1.3.1 索引与提示词（Web 分析链路）

- **索引器**（`src/aika/indexer.py`）：`sync_project` / `sync_project_md_root` 接收 `chunk_strategy`；Web 调用 `index-md` 时**必须**传入设置中的策略（不得仅依赖环境变量）。CLI 无设置文件时可用 `AIKA_CHUNK_STRATEGY` 作为后备，默认 `blank`。
- **数据访问**（`src/aika/db.py`）：`list_chunk_entries(project_id, limit)` 返回 `doc_path`、`chunk_index`、`text`、解析后的 `locator`；`list_chunk_texts` 可视为对其封装。
- **提示词**（`web/backend/prompt_builder.py`）：`build_user_prompt_from_entries` 生成带「片段 n | 文件 | 章节 | 行」的块头；`format_chunk_index_markdown` 生成文末 GFM 索引表。
- **分析 API**（`web/backend/main.py`）：流式结束后将模型输出规范化 Markdown，再**拼接**上述索引表（仅包含实际送入模型的片段）。

#### 3.1.3.2 规则文件、`focus_presets` 与审查系统提示（当前 Web）

- **活动规则文件路径**：`$AIKA_REPO_ROOT` 下文件名由环境变量 `AIKA_RULES_FILENAME` 指定，默认 `rules.md`。
- **关注点**：行级解析 `### focus:<id> | <名称>`，正文为 Prompt；强校验二级标题结构，禁止误用 `### 组合使用建议`（须用 `## 组合使用建议`）。
- **「组合使用建议」表格**：仅解析 **固定五列** 数据行（表头/列序：`评审节点` | `推荐组合的关注点` | `审查角色` | `审查目标与原则` | `输出要求`）。单元格编码：换行 ↔ `<br>`，`|` ↔ `&#124;`（实现见 `web/backend/main.py` 中 `_combo_cell_encode` / `_combo_cell_decode`）。
- **派生对象**：
  - `focus_combo_tips[]`：每行对应 `stage`、`recommended`、`review_role`、`review_goals_principles`、`output_requirements`。
  - `focus_presets[]`：由表格与关注点名称映射生成，含 `id`、`name`、`focus_points` 及上述三字符串字段（可空）。
- **设置持久化**：`POST /api/v1/settings` 可保存 `focus_points`、`focus_presets`；写回规则文件时组合节重写为五列表。
- **分析请求体**（非会话与会话流式 analyze）：除 `focus_points`、`chunk_limit` 等外，可选 `review_role`、`review_goals_principles`、`output_requirements`。非空时传入 `build_system_prompt`（`web/backend/prompt_builder.py`），用于**覆盖**默认「审查角色 / 审查目标与原则 / 输出要求」段落（含与 `MARKDOWN_OUTPUT_HINT` 相关的输出结构约定）。
- **前端**：设置页「规则」分为子 Tab「关注点」「预设组合」；首页选预设后随请求带上三字段（与 `focus_presets` 对齐）。

#### 3.1.4 annotations

| 字段 | 类型 | 约束 | 说明 |
| :-- | :-- | :-- | :-- |
| id | uuid | PK | 标注 ID |
| project_id | uuid | FK | 项目 |
| chunk_id | uuid | FK | 证据 chunk |
| type | text | not null | requirement/risk/decision/dependency/knowledge |
| content | text | not null | 标注内容 |
| source | text | not null | ai_generated/human |
| confidence | text |  | high/medium/needs_review |
| status | text |  | confirmed/pending/out_of_scope（需求类） |
| module | text |  | 业务模块归属 |
| tags_json | text/json |  | 标签 |
| is_verified | bool | not null | 是否已验证 |
| created_by | uuid/text |  | 创建者 |
| created_at | datetime | not null | 创建时间 |
| updated_at | datetime | not null | 更新时间 |

索引建议：
- `(project_id, type)`
- `(project_id, is_verified)`
- `(project_id, confidence)`

#### 3.1.5 analysis_jobs

| 字段 | 类型 | 约束 | 说明 |
| :-- | :-- | :-- | :-- |
| id | uuid | PK | 任务 ID |
| project_id | uuid | FK | 项目 |
| job_type | text | not null | extract_requirements/extract_risks/... |
| scope_json | text/json | not null | 文档范围（doc_ids / stage / filters） |
| llm_config_json | text/json |  | 模型覆盖配置 |
| status | text | not null | queued/running/partial_success/succeeded/failed/cancelled |
| progress | int | not null | 0-100 |
| error_code | text |  | 错误码 |
| error_message | text |  | 错误摘要 |
| started_at | datetime |  | 开始时间 |
| finished_at | datetime |  | 结束时间 |

索引建议：
- `(project_id, status)`
- `(project_id, started_at)`

#### 3.1.6 reports / report_versions（建议拆分）

**reports**

| 字段 | 类型 | 约束 | 说明 |
| :-- | :-- | :-- | :-- |
| id | uuid | PK | 报告 ID |
| project_id | uuid | FK | 项目 |
| title | text | not null | 标题 |
| template_id | uuid/text |  | 模板 |
| status | text | not null | draft/frozen/exported |
| created_at | datetime | not null | 创建时间 |

**report_versions**

| 字段 | 类型 | 约束 | 说明 |
| :-- | :-- | :-- | :-- |
| id | uuid | PK | 版本 ID |
| report_id | uuid | FK | 报告 |
| version_no | int | not null | 版本号 |
| content_json | text/json | not null | 章节/块内容（含引用） |
| frozen_at | datetime |  | 冻结时间 |
| frozen_by | uuid/text |  | 冻结人 |

---

## 4. API 设计（契约级）

### 4.1 统一约定

- 统一返回结构（`status/data/message`）
- 错误码建议：
  - `VALIDATION_ERROR`
  - `NOT_FOUND`
  - `FORBIDDEN`
  - `CONFLICT`
  - `PARSER_ERROR`
  - `LLM_TIMEOUT`
  - `LLM_RATE_LIMIT`
  - `VECTOR_STORE_ERROR`
  - `REPORT_RENDER_ERROR`

### 4.2 核心接口（示例形状）

> 这里给到“契约与字段”，具体路径可沿用 V1.0 的 `/api/v1/...`。

- `POST /projects`
  - 入参：`name, root_path, industry, scale, tags`
  - 出参：`project`
- `POST /projects/{id}/sync`
  - 行为：扫描增量变更，更新 documents 状态
- `GET /projects/{id}/documents`
  - 出参：`documents[]`（含 status）
- `POST /analysis/jobs`
  - 入参：`project_id, job_type, scope, llm_config`
  - 出参：`job_id`
- `GET /analysis/jobs/{id}`
  - 出参：状态、进度、错误摘要、统计
- `GET /analysis/jobs/{id}/results`
  - 出参：`annotations[]` 或聚合视图
- `POST /reports`
  - 入参：`project_id, template_id, title`
  - 出参：`report`
- `POST /reports/{id}/export`
  - 入参：`format: docx|pdf|md`，可选 `version_id`
  - 出参：下载信息（或 bytes 流）
- `GET/POST /api/v1/settings`
  - 出参/入参（摘要）：含 `focus_points`、`focus_combo_tips`、`focus_presets`（预设含 `review_role`、`review_goals_principles`、`output_requirements`）、`chunk_strategy`、`llm_settings`、`rules_md_error`、`rules_filename` 等（以 OpenAPI/代码为准）。
- `POST /api/v1/projects/{id}/analyze/stream`（及会话维度同类流式 analyze）
  - 请求体可选：`review_role`、`review_goals_principles`、`output_requirements`（与所选预设一致时由前端填充）。

---

## 5. 关键流程时序（从文件到报告）

### 5.1 项目同步与索引（Sync）

1) 用户点击“同步项目”
2) `Project Service` 读取目录清单（增量：对比 `sha256/mtime`）
3) 新/变更文档进入 `Document Service.parse`
4) 解析成功 → `Chunker.chunk` → `EmbeddingProvider.embed` → `VectorStoreAdapter.upsert`
5) 任一步失败：
   - 文档标记 `status=error`
   - 记录 `parse_error`（摘要）
   - 允许用户触发“重试”或“跳过”

### 5.2 分析任务（Analysis Job）

1) 用户在分析工作台选择范围与任务类型
2) 创建 `analysis_jobs(status=queued)`
3) `Analysis Orchestrator` 拉取任务执行：
   - 读取 scope 下的 chunks
   - 按“文档/并发上限”批量调用 `LLMGateway.chat`
   - 解析 LLM 结果为 `annotations`（source=ai_generated）
4) 聚合与落库
5) 返回 `partial_success/succeeded/failed`

### 5.3 报告生成（Report → epic-doc）

1) 报告编辑器保存 `report_versions.content_json`
2) 导出时 `Report Service`：
   - 基于模板把 `content_json` 转换为 `epic-doc` blocks
   - 调用 `epic-doc generate config.json -o out.docx` 或库 API
3) 记录导出审计：导出者、时间、格式、版本号、文件哈希

---

## 6. 异常处理与幂等

### 6.1 解析与分块异常

- 解析失败：保留原文件记录，状态置 `error`，允许重试
- 分块失败：保留 parse 结果，允许更换 chunk 策略重试
- 幂等要求：同一 `document.sha256` 重复同步不应创建重复 chunks

### 6.2 LLM 异常

- 超时：可重试（带退避），重试仍失败则该文档标记失败
- 限流：自动降速或切换备用 provider（若配置）
- 输出不合法：落 `needs_review`，并记录“解析失败原因”

### 6.3 向量库异常

- upsert 失败：可重试；持续失败时阻断“语义检索/跨文档关联”，但不阻断“纯 LLM 分析”（可降级）

---

## 7. 审计与安全（最小可用）

### 7.1 审计事件（建议）

- 项目：创建/删除/改配置/创建快照
- 文档：同步、重新解析、重新向量化
- 分析：创建任务、取消、重试、导出结果
- 报告：创建、冻结、导出、分享
- 配置：模型 key 变更、提示词模板变更、权限变更

### 7.2 日志脱敏

- 不记录 API Key
- 不记录原文全文（最多记录 chunk_id 与片段长度/哈希）

---

## 8. 与 `epic-doc` 集成要求（给对方项目的修改建议）

若你希望 `epic-doc` 更适配本项目，建议他们支持/强化以下能力（按优先级）：

1) **更完整的 JSON Schema**
   - 不仅声明 `blocks.type`，还声明各 block 类型字段（heading: text/level；table: data/style/merge；chart: type/data；flowchart: nodes/edges…）。
2) **块级“引用来源”元数据**
   - 支持在 block 上挂 `meta` 字段（如 `source: {doc, chunk, offsets}`），便于在 docx 中生成脚注/引用表。
3) **表格合并与列宽的强约束提示**
   - 当 merge/col_widths 未设置时给出 lint/validate 的明确错误信息，避免生成出来错版。
4) **Markdown → blocks 的官方转换器（可选）**
   - 让本项目可以先产出 Markdown，再由转换器变成 blocks JSON，降低模板维护成本。

