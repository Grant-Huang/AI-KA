"""
review_domain.md 解析、校验与写回（原 main 内 rules 相关逻辑）。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any


def normalize_md_line_for_heading(line: str) -> str:
    """全角 # 等与 Markdown 标题比对时做 NFKC，避免行首 `＃＃` 无法识别为 ##。"""
    return unicodedata.normalize("NFKC", (line or "").strip())


_DOMAIN_H2_FOCUS_BLOCK_MARKER = "关注点块"
_DOMAIN_H2_COMBO_MARKER = "组合使用建议"

_DOMAIN_FOCUS_HEADING_LINE_RE = re.compile(
    r"^###\s+focus:\s*([^\s|]+)\s*\|\s*(.+)$"
)


def is_allowed_domain_h2_line(line: str) -> bool:
    s = normalize_md_line_for_heading(line)
    m = re.match(r"^##(?!#)\s+(.+)$", s)
    if not m:
        return False
    title = m.group(1).strip()
    if _DOMAIN_H2_FOCUS_BLOCK_MARKER in title:
        return True
    if _DOMAIN_H2_COMBO_MARKER in title:
        return True
    return False


def is_focus_block_h2_line(line: str) -> bool:
    s = normalize_md_line_for_heading(line)
    m = re.match(r"^##(?!#)\s+(.+)$", s)
    if not m:
        return False
    return _DOMAIN_H2_FOCUS_BLOCK_MARKER in m.group(1).strip()


def review_domain_strict_schema_error(text: str) -> str | None:
    """
    强校验：二级标题（##）仅允许含「关注点块」的节或含「组合使用建议」的组合节；
    三级标题（###）仅允许「### focus:<id> | <名称>」；
    首个「### focus:」之前须已出现含「关注点块」的二级标题。
    """
    seen_focus_block_h2 = False
    for line in text.splitlines():
        s = normalize_md_line_for_heading(line)
        if re.match(r"^##(?!#)", s):
            if not is_allowed_domain_h2_line(line):
                return (
                    "审查域文件格式无效：二级标题（##）仅允许「关注点块」节（如 ## 关注点块）"
                    "或含「组合使用建议」的组合节标题（如 ## 组合使用建议）。"
                )
            if is_focus_block_h2_line(line):
                seen_focus_block_h2 = True
            continue
        if re.match(r"^###\s+", s) and not re.match(r"^####", s):
            if not _DOMAIN_FOCUS_HEADING_LINE_RE.match(s):
                return (
                    "审查域文件格式无效：三级标题（###）仅允许「### focus:<id> | <名称>」格式，"
                    "例如 ### focus:handover | 运维交接与知识转移。"
                )
            if not seen_focus_block_h2:
                return (
                    "审查域文件格式无效：在首个「### focus:…」之前必须有含「关注点块」的二级标题（如 ## 关注点块）。"
                )
    return None


def is_combo_suggestions_heading(line: str) -> bool:
    s = unicodedata.normalize("NFKC", (line or "").strip())
    m = re.match(r"^##\s+(.+)$", s)
    if not m:
        return False
    title = m.group(1).strip()
    return _DOMAIN_H2_COMBO_MARKER in title


def is_combo_like_h3_heading(line: str) -> bool:
    s = unicodedata.normalize("NFKC", (line or "").strip())
    m = re.match(r"^###\s+(.+)$", s)
    if not m:
        return False
    title = m.group(1).strip()
    if "组合" not in title:
        return False
    return any(x in title for x in ("建议", "预设", "搭配", "使用"))


def normalize_table_line(raw: str) -> str:
    return raw.strip().replace("｜", "|")


def is_md_table_separator_row(cells: list[str]) -> bool:
    if len(cells) < 2:
        return False

    def cell_is_sep(c: str) -> bool:
        t = c.strip().replace(" ", "")
        return bool(t) and all(ch in "-:" for ch in t)

    return all(cell_is_sep(c) for c in cells)


