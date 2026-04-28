from __future__ import annotations

from typing import Any

from .conversation_models import Finding, FindingStatus, MessageMetadata, collect_findings_from_conversation

RECENT_TURNS_VERBATIM = 3          # 最近 N 轮保留原文
MAX_OLDER_TURN_CHARS = 500         # 更早轮次每条截断字符数
MAX_HISTORY_CHARS = 4000           # 历史摘要总上限


def build_rolling_context(
    messages: list[Any],  # list[MessageRow]
    recent_n: int = RECENT_TURNS_VERBATIM,
) -> list[tuple[str, str]]:
    """
    构建滚动上下文：最近 recent_n 轮保留原文，更早的轮次截断为摘要。
    返回 (role, content) 元组列表，供 LLM prior_messages 参数使用。
    """
    turns = [m for m in messages if getattr(m, "role", None) in ("user", "assistant")]
    if not turns:
        return []

    recent = turns[-recent_n:] if len(turns) > recent_n else turns
    older = turns[:-recent_n] if len(turns) > recent_n else []

    result: list[tuple[str, str]] = []

    if older:
        # 把更早的轮次压缩为摘要注释注入（无需 LLM 调用，简单截断）
        summary_parts: list[str] = []
        total = 0
        for m in older:
            content = str(getattr(m, "content", "") or "")
            role = str(getattr(m, "role", "") or "")
            excerpt = content[:MAX_OLDER_TURN_CHARS]
            if len(content) > MAX_OLDER_TURN_CHARS:
                excerpt += "…（已截断）"
            line = f"[{role}] {excerpt}"
            if total + len(line) > MAX_HISTORY_CHARS:
                break
            summary_parts.append(line)
            total += len(line)
        if summary_parts:
            summary_text = "【早期对话摘要】\n" + "\n\n".join(summary_parts)
            result.append(("system", summary_text))

    for m in recent:
        role = str(getattr(m, "role", "") or "")
        content = str(getattr(m, "content", "") or "")
        result.append((role, content))

    return result


def format_open_findings_for_prompt(findings: list[Finding]) -> str:
    """
    将当前会话的 open/acknowledged 发现格式化为系统提示注入段落。
    目的：让 LLM 避免重复发现，并主动寻找关联关系。
    """
    if not findings:
        return ""
    lines: list[str] = ["【本次审查已发现的问题（请避免重复，注意关联）】"]
    for f in findings:
        sev_label = {"high": "HIGH", "medium": "MED", "low": "LOW"}.get(f.severity, f.severity.upper())
        status_label = "" if f.status == FindingStatus.OPEN else f" [{f.status}]"
        lines.append(f"- [{sev_label}] {f.id}: {f.title}{status_label}（关注点: {f.focus_id}）")
    return "\n".join(lines)


def collect_open_findings(messages: list[Any]) -> list[Finding]:
    """从会话历史中收集所有 open 或 acknowledged 状态的发现。"""
    return collect_findings_from_conversation(
        messages,
        status_filter={FindingStatus.OPEN, FindingStatus.ACKNOWLEDGED},
    )


def collect_all_findings(messages: list[Any]) -> list[Finding]:
    """从会话历史中收集所有发现（含 resolved），用于文档生成时聚合。"""
    return collect_findings_from_conversation(messages, status_filter=None)
