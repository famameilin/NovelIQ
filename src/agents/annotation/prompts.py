"""
章节标注 Agent 语义写入提示词
"""

from __future__ import annotations

import json

from .schema import DialogueCandidate

SYSTEM_PROMPT = "你是小说章节语义标注 Agent，请依据当前提供的小说正文完成语义标注。"


def build_system_prompt() -> str:
    """2026-08-30 用于构建只声明章节标注职责的单行系统提示词"""
    return SYSTEM_PROMPT


def build_chunk_message(
    *,
    chunk_index: int,
    chunk_total: int,
    chunk_text: str,
    candidates: list[DialogueCandidate],
) -> str:
    """2026-08-07 用于向 Agent 提供当前唯一可写 chunk 和有序候选

    2026-08-22事件不再携带段落锚点，移除 ¶N 段落标记注入。
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
    return (
        f'<CurrentChunk order="{chunk_index}/{chunk_total}">\n'
        f"{chunk_text}\n"
        "</CurrentChunk>\n\n"
        "<DialogueCandidates>\n"
        f"{json.dumps(candidate_views, ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>"
    )


__all__ = ["build_chunk_message", "build_system_prompt"]
