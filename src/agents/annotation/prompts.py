"""
章节标注 Agent 语义写入提示词
"""

from __future__ import annotations

import json

from .schema import DialogueCandidate

SYSTEM_PROMPT = "你是小说章节语义标注 Agent，请依据当前提供的小说正文完成语义标注。"


def build_system_prompt() -> str:
    """2026-08-30 用于构建只声明章节标注职责的单行系统提示词

    2026-09-04 曾追加"案例编号"检索管道规则，2026-09-05 裁决删除：
    该规则把非案例疑点（如对话说话人）误导进 search_pool 空转至上限
    （第3章 15 轮 40 次检索 0 写入）。编号授权=编号表注入展示即授权
    + 工具层 case_number 校验（未授权编号直接报错自纠）。
    """
    return SYSTEM_PROMPT


def build_initial_cases_block(cases: list[dict]) -> str:
    """2026-09-04 用于渲染初始活动案例编号表（展示即授权，与旧合同一致）"""
    if not cases:
        return "<ActiveCases>\n（无初始活动案例，需要时用 search_pool 检索）\n</ActiveCases>"
    return (
        "<ActiveCases>\n"
        f"{json.dumps(cases, ensure_ascii=False, indent=2)}\n"
        "</ActiveCases>"
    )


def build_chunk_message(
    *,
    chunk_index: int,
    chunk_total: int,
    chunk_text: str,
    candidates: list[DialogueCandidate],
    initial_cases: list[dict] | None = None,
) -> str:
    """2026-08-07 用于向 Agent 提供当前唯一可写 chunk 和有序候选

    2026-08-22事件不再携带段落锚点，移除 ¶N 段落标记注入。
    2026-09-04恢复初始案例编号表注入（cb4f96f1 误删，见 build_system_prompt）。
    2026-09-07 句级监督：新增自选句标签区块（提交渠道=write_metrics 的
    sentence_labels 可选参数，不新增工具；选句标准见 write_metrics docstring）。
    """
    candidate_views = [
        {
            "index": index,
            "id": candidate.candidate_key,
            "text": candidate.content,
            "parse_status": candidate.parse_status,
        }
        for index, candidate in enumerate(candidates, start=1)
    ]
    sections = [
        f'<CurrentChunk order="{chunk_index}/{chunk_total}">\n'
        f"{chunk_text}\n"
        "</CurrentChunk>",
        build_initial_cases_block(initial_cases or []),
        "<DialogueCandidates>\n"
        f"{json.dumps(candidate_views, ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
        "<SentenceLabels>\n"
        "请从上方正文中自选 2-3 个完整句子（原样摘录，不改写），随 write_metrics 的 "
        "sentence_labels 参数为每句提交整句情绪标签（emotion 英文枚举）。选择权在模型："
        "优先选情绪表达有代表性、或语气/标点有区分度的句子；也允许选 neutral 句。\n"
        "</SentenceLabels>",
    ]
    return "\n\n".join(sections)


__all__ = ["build_chunk_message", "build_system_prompt"]
