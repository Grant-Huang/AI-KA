from __future__ import annotations

import re
from .conversation_models import UserIntent

# 规则优先，按匹配顺序短路；CHAT 为兜底。
# 每条规则：(intent, must_match_any_of_these_patterns)
_RULES: list[tuple[UserIntent, list[str]]] = [
    (
        UserIntent.GENERATE_DOC,
        [r"生成报告", r"输出报告", r"导出报告", r"写报告", r"生成文档", r"导出文档",
         r"生成审查报告", r"生成评审报告", r"输出文档", r"写文档"],
    ),
    (
        UserIntent.UPDATE_FINDING,
        [r"f-\d+.{0,10}(已知|不重要|确认|关闭|忽略|resolved|acknowledged)",
         r"(已知|不重要|确认|关闭|忽略).{0,10}f-\d+",
         r"标记.{0,10}(已知|已解决|不重要)"],
    ),
    (
        UserIntent.REFINE,
        [r"不够深", r"太表面", r"再深入", r"再仔细", r"重新审查", r"重新分析",
         r"深入分析", r"加强分析", r"更详细", r"细化", r"补充分析",
         r"深度模式", r"继续深挖"],
    ),
    (
        UserIntent.CLARIFY,
        [r"什么意思", r"解释一下", r"详细说", r"展开说", r"说明一下",
         r"能举例吗", r"举个例子", r"具体是指", r"能详细说明",
         r"为什么这么说", r"依据是什么", r"证据在哪"],
    ),
    (
        UserIntent.ANALYZE_NEW,
        [r"审查", r"分析", r"检查", r"评审", r"review",
         r"看看.{0,10}(章|节|部分|文档|方案|设计)",
         r"(章|节|部分|文档|方案|设计).{0,10}(有没有|存在|问题|风险|遗漏)"],
    ),
]


def classify_intent(text: str) -> UserIntent:
    """
    规则优先意图分类。
    返回 CHAT 表示普通问答，不触发任何分析管道。
    """
    t = (text or "").strip()
    if not t:
        return UserIntent.CHAT

    for intent, patterns in _RULES:
        for pat in patterns:
            if re.search(pat, t, re.IGNORECASE):
                return intent

    return UserIntent.CHAT
