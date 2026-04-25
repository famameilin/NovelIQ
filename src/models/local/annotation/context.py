"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: 标注上下文数据类和异常定义

修改时间: 2026-03-28
修改者: TraeAI
任务: consolidate-codebase-architecture
修改内容: 从 constants 导入 PHASE_MAX_RETRIES，移除本地重复定义

修改时间: 2026-03-29
修改者: TraeAI
任务: remove-unused-annotation-fields
修改内容: 移除 character_appearances 字段
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient
    from src.models.local.schema import ChunkAnnotation, ForeshadowingResult, RelationChangeSnapshot
    from src.rag import EvidenceBundle, Level3Request, NarrativeEvidenceService


@dataclass
class AnnotationContext:
    """
    标注上下文参数

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 简化annotate_chunk参数
    说明: 封装annotate_chunk的多参数，减少函数签名复杂度

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 统一字段命名，添加 run_id 支持
    修改内容: 移除 prev_tail_text 和 next_preview，统一使用 prev_chunk_text 和 next_chunk_text，添加 run_id

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: remove-unused-annotation-fields
    修改内容: 移除 character_appearances 字段

    修改时间: 2026-04-25
    修改者: Codex
    任务: level3-intent-phase-split
    修改内容: 改为显式 phase-scoped bundles，并允许多阶段标注在 Phase4 运行前按 request 模板补取证据。
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
    phase4_request_template: Level3Request | None = None
    evidence_provider: NarrativeEvidenceService | None = None
    novel_title: str | None = None
    main_characters: str | None = None
    position_pct: float | None = None
    chapter_id: int | None = None
    fallback_client: AnnotationClient | None = None
    run_id: str | None = None


class Phase1MaxRetriesExceededError(Exception):
    """
    Phase1重试次数耗尽异常

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    """

    pass


class NameValidationMaxRetriesExceededError(Exception):
    """
    名字验证重试次数耗尽异常

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 添加 invalid_names 和 bad_output 属性
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

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    """

    pass


class DialogueAttributionError(Exception):
    """
    对话归属失败异常

    创建时间: 2026-03-22
    创建者: TraeAI
    任务: code-quality-review
    说明: 当 LLM 无法正确归属对话说话者时抛出此异常
    """

    pass


@dataclass
class MultiPhaseAnnotationResult:
    """
    多阶段标注结果

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: rename-two-phase-to-multi-phase
    修改内容: 重命名为 MultiPhaseAnnotationResult 以支持多阶段架构

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: phase3-return-speaker-to-storage
    修改内容: 添加 dialogue_speakers 字段存储 phase3 判断的说话者

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: phase3-return-dialogues-to-storage
    修改内容: 添加 dialogues 字段存储 phase3 提取的对话列表

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-tone-distribution-semantic-error
    修改内容: 添加 dialogue_tones 字段存储对话语气类型

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: fix-unknown-speaker-context
    修改内容: 添加 dialogue_evidences 字段存储对话判断依据

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: use-phase3-identity-clue-in-disambiguation
    修改内容: 添加 dialogue_identity_clues 字段存储身份线索

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: fix-multi-speaker-support
    修改内容: 删除 dialogue_evidences 字段
    """

    annotation: ChunkAnnotation
    foreshadowing: ForeshadowingResult | None = None
    dialogue_lengths: dict[str, int] | None = None
    dialogue_speakers: dict[int, list[str]] | None = None
    dialogues: list[tuple[int, str]] | None = None
    dialogue_tones: dict[int, str] | None = None
    dialogue_identity_clues: dict[int, str | None] | None = None
    relations: list[RelationChangeSnapshot] | None = None
