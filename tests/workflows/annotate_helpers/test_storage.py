"""
annotate_helpers.storage 单元测试。

创建时间: 2026-04-23
任务: p2-store-annotation-results-split
说明: 直接覆盖伏笔合并与对话快照转换 helper，保护这次拆出的数据变换边界。
"""

from __future__ import annotations

from src.models.local.schema import CharacterSnapshot, ChunkAnnotation, ForeshadowingResult
from src.workflows.annotate_helpers.storage import _build_dialogue_snapshots, _merge_annotation_foreshadowing


def _make_annotation() -> ChunkAnnotation:
    """构造用于存储测试的最小 annotation。"""
    return ChunkAnnotation(
        emotional_valence="neutral",
        event_type="铺垫",
        pivot_moment=False,
        cliffhanger=False,
        chunk_summary="白芷察觉异样。",
        has_foreshadowing=False,
        foreshadowing_type=None,
        foreshadowing_desc="",
        characters=[
            CharacterSnapshot(
                name="白芷",
                role_function="主体",
                action="观察",
                action_type="其他",
                emotion_score="neutral",
            )
        ],
        dialogues=[],
    )


def test_merge_annotation_foreshadowing_overrides_phase2_fields() -> None:
    """伏笔合并后应以 Phase2 结果覆盖 annotation 中的伏笔字段。"""
    merged = _merge_annotation_foreshadowing(
        _make_annotation(),
        ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="causal",
            anchor_text="铜铃",
            anchor_reason="反复出现但用途未明",
            confidence="high",
        ),
    )

    assert merged.has_foreshadowing is True
    assert merged.foreshadowing_type == "causal"
    assert merged.foreshadowing_desc == "铜铃 - 反复出现但用途未明"


def test_build_dialogue_snapshots_keeps_speaker_tone_and_identity_clue_alignment() -> None:
    """对话快照转换应按 dialogue_idx 对齐 speaker、tone 与身份线索。"""
    snapshots, lengths = _build_dialogue_snapshots(
        dialogues=[(0, "你是谁？"), (1, "我是白芷。")],
        dialogue_speakers={0: ["未知"], 1: ["白芷"]},
        dialogue_tones={0: "警惕", 1: "平静"},
        dialogue_identity_clues={1: "自报姓名"},
    )

    assert lengths == [4, 5]
    assert snapshots[0].speaker == ["未知"]
    assert snapshots[0].tone == "警惕"
    assert snapshots[0].identity_clue is None
    assert snapshots[1].speaker == ["白芷"]
    assert snapshots[1].tone == "平静"
    assert snapshots[1].identity_clue == "自报姓名"
