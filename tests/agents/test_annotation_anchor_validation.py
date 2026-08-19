"""validate_bound_annotation 事件锚点校验分支测试

覆盖：
- 事件锚点超出 chunk 文本范围 → 事件锚点超出原文范围
- 事件锚点 char_end <= char_start → 事件锚点 char_end 必须大于 char_start
- 事件锚点文本哈希不一致 → 事件锚点文本哈希不一致
- 合法事件锚点通过校验
"""

from __future__ import annotations

import hashlib

import pytest

from src.agents.annotation.runner import validate_bound_annotation
from src.agents.annotation.schema import (
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundEntityDirectory,
    BoundEvent,
    ChunkMetricsInput,
    TextEvidence,
)

_CHUNK_TEXT = "顾霜拔剑。"
_CHUNK_ID = 1


def _chapter_annotation(events: list[BoundEvent]) -> BoundChapterAnnotation:
    """2026-08-18 用于构造绑定单个 chunk 的正式标注"""
    return BoundChapterAnnotation(
        chapter_summary="测试摘要",
        chunks=[
            BoundChunkAnnotation(
                chunk_id=_CHUNK_ID,
                metrics=ChunkMetricsInput(
                    summary="chunk 摘要",
                    emotional_valence="neutral",
                    narrative_function="铺垫",
                    pivot_moment=False,
                    cliffhanger=False,
                ),
                entities=BoundEntityDirectory(),
                character_observations=[],
                dialogues=[],
                events=events,
                relations=[],
                foreshadowings=[],
            )
        ],
    )


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _event(*, char_start: int, char_end: int, text_hash: str) -> BoundEvent:
    """2026-08-18 用于构造指定锚点字段的事件（evidence 独立持有合法区间）"""
    return BoundEvent(
        description="顾霜拔剑",
        participants=[],
        anchor_paragraph_ids=[0],
        causal_event_refs=[],
        tree_id="tree-a",
        cause_role="root",
        char_start=char_start,
        char_end=char_end,
        text_hash=text_hash,
        evidence=[
            TextEvidence(
                paragraph_ids=[0],
                char_start=0,
                char_end=len(_CHUNK_TEXT),
                text_hash=_hash(_CHUNK_TEXT),
            )
        ],
    )


def _validate(events: list[BoundEvent]) -> None:
    validate_bound_annotation(
        _chapter_annotation(events),
        chapter_id=1,
        current_chunks=[(_CHUNK_ID, _CHUNK_TEXT)],
    )


def test_event_anchor_out_of_chunk_range_raises() -> None:
    """2026-08-18 用于验证锚点超出章节原文范围被拒绝"""
    with pytest.raises(ValueError, match="事件锚点超出原文范围"):
        _validate(
            [
                _event(
                    char_start=0,
                    char_end=len(_CHUNK_TEXT) + 100,
                    text_hash=_hash(_CHUNK_TEXT),
                )
            ]
        )


def test_event_anchor_inverted_range_raises() -> None:
    """2026-08-18 用于验证 char_end <= char_start 被拒绝"""
    with pytest.raises(ValueError, match="事件锚点 char_end 必须大于 char_start"):
        _validate([_event(char_start=3, char_end=2, text_hash=_hash(_CHUNK_TEXT))])


def test_event_anchor_text_hash_mismatch_raises() -> None:
    """2026-08-18 用于验证锚点文本哈希与原文切片不一致被拒绝"""
    with pytest.raises(ValueError, match="事件锚点文本哈希不一致"):
        _validate(
            [
                _event(
                    char_start=0,
                    char_end=len(_CHUNK_TEXT),
                    text_hash=_hash("其它文本"),
                )
            ]
        )


def test_event_anchor_valid_passes() -> None:
    """2026-08-18 用于验证合法锚点通过校验（不抛异常）"""
    _validate([_event(char_start=0, char_end=len(_CHUNK_TEXT), text_hash=_hash(_CHUNK_TEXT))])