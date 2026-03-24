"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: 多阶段标注逻辑（并行和串行模式）

修改时间: 2026-03-21
修改者: TraeAI
任务: fix-validate-names-from-character-appearances
修改内容: 添加 character_appearances 参数支持

修改时间: 2026-03-22
修改者: TraeAI
任务: rename-two-phase-to-multi-phase
修改内容: 重命名为 multi_phase 模块，annotate_chunk_two_phase 改为 annotate_chunk_multi_phase

修改时间: 2026-03-22
修改者: TraeAI
任务: parallel-three-phase
修改内容: 并行模式扩展为三阶段并行（Phase1+Phase2并行，Phase3在Phase1后执行）
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.config import settings
from src.models.local.parser import validate_foreshadowing_result

from .context import MultiPhaseAnnotationResult
from .phase1 import annotate_chunk_phase1
from .phase2 import annotate_chunk_phase2
from .phase3 import compute_dialogue_lengths_with_llm, extract_dialogues_from_text

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient
    from src.models.local.unified_client import UnifiedModelClient


def _get_annotation_client(client: AnnotationClient | UnifiedModelClient) -> AnnotationClient:
    """从 UnifiedModelClient 或直接返回 AnnotationClient"""
    if hasattr(client, "_annotation_client"):
        return client._annotation_client
    return client


def _get_unified_client(client: AnnotationClient | UnifiedModelClient) -> UnifiedModelClient | AnnotationClient:
    """如果输入是 AnnotationClient，直接返回；如果是 UnifiedModelClient 也返回自身"""
    return client


def annotate_chunk_multi_phase(
    client: AnnotationClient | UnifiedModelClient,
    text: str,
    prev_summary: str | None = None,
    alias_map: dict[str, str] | None = None,
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
    cloud_client: AnnotationClient | UnifiedModelClient | None = None,
    run_id: str | None = None,
    character_appearances: list[dict] | None = None,
    rag_retriever: Any | None = None,
) -> MultiPhaseAnnotationResult:
    """
    多阶段标注模式

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 统一字段命名，使用 prev_chunk_text 和 next_chunk_text，添加 run_id 支持

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-validate-names-from-character-appearances
    修改内容: 添加 character_appearances 参数支持

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: rename-two-phase-to-multi-phase
    修改内容: 重命名为 annotate_chunk_multi_phase
    """
    parallel = settings.analysis.multi_phase_annotation.parallel

    if parallel:
        return annotate_chunk_parallel(
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
            character_appearances=character_appearances,
            rag_retriever=rag_retriever,
        )
    else:
        return annotate_chunk_serial(
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
            character_appearances=character_appearances,
            rag_retriever=rag_retriever,
        )


def annotate_chunk_parallel(
    client: AnnotationClient | UnifiedModelClient,
    text: str,
    alias_map: dict[str, str] | None = None,
    chunk_id: int | None = None,
    prev_chunk_text: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    active_entities: str | None = None,
    cloud_client: AnnotationClient | UnifiedModelClient | None = None,
    run_id: str | None = None,
    character_appearances: list[dict] | None = None,
    rag_retriever: Any | None = None,
) -> MultiPhaseAnnotationResult:
    """
    并行模式：Phase1 和 Phase2 并行执行，Phase3 在 Phase1 完成后执行

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

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-validate-names-from-character-appearances
    修改内容: 添加 character_appearances 参数传递

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: parallel-three-phase
    修改内容: 扩展为三阶段并行：Phase1+Phase2 并行，Phase3 在 Phase1 完成后执行
    """
    logger.debug("annotate_chunk_parallel start chunk_id={}", chunk_id)

    annotation_client = _get_annotation_client(client)
    cloud_annotation_client = _get_annotation_client(cloud_client) if cloud_client else None
    unified_client = _get_unified_client(client)

    with ThreadPoolExecutor(max_workers=3) as executor:
        phase1_future = executor.submit(
            annotate_chunk_phase1,
            client=annotation_client,
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
            cloud_client=cloud_annotation_client,
            run_id=run_id,
            character_appearances=character_appearances,
        )
        phase2_future = executor.submit(
            annotate_chunk_phase2,
            client=annotation_client,
            text=text,
            chunk_id=chunk_id,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            cloud_client=cloud_annotation_client,
            run_id=run_id,
            rag_retriever=rag_retriever,
        )

        annotation = phase1_future.result()
        foreshadowing = phase2_future.result()

        dialogue_lengths = None
        dialogue_speakers = None
        dialogues = None
        extracted_dialogues = extract_dialogues_from_text(text)
        if extracted_dialogues:
            logger.debug("annotate_chunk_parallel: phase3 text_has_dialogues=True count={} chunk_id={}", len(extracted_dialogues), chunk_id)
            known_characters = [c.name for c in annotation.characters] if annotation.characters else None
            speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(
                client=unified_client,
                text=text,
                alias_map=alias_map,
                chunk_id=chunk_id,
                run_id=run_id,
                known_characters=known_characters,
            )
            dialogue_lengths = speaker_lengths
            dialogue_speakers = attribution
            logger.debug("annotate_chunk_parallel: phase3 dialogue_lengths={} dialogue_speakers={} dialogues={} chunk_id={}", dialogue_lengths, dialogue_speakers, dialogues, chunk_id)

    if foreshadowing and validate_foreshadowing_result(foreshadowing, text):
        logger.debug(
            "annotate_chunk_parallel found foreshadowing chunk_id={} type={}",
            chunk_id,
            foreshadowing.foreshadowing_type,
        )
    else:
        foreshadowing = None

    logger.debug("annotate_chunk_parallel complete chunk_id={}", chunk_id)
    return MultiPhaseAnnotationResult(annotation=annotation, foreshadowing=foreshadowing, dialogue_lengths=dialogue_lengths, dialogue_speakers=dialogue_speakers, dialogues=dialogues)


