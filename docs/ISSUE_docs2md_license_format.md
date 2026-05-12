# docs2md 依赖安装失败问题分析

## 问题描述

在执行 `python3 -m pip install -e . --no-build-isolation` 时，安装失败并报错：

```
error: metadata-generation-failed
× Encountered error while generating package metadata.
```

具体错误信息显示 `docs2md` 包的 `pyproject.toml` 配置不符合 PEP 621 标准。

## 根本原因

**位置**：`https://github.com/Grant-Huang/docs2md.git` 的 `pyproject.toml` 第 11 行

**问题代码**：
```toml
license = "MIT"
```

**错误说明**：
根据 [PEP 621](https://peps.python.org/pep-0621/#license) 标准，`project.license` 字段必须是对象格式，而不能是简单的字符串。setuptools>=70 严格执行这一规则。

**正确格式**：
```toml
license = {text = "MIT"}
```

或者：
```toml
license = {file = "LICENSE"}
```

## 解决方案

### 方案 1：修复 docs2md 仓库（推荐）

需要在 `docs2md` 仓库提交 PR，修改 `pyproject.toml` 第 11 行：

```diff
- license = "MIT"
+ license = {text = "MIT"}
```

**优点**：
- 从根本上解决问题
- 对所有使用者都有益

**缺点**：
- 需要等待上游仓库合并 PR

### 方案 2：Fork 并修复（快速解决）

1. Fork `https://github.com/Grant-Huang/docs2md.git` 到自己的账号
2. 在 fork 的仓库中修复 `pyproject.toml`
3. 修改当前项目的 `pyproject.toml` 依赖指向：

```diff
dependencies = [
  ...
-  "docs2md @ git+https://github.com/Grant-Huang/docs2md.git",
+  "docs2md @ git+https://github.com/<YOUR_USERNAME>/docs2md.git@<branch_name>",
  ...
]
```

**优点**：
- 可以立即解决问题
- 完全控制依赖版本

**缺点**：
- 需要维护 fork 仓库
- 需要定期同步上游更新

### 方案 3：降低 setuptools 版本（临时方案，不推荐）

修改当前项目的 `pyproject.toml`：

```diff
[build-system]
- requires = ["setuptools>=70,<78", "wheel"]
+ requires = ["setuptools>=69,<70", "wheel"]
build-backend = "setuptools.build_meta"
```

**优点**：
- 最简单的修改
- 可以立即解决问题

**缺点**：
- 不符合项目对新版本 setuptools 的需求
- 可能引入兼容性问题
- 治标不治本

### 方案 4：使用 uv 包管理器（探索性方案）

项目根目录已经有 `uv.lock` 文件，说明可能支持使用 `uv` 作为包管理器：

```bash
# 安装 uv（如果尚未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 使用 uv 安装依赖
uv pip install -e .
```

**优点**：
- uv 可能对配置格式更宽容
- 安装速度更快

**缺点**：
- 需要验证是否真的能解决问题
- 可能需要调整现有工作流

## 推荐行动方案

**短期**：采用方案 2（Fork 并修复）
1. Fork docs2md 仓库
2. 修复 license 字段格式
3. 更新当前项目依赖指向

**长期**：同时执行方案 1
1. 向上游 docs2md 仓库提交 PR
2. PR 合并后，恢复依赖指向原始仓库

## 需要修改的文件

### docs2md 仓库的 pyproject.toml

```toml
[project]
name = "docs2md"
version = "0.2.0"
description = "将文档/图片转换为 Markdown 或纯文本的工具包（含 CLI）"
readme = "README.md"
requires-python = ">=3.11"
license = {text = "MIT"}  # ← 修改这一行
license-files = ["LICENSE"]
authors = [{ name = "docs2md contributors" }]
# ... 其余配置保持不变
```

### epic-doc 仓库检查

✅ **已检查**：`epic-doc` 仓库的 `pyproject.toml` 格式正确，使用了 `license = { text = "MIT" }`，不存在此问题。

## 参考资料

- [PEP 621 - License 字段规范](https://peps.python.org/pep-0621/#license)
- [setuptools 配置文档](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html)
