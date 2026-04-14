from __future__ import annotations

import hashlib
from typing import Any


def sha256_short(text: str, n: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[: int(n)]


def build_run_metadata(
    *,
    skill_id: str | None,
    skill_version: str | None,
    rules_hash: str | None,
    memory_injected: list[dict[str, Any]],
    rules_filename: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "skill_id": (skill_id or "").strip(),
        "skill_version": (skill_version or "").strip(),
        "rules_hash": (rules_hash or "").strip(),
        "memory_files_injected": list(memory_injected),
    }
    if rules_filename:
        out["rules_filename"] = str(rules_filename)
    if extra:
        for k, v in extra.items():
            out[str(k)] = v
    return out
