"""
Phase3 dialogue projector 单元测试。

创建时间: 2026-04-23
任务: annotation-projector-runtime-landing
说明: 覆盖 Phase3 raw records 到归一化对话结果的投影边界。
"""

from __future__ import annotations

from src.models.local.annotation.projectors.dialogue import normalize_dialogue_records, project_dialogue_lengths
from src.models.local.schema import DialogueRecord, DialogueRecordSchema, QuoteCandidate


def test_normalize_dialogue_records_skips_invalid_index_and_normalizes_alias() -> None:
    """非法 index 被跳过，合法 speaker 先做别名归一化。"""
    records = [
        DialogueRecordSchema(index=99, is_dialogue=True, speaker=["白芷"]),
        DialogueRecordSchema(index=1, is_dialogue=True, speaker=["猴子"]),
    ]
    candidates = [QuoteCandidate(index=1, content="你好")]

    result = normalize_dialogue_records(
        records,
        candidates,
        known_characters=["侯飞白"],
        alias_map={"猴子": "侯飞白"},
        chunk_id=1,
    )

    assert len(result) == 1
    assert result[0].speaker == ["侯飞白"]
    assert result[0].content == "你好"


def test_project_dialogue_lengths_deduplicates_and_counts_multi_speakers() -> None:
    """重复 dialogue index 只计一次，多人说话时每个 speaker 各计一次长度。"""
    records = [
        DialogueRecord(index=1, content="模型改写", is_dialogue=True, speaker=["白芷", "侯飞白"], tone="强硬"),
        DialogueRecord(index=1, content="重复", is_dialogue=True, speaker=["白芷"]),
        DialogueRecord(index=2, content="旁白", is_dialogue=False, speaker=None),
    ]
    candidates = [QuoteCandidate(index=1, content="原文"), QuoteCandidate(index=2, content="旁白")]

    result = project_dialogue_lengths(records, candidates, return_tones=True)

    assert result.dialogues == [(1, "原文")]
    assert result.speaker_lengths == {"白芷": 2, "侯飞白": 2}
    assert result.canonical_attribution == {1: ["白芷", "侯飞白"]}
    assert result.dialogue_tones == {1: "强硬"}


def test_project_dialogue_lengths_aligns_identity_clues() -> None:
    """identity clue 应按 dialogue index 对齐返回。"""
    records = [
        DialogueRecord(
            index=1,
            content="我是白芷",
            is_dialogue=True,
            speaker=["白芷"],
            identity_clue="自报姓名",
        )
    ]
    candidates = [QuoteCandidate(index=1, content="我是白芷")]

    result = project_dialogue_lengths(records, candidates, return_identity_clues=True)

    assert result.dialogue_identity_clues == {1: "自报姓名"}
