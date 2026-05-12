"""Tests for ki_parser.py"""
from __future__ import annotations

from backend.ki_parser import extract_clarify, extract_ki_items, extract_satisfaction


def test_extract_ki_basic():
    text = """
分析结论：金融项目需要合规审查。

<!-- ki: {"focus": "req", "title": "合规需求必须纳入", "confidence": "high",
          "content": "IF 金融类项目 THEN 需求必须包含监管章节",
          "applicable_when": {"project_type": ["finance"]},
          "evidence": "专家陈述：金融项目必须有合规章节"} -->
"""
    items = extract_ki_items(text)
    assert len(items) == 1
    item = items[0]
    assert item["focus_id"] == "req"
    assert item["title"] == "合规需求必须纳入"
    assert item["confidence"] == "high"
    assert item["applicable_when"] == {"project_type": ["finance"]}
    assert "金融类项目" in item["content"]


def test_extract_ki_multiple():
    text = """
<!-- ki: {"focus": "risk", "title": "风险一", "confidence": "medium", "content": "rule1"} -->
<!-- ki: {"focus": "req", "title": "风险二", "confidence": "low", "content": "rule2"} -->
"""
    items = extract_ki_items(text)
    assert len(items) == 2


def test_extract_ki_invalid_json_skipped():
    text = "<!-- ki: {invalid json} -->"
    items = extract_ki_items(text)
    assert items == []


def test_extract_ki_missing_title_skipped():
    text = '<!-- ki: {"focus": "req", "confidence": "high", "content": "c"} -->'
    items = extract_ki_items(text)
    assert items == []


def test_extract_ki_confidence_default():
    text = '<!-- ki: {"focus": "f", "title": "t", "content": "c"} -->'
    items = extract_ki_items(text)
    assert items[0]["confidence"] == "medium"


def test_extract_ki_invalid_confidence_normalized():
    text = '<!-- ki: {"focus": "f", "title": "t", "confidence": "critical", "content": "c"} -->'
    items = extract_ki_items(text)
    assert items[0]["confidence"] == "medium"


def test_extract_clarify_basic():
    text = """
Some analysis.
<!-- clarify: {"strategy": "gap_based", "questions": ["追问1", "追问2"]} -->
"""
    result = extract_clarify(text)
    assert result is not None
    assert result["strategy"] == "gap_based"
    assert len(result["questions"]) == 2
    assert "追问1" in result["questions"]


def test_extract_clarify_none_when_absent():
    text = "No clarify markers here."
    assert extract_clarify(text) is None


def test_extract_satisfaction_basic():
    text = "Analysis done. <!-- satisfaction: 0.92 -->"
    score = extract_satisfaction(text)
    assert score is not None
    assert abs(score - 0.92) < 0.001


def test_extract_satisfaction_last_wins():
    text = "<!-- satisfaction: 0.5 --> more text <!-- satisfaction: 0.9 -->"
    score = extract_satisfaction(text)
    assert abs(score - 0.9) < 0.001


def test_extract_satisfaction_none_when_absent():
    text = "No satisfaction marker."
    assert extract_satisfaction(text) is None


def test_extract_ki_with_focus_id_alias():
    """Test that both 'focus' and 'focus_id' are accepted."""
    text1 = '<!-- ki: {"focus": "req", "title": "t1", "content": "c"} -->'
    text2 = '<!-- ki: {"focus_id": "req", "title": "t2", "content": "c"} -->'
    assert extract_ki_items(text1)[0]["focus_id"] == "req"
    assert extract_ki_items(text2)[0]["focus_id"] == "req"
