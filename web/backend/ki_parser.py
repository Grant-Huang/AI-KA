"""Parse <!-- ki: {...} --> markers from LLM streaming output."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

_KI_PATTERN = re.compile(r"<!--\s*ki:\s*(\{.*?\})\s*-->", re.DOTALL)


@dataclass
class KiMarker:
    card_type: str          # risk_signal | rule | process | best_practice | anti_pattern
    title: str
    content: str
    applicable_scope: str | None = None
    exceptions: str | None = None
    confidence: str = "medium"  # high | medium | low


def parse_ki_markers(text: str) -> list[KiMarker]:
    markers: list[KiMarker] = []
    for m in _KI_PATTERN.finditer(text):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if not d.get("title") or not d.get("content"):
            continue
        markers.append(
            KiMarker(
                card_type=str(d.get("type", "rule")),
                title=str(d["title"]),
                content=str(d["content"]),
                applicable_scope=d.get("applicable_scope") or d.get("scope"),
                exceptions=d.get("exceptions"),
                confidence=str(d.get("confidence", "medium")),
            )
        )
    return markers


def strip_ki_markers(text: str) -> str:
    """Remove ki marker comments from text shown to the user."""
    return _KI_PATTERN.sub("", text).strip()
