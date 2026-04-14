# Docker 部署 AI-KA

更完整的运维说明（环境变量清单、数据与权限、升级与排错）见 [《系统管理员手册》](System_Admin_Manual_zh.md)。

## 前置

- 已安装 [Docker](https://docs.docker.com/get-docker/) 与 Docker Compose v2。

## 快速启动

在项目根目录执行：

```bash
docker compose up -d --build
```

浏览器打开：**http://localhost:8765**（前端与 `/api` 同源，无需再开 Vite）。

健康检查：

```bash
curl -s http://localhost:8765/api/v1/health
```

## 配置说明

| 方式 | 说明 |
|------|------|
| **环境变量** | 见根目录 `README.md` 中 `AIKA_*`、`OPENAI_*` 等；可在 `docker-compose.yml` 的 `environment` 中追加。 |
| **`app_settings.md`** | 建议挂载只读或首次复制进数据卷，勿把含 Key 的文件提交到 Git。 |
| **`default_skills.md`** | 可挂载为 `./default_skills.md:/app/default_skills.md`，供首次初始化默认审查技能包时作为 `review_domain.md` 种子；或直接挂载整个 `./review_skill_packages` 目录。 |

## 数据持久化

`docker-compose.yml` 已将 **`/app/.tmp`** 映射到命名卷 `ai-ka-data`，用于 SQLite、项目 `md_out`、导出等。升级镜像时数据可保留。

## 镜像体积与文档转换

默认镜像**未**安装 LibreOffice / Pandoc / Graphviz，体积较小；若需要完整的 office 转 Markdown 等能力，可编辑根目录 `Dockerfile`，取消注释「可选」的 `apt-get install` 一段后重新构建。

## 构建命令（不用 Compose 时）

```bash
docker build -t ai-ka:latest .
docker run --rm -p 8765:8765 \
  -e AIKA_REPO_ROOT=/app \
  -e AIKA_CORS_ORIGINS=http://localhost:8765 \
  -v ai-ka-data:/app/.tmp \
  ai-ka:latest
```

## 故障排查

1. **页面空白**：确认 `web/frontend/dist` 已打进镜像（多阶段构建应自动生成）。
2. **API 403 CORS**：把实际访问来源加入 `AIKA_CORS_ORIGINS`（逗号分隔）。
3. **找不到项目/数据库**：确认 `AIKA_REPO_ROOT` 为 `/app`，且卷挂载未覆盖整个 `/app` 导致代码丢失。
