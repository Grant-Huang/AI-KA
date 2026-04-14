# SkillManifest（审查技能包清单）v1

`SkillManifest` 描述一组可复用的审查配置：关注点引用、预设三文案、版本与标识，用于回放与合规（与 `analysis_runs.run_metadata_json` 对齐）。

## 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `schema_version` | string | 是 | 固定 `1` |
| `id` | string | 是 | 稳定 id，如 `package-general` |
| `name` | string | 是 | 展示名 |
| `version` | string | 是 | 语义化版本，如 `1.0.0` |
| `focus_ids` | string[] | 是 | 引用的关注点 id 列表（顺序即审查顺序建议） |
| `review_role` | string \| null | 否 | 预设：审查角色 |
| `review_goals_principles` | string \| null | 否 | 预设：目标与原则 |
| `output_requirements` | string \| null | 否 | 预设：输出要求 |
| `description` | string \| null | 否 | 适用场景说明 |
| `tags` | string[] | 否 | 路由/推荐用标签 |

运行时写入元数据的字段见 `run_metadata_json`：`skill_id`、`skill_version`、`rules_hash`、`memory_files_injected` 等。

## 示例

见同目录 [`examples/skill_manifest.v1.json`](examples/skill_manifest.v1.json)。
