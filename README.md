# AI-KA（ProjectLens）- 开发基线

本仓库当前阶段目标：按 `docs/ProjectLens_行动计划_V1.0.md` 落地 **M0（工程基线）** 与 **M1（文档索引 MVP）**。

## 1. CLI（M0/M1）

安装（开发模式）：

```bash
python -m pip install -e .
```

初始化一个项目（写入 SQLite 索引）：

```bash
aika project init --name "demo" --root "./docs"
```

同步（扫描 `.md/.txt`，增量更新 `sha256/mtime`，生成 chunk 定位）：

```bash
aika project sync --project "demo"
```

查看项目与文档：

```bash
aika project list
aika doc list --project "demo"
```

## 2. Word 文档导出（只调用 epic-doc）

请参考 `docs/epic-doc/README.md`。

## 3. Web 前端 + 本机后端（docs2md / 流式分析 / epic-doc）

### 3.1 安装

```bash
python -m pip install -e . --no-build-isolation
```

**升级 docs2md（Git 源，非 PyPI 固定版）**：依赖在 `pyproject.toml` 中指向 `git+https://github.com/Grant-Huang/docs2md.git`。若需拉取上游最新提交（例如图片解析、格式支持更新），在已激活的虚拟环境中执行：

```bash
python -m pip install -U "docs2md @ git+https://github.com/Grant-Huang/docs2md.git"
```

然后重新安装本仓库（`python -m pip install -e .`）或重启后端，使运行中的进程使用新包。

前端（开发态你自己跑；发布时由 CI 负责 `npm run build` 并将 `dist` 打进 wheel）：

```bash
cd web/frontend
npm install
npm run dev
```

### 3.2 环境变量

