"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: 双阶段标注逻辑（并行和串行模式）
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Dict

from loguru import logger

from src.config import settings
from src.models.local.parser import validate_foreshadowing_result

from .context import TwoPhaseAnnotationResult
from .phase1 import annotate_chunk_phase1
from .phase2 import annotate_chunk_phase2

if TYPE_CHECKING:
    from src.models.local.annotation_client import AnnotationClient


def annotate_chunk_two_phase(
    client: "AnnotationClient",
    text: str,
    prev_summary: str | None = None,
    alias_map: Dict[str, str] | None = None,
    chunk_id: int | None = None,
    global_context: str | None = None,
    prev_chunk_text: str | None = None,
    active_entities: str | None = None,
    rag_evidence: str | None = None,
    known_aliases: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    cloud_client: "AnnotationClient | None" = None,
    run_id: str | None = None,
) -> TwoPhaseAnnotationResult:
    """
    双次调用标注模式

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 统一字段命名，使用 prev_chunk_text 和 next_chunk_text，添加 run_id 支持
    """
    parallel = settings.analysis.two_phase_annotation.parallel

    if parallel:
        return annotate_chunk_two_phase_parallel(
            client=client,
            text=text,
            alias_map=alias_map,
            chunk_id=chunk_id,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            active_entities=active_entities,
            cloud_client=cloud_client,
            run_id=run_id,
        )
    else:
        return annotate_chunk_two_phase_serial(
            client=client,
            text=text,
            alias_map=alias_map,
            chunk_id=chunk_id,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            active_entities=active_entities,
            cloud_client=cloud_client,
            run_id=run_id,
        )


def annotate_chunk_two_phase_parallel(
    client: "AnnotationClient",
    text: str,
    alias_map: Dict[str, str] | None = None,
    chunk_id: int | None = None,
    prev_chunk_text: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    active_entities: str | None = None,
    cloud_client: "AnnotationClient | None" = None,
    run_id: str | None = None,
) -> TwoPhaseAnnotationResult:
    """
    并行双次调用模式

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: Phase1/Phase2独立重试机制
    修改内容: 添加 cloud_client 参数传递

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 添加 run_id 支持
    修改内容: 添加 run_id 参数传递
    """
    logger.debug("annotate_chunk_two_phase_parallel start chunk_id={}", chunk_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        phase1_future = executor.submit(
            annotate_chunk_phase1,
            client=client,
            text=text,
            alias_map=alias_map,
            chunk_id=chunk_id,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            active_entities=active_entities,
            cloud_client=cloud_client,
            run_id=run_id,
        )
        phase2_future = executor.submit(
            annotate_chunk_phase2,
            client=client,
            text=text,
            prev_chunk_summary=None,
            chunk_id=chunk_id,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            cloud_client=cloud_client,
            run_id=run_id,
        )

        annotation = phase1_future.result()
        foreshadowing = phase2_future.result()

    if foreshadowing and validate_foreshadowing_result(foreshadowing, text):
        logger.debug(
            "annotate_chunk_two_phase_parallel found foreshadowing chunk_id={} type={}",
            chunk_id,
            foreshadowing.foreshadowing_type,
        )
    else:
        foreshadowing = None

    logger.debug("annotate_chunk_two_phase_parallel complete chunk_id={}", chunk_id)
    return TwoPhaseAnnotationResult(annotation=annotation, foreshadowing=foreshadowing)


def annotate_chunk_two_phase_serial(
    client: "AnnotationClient",
    text: str,
    alias_map: Dict[str, str] | None = None,
    chunk_id: int | None = None,
    prev_chunk_text: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    active_entities: str | None = None,
    cloud_client: "AnnotationClient | None" = None,
    run_id: str | None = None,
) -> TwoPhaseAnnotationResult:
    """
    串行双次调用模式

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: Phase1/Phase2独立重试机制
    修改内容: 添加 cloud_client 参数传递

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 添加 run_id 支持
    修改内容: 添加 run_id 参数传递
    """
    logger.debug("annotate_chunk_two_phase_serial start chunk_id={}", chunk_id)

    annotation = annotate_chunk_phase1(
        client=client,
        text=text,
        alias_map=alias_map,
        chunk_id=chunk_id,
        prev_chunk_text=prev_chunk_text,
        next_chunk_text=next_chunk_text,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        active_entities=active_entities,
        cloud_client=cloud_client,
        run_id=run_id,
    )

    foreshadowing = annotate_chunk_phase2(
        client=client,
        text=text,
        prev_chunk_summary=annotation.chunk_summary,
        chunk_id=chunk_id,
        prev_chunk_text=prev_chunk_text,
        next_chunk_text=next_chunk_text,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        cloud_client=cloud_client,
        run_id=run_id,
    )

    if foreshadowing and validate_foreshadowing_result(foreshadowing, text):
        logger.debug(
            "annotate_chunk_two_phase_serial found foreshadowing chunk_id={} type={}",
            chunk_id,
            foreshadowing.foreshadowing_type,
        )
    else:
        foreshadowing = None

    logger.debug("annotate_chunk_two_phase_serial complete chunk_id={}", chunk_id)
    return TwoPhaseAnnotationResult(annotation=annotation, foreshadowing=foreshadowing)
