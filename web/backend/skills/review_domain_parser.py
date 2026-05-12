"""
Parse review_domain.md into structured DB tables.

Extracts:
- L0: review phases (inferred from focus point ID prefix: 一审- / 二审-)
- L1: focus points (### focus:id | name)
- L2: review categories (**【xxx】** bold headings inside each focus point)
- Presets: ## 组合使用建议 table rows

Usage:
    from backend.skills.review_domain_parser import import_review_domain_to_db
    import_review_domain_to_db(conn, package_dir, package_id="package-solution-review-fs-v2")
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from aika import db as dbm

# ── Regex patterns ──────────────────────────────────────────────────────────

_FOCUS_HEADING_RE = re.compile(r'^###\s+focus:([^\|]+)\|\s*(.+?)\s*$', re.MULTILINE)
_CATEGORY_RE = re.compile(r'^\d+\.\s+\*\*【([^】]+)】', re.MULTILINE)
_PRESET_TABLE_SECTION_RE = re.compile(r'^##\s+.*(?:组合|建议|预设).*$', re.MULTILINE)
_TABLE_ROW_RE = re.compile(r'^\|(.+)\|$')

_PHASE_MAP = {
    "一审": ("phase-1review", "方案一审", "调研完成后蓝图设计前", 1),
    "二审": ("phase-2review", "方案二审", "蓝图方案完成后", 2),
    "transition": ("phase-transition", "一审到二审衔接检查", "二审评审前", 3),
}


def _detect_phase(focus_id: str) -> str:
    if focus_id.startswith("一审"):
        return "phase-1review"
    if focus_id.startswith("二审"):
        return "phase-2review"
    return "phase-other"


def _parse_focus_blocks(text: str) -> list[dict]:
    """Extract focus point blocks with their text content."""
    matches = list(_FOCUS_HEADING_RE.finditer(text))
    blocks = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end]
        # Stop at ## heading (next major section)
        section_end = re.search(r'^##\s+', content, re.MULTILINE)
        if section_end:
            content = content[:section_end.start()]
        blocks.append({
            "id": m.group(1).strip(),
            "name": m.group(2).strip(),
            "content": content,
        })
    return blocks


def _parse_categories(focus_id: str, content: str) -> list[dict]:
    """Extract L2 categories from a focus point block."""
    cats = []
    for i, m in enumerate(_CATEGORY_RE.finditer(content)):
        name = m.group(1).strip()
        # Detect conditional categories
        is_conditional = "条件性" in content[max(0, m.start()-5):m.end()+20] or "条件性" in name
        condition_note = ""
        if is_conditional:
            # Extract condition hint from parentheses nearby
            note_m = re.search(r'（([^）]{5,60})）', content[m.start():m.start()+100])
            condition_note = note_m.group(1) if note_m else ""
        cats.append({
            "id": f"{focus_id}::{name}",
            "focus_id": focus_id,
            "name": name,
            "order_index": i,
            "is_conditional": is_conditional,
            "condition_note": condition_note,
        })
    return cats


def _parse_preset_table(text: str) -> list[dict]:
    """Extract preset combinations from the 组合使用建议 table."""
    m = _PRESET_TABLE_SECTION_RE.search(text)
    if not m:
        return []
    table_text = text[m.end():]
    # Stop at next ## section
    next_section = re.search(r'^##\s+', table_text, re.MULTILINE)
    if next_section:
        table_text = table_text[:next_section.start()]

    presets = []
    rows = [line for line in table_text.splitlines() if _TABLE_ROW_RE.match(line.strip())]
    # Skip header and separator rows
    data_rows = [r for r in rows if not re.match(r'^\|\s*[-:]+\s*\|', r.strip()) and '评审节点' not in r]

    for i, row in enumerate(data_rows):
        cells = [c.strip() for c in row.strip().strip('|').split('|')]
        if len(cells) < 2:
            continue
        preset_name = re.sub(r'\*+', '', cells[0]).strip()  # remove bold markers
        focus_refs_raw = cells[1] if len(cells) > 1 else ""
        review_role = cells[2] if len(cells) > 2 else ""
        review_goals = cells[3] if len(cells) > 3 else ""
        output_req = cells[4] if len(cells) > 4 else ""

        # Extract focus IDs from `focus:xxx` patterns
        focus_ids = re.findall(r'focus:([^\s`+）\)]+)', focus_refs_raw)

        # Detect phase from preset name or focus IDs
        phase_id = ""
        if "一审" in preset_name and "二审" not in preset_name:
            phase_id = "phase-1review"
        elif "二审" in preset_name and "一审" not in preset_name:
            phase_id = "phase-2review"
        elif "衔接" in preset_name or ("一审" in preset_name and "二审" in preset_name):
            phase_id = "phase-transition"

        # pass_threshold: 二审 has ≥80% rule
        pass_threshold = None
        if "80%" in review_goals or "0.8" in review_goals:
            pass_threshold = 0.80

        # is_prerequisite: 通用要求 must run first
        prerequisite_ids = set()
        if "通用要求" in review_goals and "优先" in review_goals:
            for fid in focus_ids:
                if "通用要求" in fid:
                    prerequisite_ids.add(fid)

        preset_id = f"preset-{i+1}-{re.sub(r'[^a-z0-9]', '-', preset_name.lower()[:20])}"
        presets.append({
            "id": preset_id,
            "name": preset_name,
            "phase_id": phase_id,
            "review_role": review_role,
            "review_goals": review_goals,
            "output_requirements": output_req,
            "pass_threshold": pass_threshold,
            "order_index": i,
            "focus_ids": focus_ids,
            "prerequisite_ids": prerequisite_ids,
        })
    return presets


def import_review_domain_to_db(
    conn: sqlite3.Connection,
    package_dir: Path,
    package_id: str = "",
) -> dict:
    """
    Parse review_domain.md in package_dir and import L0/L1/L2 + presets into DB.
    Returns a summary dict with counts.
    """
    review_domain = package_dir / "review_domain.md"
    if not review_domain.is_file():
        return {"error": f"{review_domain} not found"}

    text = review_domain.read_text(encoding="utf-8")

    # ── L0: Phases ─────────────────────────────────────────────────────────
    for key, (pid, pname, pdesc, porder) in _PHASE_MAP.items():
        dbm.upsert_review_phase(conn, id=pid, name=pname, description=pdesc, order_index=porder)

    # ── L1: Focus Points ────────────────────────────────────────────────────
    blocks = _parse_focus_blocks(text)
    fp_count = 0
    cat_count = 0
    for i, block in enumerate(blocks):
        phase_id = _detect_phase(block["id"])
        # Ensure phase exists even if not in _PHASE_MAP
        if not conn.execute("SELECT 1 FROM review_phases WHERE id=?", (phase_id,)).fetchone():
            dbm.upsert_review_phase(conn, id=phase_id, name=phase_id, order_index=99)

        dbm.upsert_review_focus_point_ext(
            conn,
            id=block["id"],
            phase_id=phase_id,
            name=block["name"],
            description=block["content"].strip()[:200],
            order_index=i,
            package_id=package_id,
        )
        fp_count += 1

        # ── L2: Categories ──────────────────────────────────────────────────
        cats = _parse_categories(block["id"], block["content"])
        for cat in cats:
            dbm.upsert_review_category(
                conn,
                id=cat["id"],
                focus_id=cat["focus_id"],
                name=cat["name"],
                order_index=cat["order_index"],
                is_conditional=cat["is_conditional"],
                condition_note=cat["condition_note"],
            )
            cat_count += 1

    # ── Presets ─────────────────────────────────────────────────────────────
    presets = _parse_preset_table(text)
    preset_count = 0
    member_count = 0
    for preset in presets:
        dbm.upsert_review_preset_ext(
            conn,
            id=preset["id"],
            name=preset["name"],
            phase_id=preset["phase_id"],
            review_role=preset["review_role"],
            review_goals=preset["review_goals"],
            output_requirements=preset["output_requirements"],
            pass_threshold=preset["pass_threshold"],
            package_id=package_id,
            order_index=preset["order_index"],
        )
        preset_count += 1
        for j, fid in enumerate(preset["focus_ids"]):
            dbm.upsert_preset_focus_member(
                conn,
                preset_id=preset["id"],
                focus_id=fid,
                order_index=j,
                is_prerequisite=(fid in preset["prerequisite_ids"]),
            )
            member_count += 1

    return {
        "phases": len(_PHASE_MAP),
        "focus_points": fp_count,
        "categories": cat_count,
        "presets": preset_count,
        "preset_members": member_count,
    }
