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


def build_case_pool_notice() -> str:
    """2026-09-11 用于声明案例池检索制：案例不进正文注入，只经 search_pool 展示

    历史背景：09-04 曾要求"疑点必须先用 search_pool 检索再解决"，模型把非
    案例问题也塞进检索，第 3 章 15 轮 40 次检索 0 写入死锁；09-05 该流程
    规则被删、改回全量注入编号表。本次改为不注入 + 检索制：执行动作与否
    由模型自行判断，此处只说明通道与编号规则，不规定处理顺序。
    """
    return (
        "<ActiveCases>\n"
        "案例池未随正文注入。用 search_pool 检索活动案例（关键词匹配，或用 "
        'case_type 枚举全部/某类型），检索即授权其编号；案例的解决/关闭一律'
        "使用 search_pool 回执中的 case_number。\n"
        "</ActiveCases>"
    )


def build_chunk_message(
    *,
    chunk_index: int,
    chunk_total: int,
    chunk_text: str,
    candidates: list[DialogueCandidate],
) -> str:
    """2026-08-07 用于向 Agent 提供当前唯一可写 chunk 和有序候选

    2026-08-22事件不再携带段落锚点，移除 ¶N 段落标记注入。
    2026-09-07 句级监督：新增自选句标签区块（提交渠道=write_metrics 的
    sentence_labels 可选参数，不新增工具；选句标准见 write_metrics docstring）。
    2026-09-10 候选字段 index 改名 candidate_index，消除与案例编号空间的混同
    （run a83fae3d 思考实测映射推理 1725 次、显式困惑 39 次）。
    2026-09-11 案例改检索制：ActiveCases 区块从编号表降级为通道说明，案例
    编号只由 search_pool 回执产生。
    """
    candidate_views = [
        {
            "candidate_index": index,
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
        build_case_pool_notice(),
        "<DialogueCandidates>\n"
        f"{json.dumps(candidate_views, ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
        "<SentenceLabels>\n"
        "请从上方正文中自选 2-3 个完整句子（原样摘录，不改写），随 write_metrics 的 "
        "sentence_labels 参数为每句提交整句情绪标签（emotion 为 -2..2 整数分值，"
        "同 write_metrics.emotional_valence）。选择权在模型："
        "优先选情绪表达有代表性、或语气/标点有区分度的句子；也允许选 0 分句。\n"
        "</SentenceLabels>",
    ]
    return "\n\n".join(sections)


__all__ = ["build_case_pool_notice", "build_chunk_message", "build_system_prompt"]