def extract_focus_combo_tips_from_domain_text(text: str) -> list[dict[str, str]]:
    """解析固定五列表：评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求"""
    lines = text.splitlines()
    start = -1
    for i, raw in enumerate(lines):
        if is_combo_suggestions_heading(raw) or is_combo_like_h3_heading(raw):
            start = i
    if start < 0:
        return []

    rows: list[dict[str, str]] = []
    in_table = False
    for raw in lines[start + 1 :]:
        line = normalize_table_line(raw)
        if not line:
            continue
        if line.startswith("## ") and in_table:
            break
        if not line.startswith("|"):
            if in_table:
                break
            continue
        cells = [x.strip() for x in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if is_md_table_separator_row(cells):
            in_table = True
            continue
        c0, c1 = cells[0], cells[1] if len(cells) > 1 else ""
        if not in_table and ("评审" in c0 or "阶段" in c0 or "节点" in c0) and ("推荐" in c1 or "关注点" in c1):
            in_table = True
            continue
        if c0 in {"评审节点", "---"} and not in_table:
            in_table = True
            continue
        if c0.startswith("---") and len(c0) <= 5:
            in_table = True
            continue
        in_table = True
        if len(cells) < 5:
            continue
        stage = c0
        recommended = c1
        review_role = combo_cell_decode(cells[2])
        review_goals_principles = combo_cell_decode(cells[3])
        output_requirements = combo_cell_decode(cells[4])
        if stage and recommended:
            rows.append(
                {
                    "stage": stage,
                    "recommended": recommended,
                    "review_role": review_role,
                    "review_goals_principles": review_goals_principles,
                    "output_requirements": output_requirements,
                }
            )
    return rows


def slugify_id(text: str) -> str:
    s = re.sub(r"\s+", "_", (text or "").strip())
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return s.lower() or "preset"


def combo_cell_encode(text: str) -> str:
    s = str(text or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("|", "&#124;")
    return s.replace("\n", "<br>")


def combo_cell_decode(text: str) -> str:
    s = str(text or "").strip()
    s = s.replace("<br>", "\n").replace("<BR>", "\n")
    s = s.replace("&#124;", "|")
    return s


def parse_focus_ids_from_recommended(text: str) -> list[str]:
    t = str(text or "")
    out: list[str] = []
    seen: set[str] = set()
    pat = re.compile(r"`\s*focus:([^`]+?)\s*`|focus:([^\s+|`]+)")
    for m in pat.finditer(t):
        raw = m.group(1) if m.group(1) is not None else m.group(2)
        x = str(raw or "").strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def norm_focus_id(s: str) -> str:
    return unicodedata.normalize("NFKC", (s or "").strip())


def derive_focus_presets_from_combo_tips(
    combo_tips: list[dict[str, str]], focus_defs: list[dict[str, str]]
) -> list[dict[str, Any]]:
    id_to_name: dict[str, str] = {}
    for d in focus_defs:
        if not isinstance(d, dict):
            continue
        pid = norm_focus_id(str(d.get("id") or ""))
        name = str(d.get("name") or "").strip()
        if pid and name:
            id_to_name[pid] = name
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in combo_tips:
        if not isinstance(row, dict):
            continue
        stage = str(row.get("stage") or "").strip()
        stage = re.sub(r"\*+", "", stage).strip()
        recommended = str(row.get("recommended") or "").strip()
        if not stage or not recommended:
            continue
        fid_list = parse_focus_ids_from_recommended(recommended)
        names = [id_to_name.get(norm_focus_id(fid)) for fid in fid_list]
        focus_points = [n for n in names if n]
        if not focus_points:
            continue
        pid = f"skill_{slugify_id(stage)}"
        if pid in seen:
            continue
        seen.add(pid)
        row_obj: dict[str, Any] = {"id": pid, "name": stage, "focus_points": focus_points}
        for key in ("review_role", "review_goals_principles", "output_requirements"):
            v = str(row.get(key) or "").strip()
            if v:
                row_obj[key] = v
        out.append(row_obj)
    return out


def merge_preset_review_into_derived(
    derived: list[dict[str, Any]], overlay: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {str(x.get("id")): x for x in overlay if isinstance(x, dict) and x.get("id")}
    out: list[dict[str, Any]] = []
    for p in derived:
        pid = str(p.get("id") or "")
        o = by_id.get(pid)
        merged = dict(p)
        if o:
            for k in ("review_role", "review_goals_principles", "output_requirements"):
                v = o.get(k)
                if isinstance(v, str) and v.strip():
                    merged[k] = v.strip()
        out.append(merged)
    return out


def trim_accidental_combo_section_in_prompt(prompt: str) -> str:
    if not prompt:
        return prompt
    lines = prompt.splitlines()
    out: list[str] = []
    for line in lines:
        st = normalize_md_line_for_heading(line)
        if re.match(r"^##(?!#)", st) and is_combo_suggestions_heading(st):
            break
        if is_combo_like_h3_heading(line):
            break
        out.append(line)
    return "\n".join(out).strip()


def extract_domain_intro_preamble(text: str) -> str | None:
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        st = normalize_md_line_for_heading(lines[i]).strip()
        if st.startswith("# ") and not st.startswith("##") and "分析规则配置" in st:
            i += 1
            parts: list[str] = []
            while i < len(lines):
                st2 = normalize_md_line_for_heading(lines[i]).strip()
                if re.match(r"^##(?!#)", st2):
                    break
                parts.append(lines[i])
                i += 1
            out = "\n".join(parts).strip()
            return out or None
        i += 1
    return None


def read_composer_hint_from_domain_text(text: str) -> str | None:
    preamble = extract_domain_intro_preamble(text)
    if not preamble:
        return None
    m = re.search(r"目的\s*[:：]\s*([^\n\r]+)", preamble)
    if not m:
        return None
    hint = m.group(1).strip()
    return hint or None


def read_settings_from_package_dir(package_dir: "Path") -> tuple[dict[str, Any] | None, str | None]:
    """
    Read focus points from a skill package directory.
    Prefers focus-points/*.md (v2) if present; falls back to review_domain.md (v1).
    """
    from pathlib import Path as _Path
    from backend.skills.focus_point_io import list_focus_points

    fps_dir = package_dir / "focus-points"
    if fps_dir.is_dir() and any(fps_dir.glob("focus-*.md")):
        fps = list_focus_points(package_dir)
        if fps:
            return {
                "focus_points": [
                    {"id": fp.id, "name": fp.name, "prompt": fp.prompt}
                    for fp in fps
                ]
            }, None

    domain_f = package_dir / "review_domain.md"
    if not domain_f.is_file():
        return None, "review_domain.md not found and no focus-points/ files"
    text = domain_f.read_text(encoding="utf-8", errors="replace")
    return read_settings_from_domain_text(text)


def read_settings_from_domain_text(text: str) -> tuple[dict[str, Any] | None, str | None]:
    strict_err = review_domain_strict_schema_error(text)
    if strict_err:
        return None, strict_err

    lines = text.splitlines()

    focus_points: list[dict[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("### focus:"):
            rest = line[len("### focus:") :].strip()
            if "|" in rest:
                pid, name = [x.strip() for x in rest.split("|", 1)]
            else:
                pid = rest
                name = rest
            j = i + 1
            buf: list[str] = []
            while j < len(lines):
                nxt = lines[j]
                st = normalize_md_line_for_heading(nxt)
                if st.startswith("### focus:"):
                    break
                if re.match(r"^##(?!#)", st):
                    break
                if is_combo_like_h3_heading(nxt):
                    break
                buf.append(nxt)
                j += 1
            prompt = trim_accidental_combo_section_in_prompt("\n".join(buf).strip())
            if pid and name:
                focus_points.append({"id": pid, "name": name, "prompt": prompt})
            i = j
            continue
        i += 1

    if not focus_points:
        return None, "review_domain.md 格式无效：未找到“关注点块”（格式：### focus:<id> | <name>）"

    out: dict[str, Any] = {"focus_points": focus_points}
    return out, None


def write_review_domain_file(
    path: Path,
    payload: dict[str, Any],
    default_focus_points: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    focus_points = payload.get("focus_points")
    if not isinstance(focus_points, list):
        focus_points = default_focus_points
    elif len(focus_points) == 0:
        focus_points = default_focus_points

    focus_presets = payload.get("focus_presets")
    if not isinstance(focus_presets, list):
        focus_presets = []

    blocks: list[str] = []
    for item in focus_points:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        prm = trim_accidental_combo_section_in_prompt(str(item.get("prompt") or "").strip())
        if not fid or not name:
            continue
        blocks.append(f"### focus:{fid} | {name}\n{prm}\n")

    existing_suffix = ""
    intro_block = "该文件由 AI-KA 自动维护，用于保存关注点及其 Prompt。\n\n"
    if path.is_file():
        old_text = path.read_text(encoding="utf-8", errors="replace")
        preserved_intro = extract_domain_intro_preamble(old_text)
        if preserved_intro:
            intro_block = preserved_intro.rstrip() + "\n\n"
        lines = old_text.splitlines()
        start = -1
        for i, raw in enumerate(lines):
            if is_combo_suggestions_heading(raw):
                start = i
                break
        if start >= 0:
            j = start + 1
            in_table = False
            while j < len(lines):
                line = lines[j].strip()
                if line.startswith("|"):
                    in_table = True
                    j += 1
                    continue
                if in_table:
                    break
                j += 1
            existing_suffix = "\n".join(lines[j:]).strip()

    combo_lines: list[str] = []
    if focus_presets:
        combo_lines.append("## 组合使用建议\n")
        combo_lines.append("| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |")
        combo_lines.append("| --- | --- | --- | --- | --- |")
        for it in focus_presets:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            fps = it.get("focus_points")
            if not name or not isinstance(fps, list):
                continue
            by_name = {str(d.get("name") or ""): str(d.get("id") or "") for d in focus_points if isinstance(d, dict)}
            ids = [by_name.get(str(x), "") for x in fps]
            ids = [x for x in ids if x]
            if not ids:
                continue
            rec = " + ".join(f"`focus:{x}`" for x in ids)
            rr = combo_cell_encode(str(it.get("review_role") or ""))
            rg = combo_cell_encode(str(it.get("review_goals_principles") or ""))
            ro = combo_cell_encode(str(it.get("output_requirements") or ""))
            n_enc = combo_cell_encode(name)
            rec_enc = combo_cell_encode(rec)
            combo_lines.append(f"| {n_enc} | {rec_enc} | {rr} | {rg} | {ro} |")
        combo_lines.append("")

    md = (
        "# 分析规则配置\n\n"
        + intro_block
        + "## 关注点块\n\n"
        + "\n".join(blocks)
    )
    if combo_lines:
        md = md.rstrip() + "\n\n---\n\n" + "\n".join(combo_lines).rstrip() + "\n"
    if existing_suffix:
        md = md.rstrip() + "\n\n" + existing_suffix.strip() + "\n"
    strict_err = review_domain_strict_schema_error(md)
    if strict_err:
        raise ValueError(strict_err)
    path.write_text(md, encoding="utf-8")
