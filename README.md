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
| `DOCS2MD_PYTHON` | 可选，默认 `python` |
| `AIKA_PROJECTS_ALLOW_PREFIX` | 可选，限制用户只能注册该前缀下的目录 |
| `AIKA_ENABLE_NATIVE_FOLDER_PICKER` | 可选，默认开启：由本机后端弹出系统文件夹对话框并返回绝对路径（`/api/v1/fs/pick-directory`） |
| `AIKA_FS_PICKER_LOCALHOST_ONLY` | 可选，默认开启：仅当从本机访问 API 时允许目录选择（防止远端触发服务器弹窗） |
| `AIKA_LLM_PROVIDER` | `openai_compatible` 或 `mock`（离线演示） |
| `AIKA_LLM_BASE_URL` | OpenAI 兼容 API 根 URL |
| `AIKA_LLM_API_KEY` | API Key（或使用 `OPENAI_API_KEY`） |
| `AIKA_LLM_MODEL` | 模型名 |
| `AIKA_WEB_HOST` / `AIKA_WEB_PORT` | 后端监听，默认 `127.0.0.1:8765` |
| `AIKA_REPO_ROOT` | 可选，显式指定本仓库根（用于 `.tmp` 与 SQLite 路径） |

### 3.3 启动后端

```bash
aika-web
# 或
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
```

浏览器打开 Vite 提示的地址（默认 `http://localhost:5173`），通过代理访问 `/api`。

### 3.4 使用流程

1. 在页面创建项目：点击「选择目录」由本机后端弹出系统文件夹对话框并回填**绝对路径**（或手动填写；后端进程必须可读）。
2. **开始转换**：调用 docs2md 子进程，SSE 显示日志；输出在 `.tmp/aika/projects/{id}/md_out/`。
3. **索引 Markdown**：将 md 扫描入库并分块。
4. 编辑并**保存规则**（JSON），**开始分析**：SSE 流式输出；前端解析最终 JSON 为卡片/表格/Tabs。
5. **导出 docx**：`epic-doc` / `docs2md` 已作为 Python 依赖安装；若缺少 LibreOffice/pandoc/graphviz 等系统依赖，启动时会提示安装方式。

## 4. 目录约定

- 代码：`src/`（CLI 库 `aika`）、`web/backend`（包名 `backend`）
- 前端：`web/frontend/`
- 测试：`tests/`
- 临时数据：`.tmp/`（已加入 `.gitignore`）

## 5. 离线 pip 说明

若构建隔离环境无法联网，请使用：

`python -m pip install -e . --no-build-isolation`

