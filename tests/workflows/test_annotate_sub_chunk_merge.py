"""
子块切分与合并单元测试（2026-08-15 对话坐标重映射）

覆盖 src/workflows/annotate.py：
- _split_chapter_sub_chunks 返回 (子块 ID, 文本, 章内起始偏移) 三元组
- _merge_sub_chunk_annotations 把第 2+ 子块的对话 start/end 从子块相对坐标
  平移回章文本坐标，首块坐标保持不变
"""

from __future__ import annotations

from types import SimpleNamespace

from src.agents.annotation.schema import (
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEvent,
    ChunkMetricsInput,
    NarrativeFunction,
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
                    emotional_valence=0,
                    narrative_function=NarrativeFunction.SETUP,
                ),
                character_observations=[],
                dialogues=[dialogue],
                events=[],
            )
        ],
    )


def _event(description: str, *, refs: list[str], role: str) -> BoundEvent:
    """2026-08-19 用于构造事件（服务端 uuid 替身 id）"""
    return BoundEvent(
        node_id=f"evt-{description}",
        tree_id="tree-merge",
        parent_node_id=None,
        cause_role=role,  # type: ignore[arg-type]
        description=description,
        participants=[],
        causal_event_refs=refs,
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
                    emotional_valence=0,
                    narrative_function=NarrativeFunction.SETUP,
                ),
                character_observations=[],
                dialogues=[],
                events=events,
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
        assert text == chapter_text[offset : offset + len(text)]
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


def test_split_chapter_sub_chunks_tail_below_min_tail_merges_into_previous_block() -> None:
    """2026-09-11 章内并行 §9：尾块小于 min_tail_chars 并入前一块（ch13 尾块 84 字实测）"""
    chapter_text = "第一段。" * 15  # 60 字符，段落边界 0/20/40
    paragraphs = [
        SimpleNamespace(local_start_char=0),
        SimpleNamespace(local_start_char=20),
        SimpleNamespace(local_start_char=40),
    ]

    # max_chars=30：40 处成块，尾块 [40, 60) 只有 20 字
    merged = _split_chapter_sub_chunks(
        chapter_text,
        paragraphs,
        chapter_chunk_id=7,
        max_chars=30,
        min_tail_chars=1000,
    )
    assert len(merged) == 1
    assert merged[0][0] == -1
    assert merged[0][1] == chapter_text  # 尾块文本并入，内容完整
    assert merged[0][2] == 0

    # min_tail_chars=0 保持现行行为（两块）
    legacy = _split_chapter_sub_chunks(
        chapter_text,
        paragraphs,
        chapter_chunk_id=7,
        max_chars=30,
        min_tail_chars=0,
    )
    assert [chunk_id for chunk_id, _, _ in legacy] == [-1, -2]

    # 尾块 ≥ min_tail_chars 时保持独立
    kept = _split_chapter_sub_chunks(
        chapter_text,
        paragraphs,
        chapter_chunk_id=7,
        max_chars=30,
        min_tail_chars=20,
    )
    assert [chunk_id for chunk_id, _, _ in kept] == [-1, -2]
    assert kept[1][1] == chapter_text[40:]


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
        )


def test_merge_keeps_event_ids_and_refs_unmapped() -> None:
    """2026-08-22 事件 node_id/tree_id 与因果引用均为服务端一次性 uuid，合并只平移文本坐标"""
    e1 = _event("进山", refs=[], role="root")
    e2 = _event("拔剑", refs=["evt-upstream-root"], role="main")
    e3 = _event("收势", refs=[], role="root")
    e4 = _event("入鞘", refs=["evt-local-prev"], role="main")

    merged = _merge_sub_chunk_annotations(
        [
            _make_event_sub_annotation(-1, summary="第一块", events=[e1, e2]),
            _make_event_sub_annotation(-2, summary="第二块", events=[e3, e4]),
        ],
        chapter_chunk_id=7,
        sub_chunk_offsets=[0, 20],
    )

    events = merged.chunks[0].events
    assert [event.description for event in events] == ["进山", "拔剑", "收势", "入鞘"]
    # 引用原样保留，不做任何序号重排
    assert events[1].causal_event_refs == ["evt-upstream-root"]
    assert events[3].causal_event_refs == ["evt-local-prev"]


def test_merge_remaps_sentence_labels_of_later_sub_chunks() -> None:
    """2026-09-07 句级监督：第 2+ 子块的自选句情绪标签坐标平移回章坐标，首块不变"""
    from src.agents.annotation.schema import BoundSentenceLabel

    def _make_label_sub_annotation(chunk_id: int, summary: str, label: BoundSentenceLabel) -> BoundChapterAnnotation:
        return BoundChapterAnnotation(
            chapter_summary=summary,
            chunks=[
                BoundChunkAnnotation(
                    chunk_id=chunk_id,
                    metrics=ChunkMetricsInput(
                        summary=summary,
                        emotional_valence=0,
                        narrative_function=NarrativeFunction.SETUP,
                    ),
                    character_observations=[],
                    dialogues=[],
                    events=[],
                    sentence_labels=[label],
                )
            ],
        )

    first_label = BoundSentenceLabel(sentence="甲说", emotion=0, start=1, end=4)
    second_label = BoundSentenceLabel(
        sentence="乙说",
        emotion=-2,
        start=2,
        end=5,
    )
    merged = _merge_sub_chunk_annotations(
        [
            _make_label_sub_annotation(-1, "第一块", first_label),
            _make_label_sub_annotation(-2, "第二块", second_label),
        ],
        chapter_chunk_id=7,
        sub_chunk_offsets=[0, 20],
    )

    merged_labels = merged.chunks[0].sentence_labels
    assert [(label.sentence, label.emotion) for label in merged_labels] == [
        ("甲说", 0),
        ("乙说", -2),
    ]
    assert (merged_labels[0].start, merged_labels[0].end) == (1, 4)
    assert (merged_labels[1].start, merged_labels[1].end) == (22, 25)
