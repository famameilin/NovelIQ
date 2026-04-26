"""
annotate_helpers.storage 单元测试。

创建时间: 2026-04-23
任务: p2-store-annotation-results-split
说明: 直接覆盖伏笔合并与对话快照转换 helper，保护这次拆出的数据变换边界。
"""

from __future__ import annotations

import runpy
from pathlib import Path

from src.models.local.annotation.projectors.foreshadowing import normalize_foreshadowing_result
from src.models.local.schema import CharacterSnapshot, ChunkAnnotation, ForeshadowingResult, LocationAppearance
from src.workflows.annotate_helpers.storage import _build_dialogue_snapshots, _merge_annotation_foreshadowing

_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "phase2_strong_foreshadowing_cases.py"
_FIXTURE_DATA = runpy.run_path(str(_FIXTURE_PATH))
PHASE2_STRONG_FORESHADOWING_CASES = _FIXTURE_DATA["PHASE2_STRONG_FORESHADOWING_CASES"]


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
            is_strong_setup=True,
            foreshadowing_type="物件",
            setup_kind="异常物件",
            anchor_text="铜铃",
            anchor_reason="反复出现但用途未明",
            why_unresolved_now="当前还没有解释铜铃为何反复出现。",
            expected_payoff_family="能力触发",
            confidence="high",
        ),
    )

    assert merged.has_foreshadowing is True
    assert merged.is_strong_setup is True
    assert merged.foreshadowing_type == "物件"
    assert merged.setup_kind == "异常物件"
    assert merged.foreshadowing_desc == "铜铃 - 反复出现但用途未明"
    assert merged.why_unresolved_now == "当前还没有解释铜铃为何反复出现。"
    assert merged.expected_payoff_family == "能力触发"


def test_strong_foreshadowing_projection_only_merges_validated_cases() -> None:
    """真实强伏笔回归样本应先经过 validator，再决定是否投影回 ChunkAnnotation。"""
    base = _make_annotation()
    chunk2 = next(case for case in PHASE2_STRONG_FORESHADOWING_CASES if case["chunk_id"] == 2)
    chunk12 = next(case for case in PHASE2_STRONG_FORESHADOWING_CASES if case["chunk_id"] == 12)

    rejected = normalize_foreshadowing_result(
        ForeshadowingResult.model_construct(**chunk2["result"]),
        chunk2["chunk_text"],
        chunk2["chunk_id"],
    )
    accepted = normalize_foreshadowing_result(
        ForeshadowingResult(**chunk12["result"]),
        chunk12["chunk_text"],
        chunk12["chunk_id"],
    )

    merged_rejected = _merge_annotation_foreshadowing(base, rejected)
    merged_accepted = _merge_annotation_foreshadowing(base, accepted)

    assert rejected is None
    assert merged_rejected.has_foreshadowing is False
    assert merged_rejected.is_strong_setup is False
    assert merged_rejected.foreshadowing_type is None
    assert accepted is not None
    assert merged_accepted.has_foreshadowing is True
    assert merged_accepted.is_strong_setup is True
    assert merged_accepted.foreshadowing_type == "人物行为"
    assert merged_accepted.setup_kind == "因果引线"
    assert "借助于人类之外的力量" in merged_accepted.foreshadowing_desc


def test_merge_annotation_foreshadowing_clears_negative_state_and_preserves_non_phase2_fields() -> None:
    """negative 结果不应把 strong setup 脏字段写回 annotation，同时要保留其他上下文字段。"""
    annotation = ChunkAnnotation(
        emotional_valence="neutral",
        event_type="铺垫",
        pivot_moment=False,
        cliffhanger=False,
        chunk_summary="白芷察觉异样。",
        has_foreshadowing=False,
        foreshadowing_type=None,
        foreshadowing_desc="",
        characters=[],
        dialogues=[],
        location_appearances=[LocationAppearance(raw_name="旧宅", location_type="building")],
        dialogue_lengths=[4],
    )
    merged = _merge_annotation_foreshadowing(
        annotation,
        ForeshadowingResult.model_construct(
            has_foreshadowing=False,
            is_strong_setup=True,
            foreshadowing_type=None,
            setup_kind="异常物件",
            anchor_text="",
            anchor_reason="具体钩子：无。未闭合原因：这里只是在解释为什么不是伏笔。",
            why_unresolved_now="",
            expected_payoff_family="",
            confidence="low",
        ),
    )

    assert merged.has_foreshadowing is False
    assert merged.is_strong_setup is False
    assert merged.foreshadowing_type is None
    assert merged.setup_kind is None
    assert merged.why_unresolved_now == ""
    assert merged.expected_payoff_family == ""
    assert merged.location_appearances == annotation.location_appearances
    assert merged.dialogue_lengths == annotation.dialogue_lengths


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
