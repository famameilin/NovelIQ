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


def _event(description: str, *, role: str) -> BoundEvent:
    """2026-09-14 用于构造事件（服务端 uuid 替身 id；causal_event_refs 已随写面退役）"""
    return BoundEvent(
        node_id=f"evt-{description}",
        tree_id="tree-merge",
        parent_node_id=None,
        cause_role=role,  # type: ignore[arg-type]
        description=description,
        participants=[],
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


def test_merge_keeps_event_ids_unmapped() -> None:
    """2026-08-22 事件 node_id/tree_id 为服务端一次性 uuid，合并只平移文本坐标

    2026-09-14 写入面重构：BoundEvent.causal_event_refs 退役（原"因果引用原样
    透传"分断言已无写面对应物，由 test_graph_persistence 的事件/边断言面接管），
    本测试保留存续不变量：跨子块合并不得重排或改写任何事件节点身份。
    """
    e1 = _event("进山", role="root")
    e2 = _event("拔剑", role="main")
    e3 = _event("收势", role="root")
    e4 = _event("入鞘", role="main")

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
    # 身份原样保留：node_id 逐字不改、同树归属不变、不做任何序号重排
    assert [event.node_id for event in events] == ["evt-进山", "evt-拔剑", "evt-收势", "evt-入鞘"]
    assert {event.tree_id for event in events} == {"tree-merge"}
    assert [event.cause_role for event in events] == ["root", "main", "root", "main"]


def test_merge_keeps_paragraph_labels_unremapped() -> None:
    """2026-09-14 段落级监督：段标签取全局段号，合并按子块顺序直接拼接、绝不 remap

    旧"句标签跨子块坐标平移"合同（sentence_labels）随句级监督退役；本测试改写为
    新面的不变量断言——第 2+ 子块的 paragraph_id 不因合并偏移而被平移或重排。
    """
    from src.agents.annotation.schema import BoundParagraphLabel

    def _make_label_sub_annotation(
        chunk_id: int, summary: str, labels: list[BoundParagraphLabel]
    ) -> BoundChapterAnnotation:
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
                    paragraph_labels=labels,
                )
            ],
        )

    first_labels = [BoundParagraphLabel(paragraph_id=0, emotion=0)]
    second_labels = [
        BoundParagraphLabel(paragraph_id=2, emotion=-2),
        BoundParagraphLabel(paragraph_id=3, emotion=1),
    ]
    merged = _merge_sub_chunk_annotations(
        [
            _make_label_sub_annotation(-1, "第一块", first_labels),
            _make_label_sub_annotation(-2, "第二块", second_labels),
        ],
        chapter_chunk_id=7,
        sub_chunk_offsets=[0, 20],
    )

    merged_labels = merged.chunks[0].paragraph_labels
    # 全局段号原样透传：第二子块偏移 20 不得进入段号坐标
    assert [(label.paragraph_id, label.emotion) for label in merged_labels] == [
        (0, 0),
        (2, -2),
        (3, 1),
    ]
