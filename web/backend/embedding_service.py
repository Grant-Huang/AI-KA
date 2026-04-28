"""
Embedding service: lazy singleton that wraps llm.embed().
Also provides cosine_similarity and numpy-free vector serialisation.
"""
from __future__ import annotations

import hashlib
import struct
from typing import Any

from aika.llm import EmbedConfig, LLMError, embed as _llm_embed

_config: EmbedConfig | None = None


def configure(*, base_url: str, model: str, api_key: str | None = None) -> None:
    global _config
    _config = EmbedConfig(base_url=base_url, model=model, api_key=api_key)


def is_configured() -> bool:
    return _config is not None and bool(_config.base_url) and bool(_config.model)


def embed_text(text: str) -> list[float]:
    if not is_configured():
        raise LLMError("embedding_model not configured — set base_url and model in Settings")
    assert _config is not None
    return _llm_embed(text, _config)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def vec_to_bytes(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def bytes_to_vec(b: bytes) -> list[float]:
    n = len(b) // 4
    return list(struct.unpack(f"{n}f", b))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def hybrid_score(
    keyword_score: float,
    semantic_score: float,
    *,
    kw_weight: float = 0.35,
    sem_weight: float = 0.65,
) -> float:
    return kw_weight * keyword_score + sem_weight * semantic_score
