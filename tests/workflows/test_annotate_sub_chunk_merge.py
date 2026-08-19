"""
子块切分与合并单元测试（2026-08-15 对话坐标重映射）

覆盖 src/workflows/annotate.py：
- _split_chapter_sub_chunks 返回 (子块 ID, 文本, 章内起始偏移) 三元组
- _merge_sub_chunk_annotations 把第 2+ 子块的对话 start/end 从子块相对坐标
  平移回章文本坐标，首块坐标保持不变
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from src.agents.annotation.schema import (
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEntityDirectory,
    BoundEvent,
    ChunkMetricsInput,
    EmotionalValence,
    NarrativeFunction,
    TextEvidence,
)
from src.workflows.annotate import _merge_sub_chunk_annotations, _split_chapter_sub_chunks


def _make_sub_annotation(chunk_id: int, *, summary: str, dialogue: BoundDialogue) -> BoundChapterAnnotation:
    """构造恰好包含一个 chunk 的最小子块标注"""
    return BoundChapterAnnotation(
        chapter_summary=summary,
        chunks=[
            BoundChunkAnnotation(
                chunk_id=chunk_id,
                metrics=ChunkMetricsInput(
                    summary=summary,
                    emotional_valence=EmotionalValence.NEUTRAL,
                    narrative_function=NarrativeFunction.SETUP,
                ),
                entities=BoundEntityDirectory(entities=[]),
                character_observations=[],
                dialogues=[dialogue],
                events=[],
                relations=[],
                foreshadowings=[],
            )
        ],
    )


def _event(description: str, *, refs: list[str], role: str) -> BoundEvent:
    """2026-08-19 用于构造契约 v3 事件（含树结构与全局 event_id 因果引用）"""
    return BoundEvent(
        description=description,
        participants=[],
        anchor_paragraph_ids=[0],
        causal_event_refs=refs,
        tree_id="tree-merge",
        cause_role=role,  # type: ignore[arg-type]
        char_start=0,
        char_end=3,
        text_hash="0" * 64,
        evidence=[TextEvidence(paragraph_ids=[0], char_start=0, char_end=3, text_hash="0" * 64)],
    )


def _make_event_sub_annotation(chunk_id: int, *, summary: str, events: list[BoundEvent]) -> BoundChapterAnnotation:
    """2026-08-19 用于构造带事件的子块标注"""
    return BoundChapterAnnotation(
        chapter_summary=summary,
        chunks=[
            BoundChunkAnnotation(
                chunk_id=chunk_id,
                metrics=ChunkMetricsInput(
                    summary=summary,
                    emotional_valence=EmotionalValence.NEUTRAL,
                    narrative_function=NarrativeFunction.SETUP,
                ),
                entities=BoundEntityDirectory(entities=[]),
                character_observations=[],
                dialogues=[],
                events=events,
                relations=[],
                foreshadowings=[],
            )
        ],
    )


def test_split_chapter_sub_chunks_returns_offsets() -> None:
    """子块三元组携带章内起始偏移，供合并阶段重映射对话坐标"""
    chapter_text = "第一段。" * 20  # 80 字符
    paragraphs = [
        SimpleNamespace(local_start_char=0),
        SimpleNamespace(local_start_char=20),
        SimpleNamespace(local_start_char=40),
        SimpleNamespace(local_start_char=60),
    ]

    sub_chunks = _split_chapter_sub_chunks(
        chapter_text,
        paragraphs,
        chapter_chunk_id=7,
        max_chars=30,
    )

    # 成块条件：累计字符 ≥ max_chars 才收块，20/60 处不满 30 并入前块
    assert [chunk_id for chunk_id, _, _ in sub_chunks] == [-1, -2]
    assert [offset for _, _, offset in sub_chunks] == [0, 40]
    # 各子块文本确为其起始偏移处的切片
    for chunk_id, text, offset in sub_chunks:
        assert text == chapter_text[offset:offset + len(text)]
        assert chunk_id < 0


def test_split_chapter_sub_chunks_within_limit_returns_single_block_offset_zero() -> None:
    chapter_text = "短章。"
    sub_chunks = _split_chapter_sub_chunks(
        chapter_text,
        [SimpleNamespace(local_start_char=0)],
        chapter_chunk_id=7,
        max_chars=30,
    )
    assert sub_chunks == [(7, chapter_text, 0)]


def test_merge_remaps_dialogues_of_later_sub_chunks() -> None:
    """第 2+ 子块的对话坐标平移回章坐标，首块坐标不变"""
    first = _make_sub_annotation(
        -1,
        summary="第一块",
        dialogue=BoundDialogue(
            candidate_index=1,
            candidate_key="k1",
            content="甲说",
            start=2,
            end=5,
            speaker="甲",
        ),
    )
    second = _make_sub_annotation(
        -2,
        summary="第二块",
        dialogue=BoundDialogue(
            candidate_index=1,
            candidate_key="k2",
            content="乙说",
            start=3,
            end=6,
            speaker="乙",
        ),
    )

    merged = _merge_sub_chunk_annotations(
        [first, second],
        chapter_chunk_id=7,
        sub_chunk_offsets=[0, 20],
        run_id="run-1",
        chapter_id=7,
    )

    assert merged.chunks[0].chunk_id == 7
    first_dialogue, second_dialogue = merged.chunks[0].dialogues
    assert (first_dialogue.start, first_dialogue.end) == (2, 5)
    assert (second_dialogue.start, second_dialogue.end) == (23, 26)


def test_merge_rejects_mismatched_offsets_length() -> None:
    import pytest

    annotation = _make_sub_annotation(
        -1,
        summary="单块",
        dialogue=BoundDialogue(
            candidate_index=1,
            candidate_key="k1",
            content="甲说",
            start=0,
            end=3,
        ),
    )
    with pytest.raises(ValueError, match="sub_chunk_offsets"):
        _merge_sub_chunk_annotations(
            [annotation],
            chapter_chunk_id=7,
            sub_chunk_offsets=[],
            run_id="run-1",
            chapter_id=7,
        )


def test_merge_remaps_causal_event_refs_to_chapter_ordinals() -> None:
    """2026-08-19 用于验证第 2+ 子块的事件 id 提升为整章序号 id（契约 v3）"""
    run_id = "run-1"
    chapter_id = 7
    # 子块 1：事件 1（root）+ 事件 2（main 引用事件 1）
    e1 = _event("进山", refs=[], role="root")
    e2 = _event("拔剑", refs=[str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:{chapter_id}:1"))], role="main")
    # 子块 2：事件 3（root）+ 事件 4（main 引用事件 3 子块内局部 id 1）
    local_e3_id = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:{chapter_id}:1"))
    e3 = _event("收势", refs=[], role="root")
    e4 = _event("入鞘", refs=[local_e3_id], role="main")

    merged = _merge_sub_chunk_annotations(
        [
            _make_event_sub_annotation(-1, summary="第一块", events=[e1, e2]),
            _make_event_sub_annotation(-2, summary="第二块", events=[e3, e4]),
        ],
        chapter_chunk_id=chapter_id,
        sub_chunk_offsets=[0, 20],
        run_id=run_id,
        chapter_id=chapter_id,
    )

    events = merged.chunks[0].events
    assert [event.description for event in events] == ["进山", "拔剑", "收势", "入鞘"]
    # 事件 4 的引用从子块局部 id（run:7:1）提升为整章序号 id（run:7:3）
    final_e3_id = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:{chapter_id}:3"))
    assert events[3].causal_event_refs == [final_e3_id]
    # 子块 1（offset=0）的引用保持整章序号 id（run:7:1）
    final_e1_id = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:{chapter_id}:1"))
    assert events[1].causal_event_refs == [final_e1_id]
