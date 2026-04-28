"""
说明: Phase3 对话归属结果投影器，负责校验、归一化、长度派生与 storage-ready 快照。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from loguru import logger

from src.models.local.schema import DialogueRecord, DialogueRecordSchema, DialogueSnapshot, QuoteCandidate


@dataclass
class DialogueLengthResult:
    """
    Phase3 对话投影结果。
    """

    speaker_lengths: dict[str, int] = field(default_factory=dict)
    canonical_attribution: dict[int, list[str]] = field(default_factory=dict)
    dialogues: list[tuple[int, str]] = field(default_factory=list)
    dialogue_tones: dict[int, str] = field(default_factory=dict)
    dialogue_identity_clues: dict[int, str | None] = field(default_factory=dict)


def normalize_dialogue_records(
    records: Sequence[DialogueRecordSchema],
    candidates: Sequence[QuoteCandidate],
    known_characters: list[str] | None,
    alias_map: dict[str, str] | None,
    chunk_id: int | None,
) -> list[DialogueRecord]:
    """
    校验 Phase3 raw records 并完成 speaker 别名归一化。
    """
    valid_records: list[DialogueRecord] = []
    candidate_indices = {c.index for c in candidates}
    known_set = None
    if known_characters:
        known_set = {alias_map.get(name, name) if alias_map else name for name in known_characters}

    unknown_count = 0
    candidate_map = {c.index: c.content for c in candidates}

    for schema_record in records:
        if schema_record.index not in candidate_indices:
            logger.warning(
                f"phase3_validation: invalid index {schema_record.index}, "
                f"not in candidates range, skipping, chunk_id={chunk_id}"
            )
            continue

        content = candidate_map.get(schema_record.index)
        record = DialogueRecord(
            index=schema_record.index,
            content=content,
            is_dialogue=schema_record.is_dialogue,
            speaker=schema_record.speaker,
            tone=schema_record.tone,
            is_inner_monologue=schema_record.is_inner_monologue,
            identity_clue=schema_record.identity_clue,
        )

        if not record.speaker:
            valid_records.append(record)
            continue

        canonical_speakers: list[str] = []
        seen_canonical_speakers: set[str] = set()
        for speaker in record.speaker:
            canonical = alias_map.get(speaker, speaker) if alias_map else speaker
            if canonical in seen_canonical_speakers:
                continue
            seen_canonical_speakers.add(canonical)
            canonical_speakers.append(canonical)

        if known_set:
            for speaker in canonical_speakers:
                if speaker not in known_set:
                    unknown_count += 1
                    logger.info(
                        f"phase3_validation: speaker '{speaker}' not in known_set, "
                        f"keeping LLM judgment. chunk_id={chunk_id} index={record.index}"
                    )

        if canonical_speakers != record.speaker:
            valid_records.append(record.model_copy(update={"speaker": canonical_speakers}))
        else:
            valid_records.append(record)

    if unknown_count > 0:
        logger.info(f"phase3_validation summary: unknown_speakers={unknown_count}, chunk_id={chunk_id}")

    return valid_records


def project_dialogue_lengths(
    records: Sequence[DialogueRecord],
    candidates: Sequence[QuoteCandidate],
    *,
    return_tones: bool = False,
    return_identity_clues: bool = False,
) -> DialogueLengthResult:
    """
    将归一化后的 Phase3 records 投影为长度、归属和对话元数据。
    """
    speaker_lengths: dict[str, int] = {}
    canonical_attribution: dict[int, list[str]] = {}
    dialogues: list[tuple[int, str]] = []
    dialogue_tones: dict[int, str] = {}
    dialogue_identity_clues: dict[int, str | None] = {}
    seen_indices: set[int] = set()

    candidate_map = {c.index: c.content for c in candidates}
    for record in records:
        if record.index in seen_indices:
            logger.warning(f"compute_dialogue_lengths_with_llm: duplicate index={record.index}, skipping duplicate")
            continue
        seen_indices.add(record.index)

        if not record.is_dialogue:
            continue

        content = (candidate_map.get(record.index) or "").strip()
        if not content:
            content = (record.content or "").strip()
        if not content:
            continue

        dialogues.append((record.index, content))

        if record.tone and return_tones:
            dialogue_tones[record.index] = record.tone

        if record.identity_clue and return_identity_clues:
            dialogue_identity_clues[record.index] = record.identity_clue

        if record.speaker and record.speaker != ["未知"]:
            for speaker in record.speaker:
                speaker_lengths[speaker] = speaker_lengths.get(speaker, 0) + len(content)
            canonical_attribution[record.index] = record.speaker

    return DialogueLengthResult(
        speaker_lengths=speaker_lengths,
        canonical_attribution=canonical_attribution,
        dialogues=dialogues,
        dialogue_tones=dialogue_tones,
        dialogue_identity_clues=dialogue_identity_clues,
    )


def build_dialogue_snapshots(
    dialogues: list[tuple[int, str]] | None,
    dialogue_speakers: dict[int, list[str]] | None = None,
    dialogue_tones: dict[int, str] | None = None,
    dialogue_identity_clues: dict[int, str | None] | None = None,
) -> tuple[list[DialogueSnapshot], list[int]]:
    """
    将 Phase3 投影结果转换为可落库的 DialogueSnapshot 列表。
    """
    if not dialogues:
        return [], []

    snapshots: list[DialogueSnapshot] = []
    lengths: list[int] = []
    for dialogue_idx, content in dialogues:
        speaker_list = dialogue_speakers.get(dialogue_idx) if dialogue_speakers else None
        tone = dialogue_tones.get(dialogue_idx) if dialogue_tones else None
        identity_clue = dialogue_identity_clues.get(dialogue_idx) if dialogue_identity_clues else None
        snapshots.append(
            DialogueSnapshot(
                speaker=speaker_list,
                content=content,
                tone=tone,
                identity_clue=identity_clue,
            )
        )
        lengths.append(len(content))
    return snapshots, lengths
