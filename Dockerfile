# AI-KA Web：多阶段构建（前端静态资源 + FastAPI）
# 构建：docker build -t ai-ka:latest .
# 运行：见 docker-compose.yml

# ---------- 前端 ----------
# 前端已构建，直接复制 dist 目录
FROM python:3.12 AS frontend-build
WORKDIR /app
COPY web/frontend/dist ./web/frontend/dist

# ---------- 后端 ----------
FROM python:3.12

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AIKA_REPO_ROOT=/app \
    PYTHONPATH=/app/web:/app/src \
    AIKA_WEB_HOST=0.0.0.0 \
    AIKA_WEB_PORT=8765

# git：安装依赖时从 GitHub 拉取 docs2md / epic-doc
# ca-certificates：HTTPS
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 可选：文档转换完整能力（镜像会明显变大）。不需要可注释掉下面 RUN，仅影响 office/pdf 等转换提示。
# RUN apt-get update \
#     && apt-get install -y --no-install-recommends \
#         libreoffice pandoc graphviz \
#     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY web ./web

# 用构建阶段产物覆盖 web/frontend/dist（供 backend 挂载静态站）
COPY --from=frontend-build /app/web/frontend/dist ./web/frontend/dist

RUN pip install --upgrade pip setuptools wheel \
    && pip install .

EXPOSE 8765

# 与 aika-web 等价：监听 0.0.0.0 便于容器外访问
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8765"]
