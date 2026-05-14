from __future__ import annotations

from typing import Any, Callable, Iterator


def _normalize_chunk(chunk: Any) -> str:
    """统一将 provider.chat_stream 的 chunk 转为字符串。"""
    if isinstance(chunk, dict):
        return chunk.get("content") or chunk.get("text") or ""
    return str(chunk) if chunk is not None else ""


def stream_and_collect(
    provider: Any,
    *,
    system: str,
    user: str,
    config: Any,
    prior_messages: list[tuple[str, str]] | None = None,
    on_chunk: Callable[[str], None] | None = None,
) -> str:
    """
    调用 provider.chat_stream，收集所有 chunk 并返回完整文本。

    on_chunk: 每个非空 chunk 调用一次（用于 SSE yield 等副作用）。
    """
    acc: list[str] = []
    for raw in provider.chat_stream(
        system=system,
        user=user,
        config=config,
        prior_messages=prior_messages or None,
    ):
        text = _normalize_chunk(raw)
        acc.append(text)
        if on_chunk and text:
            on_chunk(text)
    return "".join(acc)


def stream_and_collect_iter(
    provider: Any,
    *,
    system: str,
    user: str,
    config: Any,
    prior_messages: list[tuple[str, str]] | None = None,
) -> Iterator[str]:
    """
    Generator 版本：逐 chunk yield 文本，调用方可以 yield 到 SSE 流中。
    最后 yield 一个空字符串作为哨兵（调用方忽略即可）。
    完整文本需要调用方自行 join。
    """
    for raw in provider.chat_stream(
        system=system,
        user=user,
        config=config,
        prior_messages=prior_messages or None,
    ):
        yield _normalize_chunk(raw)
