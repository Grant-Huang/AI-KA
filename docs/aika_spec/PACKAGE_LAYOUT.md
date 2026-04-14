# 审查技能包目录约定

仓库根（`AIKA_REPO_ROOT`）下：

```
review_skill_packages/
  <package_id>/
    manifest.json       # schema_version, id, name, version, description
    review_domain.md    # 与仓库根 default_skills.md 同格式（关注点块 + 组合使用建议表）
```

- 活动包 id 存于 `app_settings.md` 的 JSON 键 **`active_skill_package_id`**（默认 `package-general`）。
- 可选环境变量 **`AIKA_REVIEW_SKILL_PACKAGES_ROOT`**：自定义包根目录（绝对路径或相对路径解析为绝对路径）。