| 变量 | 说明 |
|------|------|
| `DOCS2MD_ROOT` | 可选：本地克隆的 [docs2md](https://github.com/Grant-Huang/docs2md) 仓库根目录（用于覆盖默认安装的 docs2md；需含 `all2md.py`） |
| `DOCS2MD_PYTHON` | 可选，默认与启动后端的 Python 解释器相同（`sys.executable`），避免与系统 `python` 混用导致 docs2md 版本/环境变量不一致 |
| `AIKA_PROJECTS_ALLOW_PREFIX` | 可选，限制用户只能注册该前缀下的目录 |
| `AIKA_ENABLE_NATIVE_FOLDER_PICKER` | 可选，默认开启：由本机后端弹出系统文件夹对话框并返回绝对路径（`/api/v1/fs/pick-directory`） |
| `AIKA_FS_PICKER_LOCALHOST_ONLY` | 可选，默认开启：仅当从本机访问 API 时允许目录选择（防止远端触发服务器弹窗） |
| `AIKA_LLM_PROVIDER` | `openai_compatible` 或 `mock`（离线演示） |
| `AIKA_LLM_BASE_URL` | OpenAI 兼容 API 根 URL |
| `AIKA_LLM_API_KEY` | API Key（或使用 `OPENAI_API_KEY`） |
| `AIKA_LLM_MODEL` | 模型名 |
| `AIKA_WEB_HOST` / `AIKA_WEB_PORT` | 后端监听，默认 `127.0.0.1:8765` |
| `AIKA_REPO_ROOT` | 可选，显式指定本仓库根（用于 `.tmp`、SQLite、`review_skill_packages` 等路径解析） |
| `AIKA_REVIEW_SKILL_PACKAGES_ROOT` | 可选，审查技能包根目录；未设置时默认为 `$AIKA_REPO_ROOT/review_skill_packages`。每个包为 `package_id/review_domain.md` 与 `manifest.json`（见 `docs/aika_spec/PACKAGE_LAYOUT.md`）。 |
| `AIKA_CHUNK_STRATEGY` | 可选，`blank` 或 `structured`：仅当**无** Web 保存的 `app_settings.md` 时作为 CLI/自动化默认；**Web 端以设置页为准**。 |

### 3.3 启动后端

```bash
aika-web
# 或
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
```

浏览器打开 Vite 提示的地址（默认 `http://localhost:5173`），通过代理访问 `/api`。

### 3.3.1 Docker 部署

在项目根目录执行 `docker compose up -d --build`，浏览器访问 **http://localhost:8765**（前后端同源）。详细说明见 [docs/docker-deploy.md](docs/docker-deploy.md)。

### 3.4 使用流程（一键分析）

1. **分析配置**：设定 chunk 上限、**分块方式**（空行分块 / 标题与结构感知）、选择关注点。若当前活动审查技能包的 `review_domain.md` 含有「组合使用建议」**五列表**（评审节点、推荐组合的关注点、审查角色、审查目标与原则、输出要求），首页关注点下拉框后会显示 `Tips` 入口用于快速参考；表格与单元格转义约定见根目录 `helpme.md`。**修改分块方式后须重新执行索引**，否则分析仍基于旧分块。
2. **选择项目**：点击「选择项目」由本机后端回填**绝对路径**（后端进程必须可读）。当前按单项目目录处理：一次选择一个目录并分析一个项目。
3. 点击 **「开始分析」**：自动顺序执行——**docs2md 转换**（SSE 日志写入「后台日志」弹窗）→ **索引 Markdown**（将 `md_out` 下 Markdown 扫描入库并分块）→ **大模型流式审查**（`POST /api/v1/projects/{id}/conversations/{conversation_id}/analyze/stream`，请求体含 `chunk_limit` 与本次勾选的 `focus_points`，系统按当前活动包的 `review_domain.md`/设置中的关注点 name+prompt 生成审查提示；「过程流式输出」区域展示）。
4. **导出 docx**：分析完成后可导出；依赖 `epic-doc`；若缺少 LibreOffice/pandoc/graphviz 等系统依赖，启动或导出时会提示安装方式。

### 3.5 设置与帮助

- 设置页包含：`chunk 上限`、**分块方式**、`关注点`、`Model`。
- 终端用户说明见 [docs/User_Manual_zh.md](docs/User_Manual_zh.md)；部署与运维见 [docs/System_Admin_Manual_zh.md](docs/System_Admin_Manual_zh.md)。
- `Model` 支持分别配置文本链路与 VL 链路（Provider/Base URL/Model + 独立 API Key）。
- 关注点支持从本机 Markdown **导入审查域**（先校验后写入当前活动包的 `review_domain.md`）；默认模板为仓库根 `default_skills.md`（首次初始化默认包时复制）；亦可用 `scripts/migrate_legacy_to_skill_package.py` 或 `POST /api/v1/skill-packages/migrate-legacy-file`（默认源文件 `default_skills.md`）导入。
- 帮助页内容来自仓库根目录 `helpme.md`（若不存在会回退读取 `docs/helpme.md`）。文件中需包含二级标题 **功能简介、操作流程、审查域说明、设置指南、常见问题**，前端将据此拆成多个 Tab 展示；否则整页渲染原文。

排障时可在「高级：分步执行」中单独运行 docs2md、索引或仅大模型分析。

**为何历史上「索引」曾需要单独点击**：转换与索引职责不同——转换是长时间子进程写 `md_out`，索引依赖转换产物；拆步便于重试。当前产品默认一键串联，无需再手动点索引。

### 3.6 通用业务文档审查能力（详细）

ProjectLens 的核心是「审查技能包 / `review_domain.md` 可配置关注点 + Prompt」，因此本质上是通用业务关联性文档审查工具，而非仅限交付实施项目。

可扩展审查场景示例：

- 合规/风控：制度条款覆盖、职责边界、证据留痕、审计可追溯性。
- 合同/招采：交付物与验收标准完整性、违约责任、范围蔓延风险。
- 产品/运营：需求边界、例外流程、口径一致性、可执行性检查。
- 数据治理：指标定义一致性、主数据责任、字段口径冲突识别。
- 技术架构/接口：上下游依赖、异常处理、降级策略、一致性约束。

建议做法：

1. 在 `review_domain.md`（或模板 `default_skills.md`）里把关注点设计为“可迁移维度”（如一致性、完整性、可执行性、风险与控制、证据与追溯）。
2. 每个关注点 Prompt 同时包含：审查目标、证据要求、输出格式要求。
3. 通过首页“关注点子集”按场景组合复用（蓝图评审、合规检查、上线门禁等）。

## 4. 目录约定

- 代码：`src/`（CLI 库 `aika`）、`web/backend`（包名 `backend`）
- 前端：`web/frontend/`
- 测试：`tests/`
- 临时数据：`.tmp/`（已加入 `.gitignore`）

## 5. 离线 pip 说明

若构建隔离环境无法联网，请使用：

`python -m pip install -e . --no-build-isolation`