def annotate_chunk_serial(
    client: AnnotationClient | UnifiedModelClient,
    text: str,
    alias_map: dict[str, str] | None = None,
    chunk_id: int | None = None,
    prev_chunk_text: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    active_entities: str | None = None,
    cloud_client: AnnotationClient | UnifiedModelClient | None = None,
    run_id: str | None = None,
    character_appearances: list[dict] | None = None,
    rag_retriever: Any | None = None,
) -> MultiPhaseAnnotationResult:
    """
    串行模式

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

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-validate-names-from-character-appearances
    修改内容: 添加 character_appearances 参数传递
    """
    logger.debug("annotate_chunk_serial start chunk_id={}", chunk_id)

    annotation_client = _get_annotation_client(client)
    cloud_annotation_client = _get_annotation_client(cloud_client) if cloud_client else None

    annotation = annotate_chunk_phase1(
        client=annotation_client,
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
        cloud_client=cloud_annotation_client,
        run_id=run_id,
        character_appearances=character_appearances,
    )

    foreshadowing = annotate_chunk_phase2(
        client=annotation_client,
        text=text,
        chunk_id=chunk_id,
        prev_chunk_text=prev_chunk_text,
        next_chunk_text=next_chunk_text,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        cloud_client=cloud_annotation_client,
        run_id=run_id,
        rag_retriever=rag_retriever,
    )

    if foreshadowing and validate_foreshadowing_result(foreshadowing, text):
        logger.debug(
            "annotate_chunk_serial found foreshadowing chunk_id={} type={}",
            chunk_id,
            foreshadowing.foreshadowing_type,
        )
    else:
        foreshadowing = None

    dialogue_lengths = None
    dialogue_speakers = None
    dialogues = None
    extracted_dialogues = extract_dialogues_from_text(text)
    if extracted_dialogues:
        logger.debug("annotate_chunk_serial: phase3 text_has_dialogues=True count={} chunk_id={}", len(extracted_dialogues), chunk_id)
        known_characters = [c.name for c in annotation.characters] if annotation.characters else None
        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(
            client=client,
            text=text,
            alias_map=alias_map,
            chunk_id=chunk_id,
            run_id=run_id,
            known_characters=known_characters,
        )
        dialogue_lengths = speaker_lengths
        dialogue_speakers = attribution
        logger.debug("annotate_chunk_serial: phase3 dialogue_lengths={} dialogue_speakers={} dialogues={} chunk_id={}", dialogue_lengths, dialogue_speakers, dialogues, chunk_id)

    logger.debug("annotate_chunk_serial complete chunk_id={}", chunk_id)
    return MultiPhaseAnnotationResult(annotation=annotation, foreshadowing=foreshadowing, dialogue_lengths=dialogue_lengths, dialogue_speakers=dialogue_speakers, dialogues=dialogues)
