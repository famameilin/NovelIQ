"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: 标注上下文数据类和异常定义
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from src.models.local.annotation_client import AnnotationClient
    from src.models.local.schema import ChunkAnnotation, ForeshadowingResult


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

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-validate-names-from-character-appearances
    修改内容: 添加 character_appearances 字段
    """

    text: str
    prev_summary: str | None = None
    alias_map: Dict[str, str] | None = None
    chunk_id: int | None = None
    global_context: str | None = None
    prev_chunk_text: str | None = None
    active_entities: str | None = None
    rag_evidence: str | None = None
    known_aliases: str | None = None
    next_chunk_text: str | None = None
    novel_title: str | None = None
    main_characters: str | None = None
    position_pct: float | None = None
    chapter_id: int | None = None
    cloud_client: "AnnotationClient | None" = None
    run_id: str | None = None
    character_appearances: List[dict] | None = None


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

    def __init__(self, message: str, invalid_names: list[str] | None = None, bad_output: str = ""):
        super().__init__(message)
        self.invalid_names = invalid_names
        self.bad_output = bad_output


class Phase2MaxRetriesExceededError(Exception):
    """
    Phase2重试次数耗尽异常

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    """

    pass


@dataclass
class TwoPhaseAnnotationResult:
    """
    双阶段标注结果

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    """

    annotation: "ChunkAnnotation"
    foreshadowing: "ForeshadowingResult | None" = None


PHASE_MAX_RETRIES = 3
