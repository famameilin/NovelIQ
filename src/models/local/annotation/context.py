"""
说明: 标注上下文数据类和异常定义
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient
    from src.models.local.schema import ChunkAnnotation, ForeshadowingResult, RelationChangeSnapshot
    from src.rag import EvidenceBundle, EvidenceRequest, NarrativeEvidenceService


@dataclass
class AnnotationContext:
    """
    标注上下文参数

    说明: 封装annotate_chunk的多参数，减少函数签名复杂度
    """

    text: str
    prev_summary: str | None = None
    alias_map: dict[str, str] | None = None
    chunk_id: int | None = None
    global_context: str | None = None
    active_entities: str | None = None
    disambig_context: str | None = None
    phase1_bundle: EvidenceBundle | None = None
    phase2_bundle: EvidenceBundle | None = None
    phase3_bundle: EvidenceBundle | None = None
    phase4_bundle: EvidenceBundle | None = None
    phase4_request_template: EvidenceRequest | None = None
    evidence_service: NarrativeEvidenceService | None = None
    novel_title: str | None = None
    main_characters: str | None = None
    position_pct: float | None = None
    chapter_id: int | None = None
    fallback_client: AnnotationClient | None = None
    run_id: str | None = None


class Phase1MaxRetriesExceededError(Exception):
    """
    Phase1重试次数耗尽异常
    """

    pass


class NameValidationMaxRetriesExceededError(Exception):
    """
    名字验证重试次数耗尽异常
    """

    def __init__(
        self,
        message: str,
        invalid_names: list[str] | None = None,
        bad_output: str = "",
        validation_details: dict[str, list[str]] | None = None,
    ):
        super().__init__(message)
        self.invalid_names = invalid_names
        self.bad_output = bad_output
        self.validation_details = validation_details or {}


class Phase2MaxRetriesExceededError(Exception):
    """
    Phase2重试次数耗尽异常
    """

    pass


class DialogueAttributionError(Exception):
    """
    对话归属失败异常

    说明: 当 LLM 无法正确归属对话说话者时抛出此异常
    """

    pass


@dataclass
class MultiPhaseAnnotationResult:
    """
    多阶段标注结果
    """

    annotation: ChunkAnnotation
    foreshadowing: ForeshadowingResult | None = None
    dialogue_lengths: dict[str, int] | None = None
    dialogue_speakers: dict[int, list[str]] | None = None
    dialogues: list[tuple[int, str]] | None = None
    dialogue_tones: dict[int, str] | None = None
    dialogue_identity_clues: dict[int, str | None] | None = None
    relations: list[RelationChangeSnapshot] | None = None
