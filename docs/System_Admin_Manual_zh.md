# AI-KA（ProjectLens）系统管理员手册

面向负责部署、升级与排错的管理员。

## 1. 部署概览

- **Docker Compose**（推荐）：项目根目录 `docker compose up -d --build`，默认 **http://localhost:8765**（前后端同源）。步骤摘要见 [docker-deploy.md](docker-deploy.md)。
- **本机开发**：`aika-web` 或 `uvicorn backend.main:app`；前端可单独 `npm run dev` 并配置 API 基址。

## 2. 端口、卷与 `AIKA_REPO_ROOT`

- 监听地址与端口：`AIKA_WEB_HOST` / `AIKA_WEB_PORT`（默认 `127.0.0.1:8765`）。  
- 数据目录：默认使用仓库根下 `.tmp/`（SQLite、`md_out`、导出等）。Compose 通常将 `/app/.tmp` 映射到命名卷。  
- **`AIKA_REPO_ROOT`**：显式指定「视为仓库根」的路径；容器内一般为 `/app`，用于解析 `app_settings.md`、`rules.md`、`.tmp` 等。

## 3. 环境变量（摘要）

| 变量 | 说明 |
|------|------|
| `AIKA_CORS_ORIGINS` | 允许的前端来源，逗号分隔。 |
| `AIKA_REPO_ROOT` | 仓库根路径。 |
| `AIKA_RULES_FILENAME` | （可选）活动规则文件名，相对于 `AIKA_REPO_ROOT`，默认 `rules.md`。设为例如 `rules_new2.md` 时，后端只加载该文件作为关注点与「组合使用建议」来源，不自动合并其他规则文件。 |
| `AIKA_CHUNK_STRATEGY` | `blank` 或 `structured`：**仅**在缺少 Web 写入的 `app_settings.md` 时作为 CLI/脚本的默认分块策略；**Web 用户以设置页保存的 `chunk_strategy` 为准**。 |
| `AIKA_LLM_PROVIDER` | 文本模型 Provider（默认 `openai_compatible`；也可用 `mock` 做离线演示）。 |
| `AIKA_LLM_BASE_URL` / `OPENAI_BASE_URL` | OpenAI 兼容接口根地址（可选）。 |
| `AIKA_LLM_API_KEY` / `OPENAI_API_KEY` | API Key（可选；Web 端也可在设置中写入 `app_settings.md` 的 `llm_text_api_key` / `llm_vl_api_key`）。 |
| `AIKA_LLM_MODEL` | 默认模型名（可选；Web 端优先使用设置）。 |
| `AIKA_ENABLE_NATIVE_FOLDER_PICKER` / `AIKA_FS_PICKER_LOCALHOST_ONLY` | 本机目录选择行为与安全限制。 |
| `DOCS2MD_ROOT` | （可选）本地克隆的 `docs2md` 仓库根目录，用于覆盖已安装的 docs2md。 |
| `DOCS2MD_PYTHON` | （可选）运行 docs2md 子进程所用解释器，默认与后端同解释器（`sys.executable`）。 |
| `AIKA_PROJECTS_ALLOW_PREFIX` | （可选）限制用户只能注册该前缀下的目录路径。 |

完整列表见根目录 [README.md](../README.md)。

## 4. 数据与持久化

- SQLite：位于 `$AIKA_REPO_ROOT/.tmp/aika/`（具体路径随版本以代码为准）。  
- 项目转换输出：`md_out` 等在 `.tmp` 下按项目隔离。  
- 不要将含密钥的 `app_settings.md` 提交到 Git；生产建议挂载只读或首次由模板复制。

## 5. `app_settings.md` 与规则文件

- **活动规则文件**：默认文件名为 `rules.md`（位于 `AIKA_REPO_ROOT`）；可通过 `AIKA_RULES_FILENAME` 切换为同目录下其他文件（如 `rules_new2.md`）。可挂载卷，例如 `./rules.md:/app/rules.md`。
- **文件内容要求（摘要）**：
  - **关注点块**：`### focus:<id> | <名称>`，id 在全文唯一；正文为审查 Prompt。
  - **组合使用建议**：二级标题须含「组合使用建议」，且紧跟 **固定五列表**：`评审节点` | `推荐组合的关注点` | `审查角色` | `审查目标与原则` | `输出要求`。数据行须五列齐备；推荐列使用 `` `focus:id` `` 与关注点 id 对齐。单元格内换行、竖线转义约定见根目录 `helpme.md`。
  - 仓库内 `default_rules.md` 可作为模板；首次部署可复制为活动规则文件或调用恢复模板接口（以当前产品行为为准）。
- **`app_settings.md`**：JSON 围栏内存放 `chunk_limit`、`chunk_strategy`、`llm_settings`、Key 等；缺失或解析失败时可回退 `default_app_settings.md`。
- 确保运行用户对上述文件有读权限，对需持久化的路径有写权限。

## 6. 升级与重建索引

- 升级镜像或拉取新代码后，若**分块逻辑或 `chunk_strategy` 默认值**变化，建议在业务低峰期对有关项目**重新执行索引**，再解读历史分析结果。  
- 用户仅在 Web 修改分块策略时，也应重新索引（产品内已有提示）。

## 7. 日志与排错

- 使用 FastAPI/uvicorn 日志配置查看请求与异常。  
- **禁止**在日志中打印 API Key 或原文全文。  
- 分析接口错误响应可能包含 provider、model、`repo_root` 等**非密钥**上下文，便于定位环境错误。

## 8. 安全建议

- Key 仅存于 `app_settings.md` 或环境变量，不入库、不写前端明文。  
- 限制 `AIKA_CORS_ORIGINS`，避免误配为 `*` 在生产环境使用。  
- 对 `.tmp` 与配置挂载卷做备份与访问控制。

---

用户操作说明见 [用户手册](User_Manual_zh.md)。
