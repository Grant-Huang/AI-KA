# 使用 uv 包管理器解决 docs2md 依赖安装问题

## 问题回顾

使用传统的 `pip install -e .` 命令安装项目依赖时，由于 `docs2md` 仓库的 `pyproject.toml` 中 `license` 字段格式不符合 PEP 621 标准（使用了字符串 `"MIT"` 而非对象 `{text = "MIT"}`），导致在 setuptools>=70 环境下安装失败。

## 解决方案：使用 uv 包管理器

`uv` 是由 Astral 开发的现代 Python 包管理器，速度快且对配置格式更宽容。

### 优势

1. **速度快**：安装速度比 pip 快 10-100 倍
2. **兼容性好**：能够处理一些 pip 无法处理的配置格式问题
3. **锁定文件**：项目已有 `uv.lock` 文件，确保依赖版本一致性
4. **无需修改上游**：不需要等待 docs2md 仓库修复

### 安装步骤

#### 1. 安装 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

安装完成后，将 uv 添加到 PATH：

```bash
source $HOME/.local/bin/env  # sh/bash/zsh
```

#### 2. 创建虚拟环境

```bash
cd /workspace
uv venv
```

#### 3. 激活虚拟环境并安装依赖

```bash
source .venv/bin/activate
uv pip install -e .
```

### 验证安装

```bash
# 验证 CLI 工具
aika --help
aika-web --help

# 验证 Python 模块导入
python3 -c "import docs2md; import epic_doc; print('✅ 所有依赖导入成功')"
```

### 已安装的关键依赖

- ✅ `ai-ka==0.1.0` (当前项目)
- ✅ `docs2md==0.2.0` (从 Git: Grant-Huang/docs2md@27bbbb4d)
- ✅ `epic-doc==0.1.0` (从 Git: Grant-Huang/epic-doc@ee8de100)
- ✅ `fastapi==0.136.1`
- ✅ `uvicorn==0.46.0`
- ✅ 及其他 62 个依赖包

## 与传统 pip 的对比

| 特性 | pip | uv |
|------|-----|-----|
| 安装速度 | 慢 | 极快 (10-100x) |
| 配置兼容性 | 严格 (setuptools>=70) | 宽容 |
| 锁定文件 | requirements.txt | uv.lock (更精确) |
| Git 依赖 | 支持但慢 | 支持且快 |
| 本次问题 | ❌ 失败 | ✅ 成功 |

## 项目建议

### 更新 README.md

建议在 README.md 中添加 uv 安装方式作为推荐方法：

```markdown
## 安装方式

### 推荐：使用 uv（速度快）

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建虚拟环境并安装依赖
uv venv
source .venv/bin/activate  # Linux/macOS
uv pip install -e .
```

### 传统方式：使用 pip

```bash
python -m pip install -e . --no-build-isolation
```

**注意**：由于上游依赖配置问题，使用 pip 可能会遇到安装失败。推荐使用 uv。
```

### 更新 CI/CD 配置

如果项目有 CI/CD 流程（如 `.github/workflows/ci.yml`），建议更新为使用 uv：

```yaml
- name: Install uv
  run: curl -LsSf https://astral.sh/uv/install.sh | sh

- name: Install dependencies
  run: |
    source $HOME/.local/bin/env
    uv venv
    source .venv/bin/activate
    uv pip install -e ".[dev]"
```

### Docker 镜像更新

如果需要更新 `Dockerfile`，可以添加 uv 支持：

```dockerfile
# 安装 uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# 使用 uv 安装依赖
RUN uv venv && \
    . .venv/bin/activate && \
    uv pip install -e .
```

## 长期解决方案

虽然 uv 解决了当前问题，但仍建议向 `docs2md` 仓库提交 PR 修复 `license` 字段格式：

```toml
# 修改前
license = "MIT"

# 修改后
license = {text = "MIT"}
```

这样可以确保使用传统 pip 的用户也能顺利安装。

## 参考资料

- [uv 官方文档](https://github.com/astral-sh/uv)
- [uv 安装指南](https://docs.astral.sh/uv/installation/)
- [PEP 621 - License 字段规范](https://peps.python.org/pep-0621/#license)
