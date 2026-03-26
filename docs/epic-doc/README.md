# 用 `epic-doc` 生成 docx（本项目约定）

本仓库将 **Markdown 作为源文档**，将 **docx 作为交付输出**。docx 的排版与渲染完全通过 [`epic-doc`](https://github.com/Grant-Huang/epic-doc) 完成，本项目不重复实现文档生成逻辑。

---

## 1. 安装

```bash
python -m pip install epic-doc
```

如需流程图/HTML/PDF：

- 流程图：安装 `graphviz`
- HTML/PDF：安装 `pandoc`

---

## 2. 生成命令（示例）

> 说明：以下 `*.json` 是 `epic-doc` 的配置文件（blocks 形式）。

```bash
epic-doc generate docs/epic-doc/projectlens-functional.json -o docs/epic-doc/out/ProjectLens_功能设计_V1.1.docx
epic-doc generate docs/epic-doc/projectlens-dd.json         -o docs/epic-doc/out/ProjectLens_详细设计_V1.1.docx
epic-doc generate docs/epic-doc/projectlens-plan.json       -o docs/epic-doc/out/ProjectLens_行动计划_V1.0.docx
```

---

## 3. 约束

- `docs/` 下的 Markdown 为**权威来源**；`docs/epic-doc/out/` 下的 docx 为**可再生成的产物**。
- 若 `epic-doc` 的 JSON Schema/字段存在差异，以 `epic-doc` 实际 CLI 校验为准；本项目不在此处“猜字段”实现生成逻辑。

