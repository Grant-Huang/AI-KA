# 四类记忆（Memory taxonomy）

与实现目录约定一致，便于项目画像与个人偏好兼顾。

## 类型


| 类型            | 目录名          | 作用域                    | 内容示例                    |
| ------------- | ------------ | ---------------------- | ----------------------- |
| **user**      | `user/`      | Global（每用户，开发期可用单用户占位） | 语言偏好、默认预设、术语表、交互习惯      |
| **feedback**  | `feedback/`  | Global                 | 误判纠正、「以后不要…」；须可撤销       |
| **project**   | `project/`   | Per-project            | 行业、关键系统名、里程碑、团队角色       |
| **reference** | `reference/` | Per-project            | 规范链接、模板摘要；**禁止**存全文敏感信息 |


## 目录布局（约定）

仓库根或 `AIKA_REPO_ROOT` 下：

```
.aika/memory/
  MEMORY.md              # 短索引（行/字节上限见 PRIVACY_AND_LIMITS.md）
  user/*.md
  feedback/*.md
  project/<project_id>/*.md
  reference/<project_id>/*.md
```

开发阶段若无多用户，可将 `user/` 视为当前操作者。

## 索引文件 MEMORY.md

- 每行一条：`type | rel_path | 一行摘要`，便于快速扫描。
- 正文记忆文件可使用 YAML frontmatter：`memory_type`, `title`, `updated_at`。

## 注入策略

1. 先读 `MEMORY.md`（截断到上限）。
2. 相关性检索（关键词匹配 → 可升级为 side 模型）选出不超过 `N` 个文件正文。
3. 维护会话级 `already_surfaced` id 列表，避免重复注入。

详见 `[PRIVACY_AND_LIMITS.md](PRIVACY_AND_LIMITS.md)`。