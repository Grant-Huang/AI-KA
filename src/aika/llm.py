from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_s: float = 60.0


@dataclass(frozen=True)
class LLMResult:
    text: str
    raw: dict[str, Any] | None = None


class LLMProvider:
    def chat(self, *, system: str, user: str, config: LLMConfig) -> LLMResult:  # pragma: no cover
        raise NotImplementedError

    def chat_stream(self, *, system: str, user: str, config: LLMConfig) -> Iterator[str]:  # pragma: no cover
        raise NotImplementedError


class MockProvider(LLMProvider):
    """
    离线可测 provider：不调用网络，返回可解析 JSON。
    规则：若 user 文本中出现 '风险' -> 生成 1 条 risk；出现 '需求' -> 生成 1 条 requirement。
    """

    def chat(self, *, system: str, user: str, config: LLMConfig) -> LLMResult:
        annotations: list[dict[str, Any]] = []
        if "需求" in user:
            annotations.append(
                {
                    "type": "requirement",
                    "content": "（mock）识别到需求相关内容",
                    "confidence": "high",
                }
            )
        if "风险" in user:
            annotations.append(
                {
                    "type": "risk",
                    "content": "（mock）识别到风险相关内容",
                    "confidence": "high",
                }
            )
        return LLMResult(text=json.dumps({"annotations": annotations}, ensure_ascii=False))

    def chat_stream(self, *, system: str, user: str, config: LLMConfig) -> Iterator[str]:
        text = self.chat(system=system, user=user, config=config).text
        yield text


class OpenAICompatibleProvider(LLMProvider):
    """
    兼容 OpenAI Chat Completions 形状的接口（用于企业自建/代理/第三方兼容服务）。
    仅使用标准库 urllib，避免强依赖。
    """

    @staticmethod
    def _chat_completions_url(base_url: str) -> str:
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    @staticmethod
    def _should_retry_without_response_format(http_status: int, err_text: str) -> bool:
        if http_status != 400:
            return False
        lo = (err_text or "").lower()
        return "response_format" in lo or "json_schema" in lo or "json_object" in lo

    def chat(self, *, system: str, user: str, config: LLMConfig) -> LLMResult:
        base = (config.base_url or "").rstrip("/")
        if not base:
            raise LLMError("base_url is required for openai_compatible provider")
        model = config.model or ""
        if not model:
            raise LLMError("model is required for openai_compatible provider")

        api_key = config.api_key
        if not api_key:
            api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("AIKA_LLM_API_KEY")
        if not api_key:
            raise LLMError("api_key missing (set in config or env OPENAI_API_KEY/AIKA_LLM_API_KEY)")

        url = self._chat_completions_url(base)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            # 协议层约束：优先要求模型返回合法 JSON 对象
            "response_format": {"type": "json_object"},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")

        try:
            with urllib.request.urlopen(req, timeout=float(config.timeout_s)) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            if self._should_retry_without_response_format(e.code, err):
                payload.pop("response_format", None)
                data = json.dumps(payload).encode("utf-8")
                req2 = urllib.request.Request(url, data=data, method="POST")
                req2.add_header("Content-Type", "application/json")
                req2.add_header("Authorization", f"Bearer {api_key}")
                try:
                    with urllib.request.urlopen(req2, timeout=float(config.timeout_s)) as resp:
                        body = resp.read().decode("utf-8", errors="replace")
                except urllib.error.HTTPError as e2:
                    err2 = e2.read().decode("utf-8", errors="replace")
                    raise LLMError(f"http error {e2.code}: {err2}") from e2
                except Exception as e2:
                    raise LLMError(str(e2)) from e2
            else:
                raise LLMError(f"http error {e.code}: {err}") from e
        except Exception as e:
            raise LLMError(str(e)) from e

        try:
            raw = json.loads(body)
            text = raw["choices"][0]["message"]["content"]
        except Exception as e:
            raise LLMError(f"invalid response: {body[:300]}") from e

        return LLMResult(text=str(text), raw=raw)

    def chat_stream(self, *, system: str, user: str, config: LLMConfig) -> Iterator[str]:
        base = (config.base_url or "").rstrip("/")
        if not base:
            raise LLMError("base_url is required for openai_compatible provider")
        model = config.model or ""
        if not model:
            raise LLMError("model is required for openai_compatible provider")

        api_key = config.api_key
        if not api_key:
            api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("AIKA_LLM_API_KEY")
        if not api_key:
            raise LLMError("api_key missing (set in config or env OPENAI_API_KEY/AIKA_LLM_API_KEY)")

        url = self._chat_completions_url(base)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "stream": True,
            # 协议层约束：优先要求模型返回合法 JSON 对象
            "response_format": {"type": "json_object"},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Accept", "text/event-stream")

        try:
            resp = urllib.request.urlopen(req, timeout=float(config.timeout_s))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            if self._should_retry_without_response_format(e.code, err):
                payload.pop("response_format", None)
                data = json.dumps(payload).encode("utf-8")
                req2 = urllib.request.Request(url, data=data, method="POST")
                req2.add_header("Content-Type", "application/json")
                req2.add_header("Authorization", f"Bearer {api_key}")
                req2.add_header("Accept", "text/event-stream")
                try:
                    resp = urllib.request.urlopen(req2, timeout=float(config.timeout_s))
                except urllib.error.HTTPError as e2:
                    err2 = e2.read().decode("utf-8", errors="replace")
                    raise LLMError(f"http error {e2.code}: {err2}") from e2
                except Exception as e2:
                    raise LLMError(str(e2)) from e2
            else:
                raise LLMError(f"http error {e.code}: {err}") from e
        except Exception as e:
            raise LLMError(str(e)) from e

        try:
            while True:
                line = resp.readline()
                if not line:
                    break
                s = line.decode("utf-8", errors="replace").strip()
                if not s or s.startswith(":"):
                    continue
                if s == "data: [DONE]":
                    break
                if not s.startswith("data: "):
                    continue
                chunk_json = s[6:].strip()
                try:
                    obj = json.loads(chunk_json)
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0].get("delta") or {})
                    piece = delta.get("content")
                    if piece:
                        yield str(piece)
                except json.JSONDecodeError:
                    continue
        finally:
            resp.close()


def get_provider(provider_id: str) -> LLMProvider:
    pid = provider_id.strip().lower()
    if pid == "mock":
        return MockProvider()
    if pid in {"openai", "openai_compatible"}:
        return OpenAICompatibleProvider()
    raise LLMError(f"unknown provider: {provider_id}")

