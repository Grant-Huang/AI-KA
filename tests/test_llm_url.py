from __future__ import annotations

from aika.llm import OpenAICompatibleProvider


def test_openai_compatible_url_with_v1_suffix() -> None:
    p = OpenAICompatibleProvider()
    url = p._chat_completions_url("https://api.example.com/v1")
    assert url == "https://api.example.com/v1/chat/completions"


def test_openai_compatible_url_without_v1_suffix() -> None:
    p = OpenAICompatibleProvider()
    url = p._chat_completions_url("https://api.example.com")
    assert url == "https://api.example.com/v1/chat/completions"

