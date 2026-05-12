# 快速安装指南

## 问题：pip 安装失败？

如果您遇到以下错误：

```
error: metadata-generation-failed
× Encountered error while generating package metadata.
configuration error: `project.license` must be valid exactly by one definition
```

**原因**：上游依赖 `docs2md` 配置格式问题。

**解决方案**：使用 uv 包管理器（推荐）👇

---

## 🚀 推荐安装方式（使用 uv）

### 1️⃣ 安装 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2️⃣ 激活 uv 环境

```bash
source $HOME/.local/bin/env
```

或者重新打开终端。

### 3️⃣ 创建虚拟环境

```bash
cd /path/to/AI-KA
uv venv
```

### 4️⃣ 激活虚拟环境

**Linux/macOS**:
```bash
source .venv/bin/activate
```

**Windows**:
```bash
.venv\Scripts\activate
```

### 5️⃣ 安装项目依赖

```bash
uv pip install -e .
```

### 6️⃣ 验证安装

```bash
# 验证 CLI 工具
aika --help

# 验证 Python 模块
python -c "import docs2md; import epic_doc; print('✅ 安装成功！')"
```

---

## 🎯 为什么使用 uv？

| 特性 | pip | uv |
|------|-----|-----|
| 速度 | 慢 | **极快 (10-100x)** |
| 兼容性 | 对配置格式严格 | **更宽容** |
| 本项目 | ❌ 安装失败 | ✅ **安装成功** |

---

## 📚 详细文档

- **问题分析**：[docs/ISSUE_docs2md_license_format.md](docs/ISSUE_docs2md_license_format.md)
- **完整方案**：[docs/SOLUTION_uv_package_manager.md](docs/SOLUTION_uv_package_manager.md)
- **项目 README**：[README.md](README.md)

---

## ⚠️ 传统 pip 方式（不推荐）

如果您坚持使用 pip，可以尝试：

```bash
python -m pip install -e . --no-build-isolation
```

**注意**：此方式可能会失败，建议使用 uv。

---

## 🆘 遇到问题？

1. 确保已安装 Python 3.12+：`python3 --version`
2. 确保已安装 Git：`git --version`
3. 查看详细文档了解更多解决方案
4. 提交 Issue 到项目仓库

---

**最后更新**：2026-05-12  
**相关 PR**：[#7](https://github.com/Grant-Huang/AI-KA/pull/7)
