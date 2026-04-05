"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: 多阶段标注逻辑（并行和串行模式）

修改时间: 2026-03-22
修改者: TraeAI
任务: rename-two-phase-to-multi-phase
修改内容: 重命名为 multi_phase 模块，annotate_chunk_two_phase 改为 annotate_chunk_multi_phase

修改时间: 2026-03-22
修改者: TraeAI
任务: parallel-three-phase
修改内容: 并行模式扩展为三阶段并行（Phase1+Phase2并行，Phase3在Phase1后执行）

修改时间: 2026-03-27
修改者: TraeAI
任务: refactor-multi-phase-extract-private-functions
修改内容: 提取私有函数减少重复代码，简化主函数为调度函数

修改时间: 2026-03-29
修改者: TraeAI
任务: remove-unused-annotation-fields
修改内容: 移除 character_appearances 参数
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.config import settings
from src.models.local.parser import validate_foreshadowing_result

from .context import MultiPhaseAnnotationResult
from .phase1 import annotate_chunk_phase1
from .phase2 import annotate_chunk_phase2
from .phase3 import compute_dialogue_lengths_with_llm, extract_dialogues_from_text
from .phase4 import annotate_chunk_phase4

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient
    from src.models.local.schema import ChunkAnnotation, ForeshadowingResult


@dataclass
class _Phase3Result:
    """Phase3 执行结果

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: refactor-multi-phase-extract-private-functions

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: fix-unknown-speaker-context
    修改内容: 添加 dialogue_evidences 字段存储对话判断依据

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: use-phase3-identity-clue-in-disambiguation
    修改内容: 添加 dialogue_identity_clues 字段存储身份线索
    """

    dialogue_lengths: dict[str, int] | None = None
    dialogue_speakers: dict[int, str] | None = None
    dialogues: list[tuple[int, str]] | None = None
    dialogue_tones: dict[int, str] | None = None
    dialogue_evidences: dict[int, str] | None = None
    dialogue_identity_clues: dict[int, str | None] | None = None


@dataclass
class _Phase4Result:
    relations: list | None = None


def _run_phase1(
    client: AnnotationClient,
    text: str,
    alias_map: dict[str, str] | None,
    chunk_id: int | None,
    novel_title: str | None,
    main_characters: str | None,
    position_pct: float | None,
    chapter_id: int | None,
    active_entities: str | None,
    cloud_client: AnnotationClient | None,
    run_id: str | None,
) -> ChunkAnnotation:
    """执行 Phase1 基础标注

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: refactor-multi-phase-extract-private-functions

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: simplify-phase1-prompt
    修改内容: 移除 prev_chunk_text 和 next_chunk_text 参数
    """
    return annotate_chunk_phase1(
        client=client,
        text=text,
        alias_map=alias_map,
        chunk_id=chunk_id,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        active_entities=active_entities,
        cloud_client=cloud_client,
        run_id=run_id,
    )


def _run_phase2(
    client: AnnotationClient,
    text: str,
    chunk_id: int | None,
    prev_chunk_text: str | None,
    next_chunk_text: str | None,
    novel_title: str | None,
    main_characters: str | None,
    position_pct: float | None,
    chapter_id: int | None,
    cloud_client: AnnotationClient | None,
    run_id: str | None,
    rag_retriever: Any | None,
) -> ForeshadowingResult | None:
    """执行 Phase2 伏笔分析

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: refactor-multi-phase-extract-private-functions
    """
    return annotate_chunk_phase2(
        client=client,
        text=text,
        chunk_id=chunk_id,
        prev_chunk_text=prev_chunk_text,
        next_chunk_text=next_chunk_text,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        cloud_client=cloud_client,
        run_id=run_id,
        rag_retriever=rag_retriever,
    )


def _run_phase3_if_needed(
    client: AnnotationClient,
    text: str,
    alias_map: dict[str, str] | None,
    chunk_id: int | None,
    run_id: str | None,
    known_characters: list[str] | None,
) -> _Phase3Result:
    """根据条件执行 Phase3 对话归属判断

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: refactor-multi-phase-extract-private-functions

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: fix-unknown-speaker-context
    修改内容: 启用 return_evidences=True 返回对话判断依据

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: use-phase3-identity-clue-in-disambiguation
    修改内容: 启用 return_identity_clues=True 返回身份线索
    """
    result = _Phase3Result()

    extracted_dialogues = extract_dialogues_from_text(text)
    if not extracted_dialogues:
        return result

    logger.debug(
        "Phase3: text_has_dialogues=True count={} chunk_id={}",
        len(extracted_dialogues),
        chunk_id,
    )

    result_tuple = compute_dialogue_lengths_with_llm(
        client=client,
        text=text,
        alias_map=alias_map,
        chunk_id=chunk_id,
        run_id=run_id,
        known_characters=known_characters,
        return_tones=True,
        return_evidences=True,
        return_identity_clues=True,
    )

    result.dialogue_lengths = result_tuple[0]
    result.dialogue_speakers = result_tuple[1]
    result.dialogues = result_tuple[2]
    result.dialogue_tones = result_tuple[3] if len(result_tuple) > 3 else None
    result.dialogue_evidences = result_tuple[4] if len(result_tuple) > 4 else None
    result.dialogue_identity_clues = result_tuple[5] if len(result_tuple) > 5 else None

    logger.debug(
        "Phase3: dialogue_lengths={} dialogue_speakers={} "
        "dialogues={} dialogue_tones={} dialogue_evidences={} chunk_id={}",
        result.dialogue_lengths,
        result.dialogue_speakers,
        result.dialogues,
        result.dialogue_tones,
        result.dialogue_evidences,
        chunk_id,
    )

    return result


def _normalize_foreshadowing_result(
    foreshadowing: ForeshadowingResult | None,
    text: str,
    chunk_id: int | None,
) -> ForeshadowingResult | None:
    """归一化伏笔结果，校验失败则返回 None

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: refactor-multi-phase-extract-private-functions
    """
    if not foreshadowing:
        return None

    if not validate_foreshadowing_result(foreshadowing, text):
        return None

    logger.debug(
        "Foreshadowing found chunk_id={} type={}",
        chunk_id,
        foreshadowing.foreshadowing_type,
    )
    return foreshadowing


def _build_multi_phase_result(
    annotation: ChunkAnnotation,
    foreshadowing: ForeshadowingResult | None,
    phase3_result: _Phase3Result,
    phase4_result: _Phase4Result,
) -> MultiPhaseAnnotationResult:
    """构建多阶段标注结果

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: refactor-multi-phase-extract-private-functions

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: fix-unknown-speaker-context
    修改内容: 添加 dialogue_evidences 字段

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: use-phase3-identity-clue-in-disambiguation
    修改内容: 添加 dialogue_identity_clues 字段
    """
    return MultiPhaseAnnotationResult(
        annotation=annotation,
        foreshadowing=foreshadowing,
        dialogue_lengths=phase3_result.dialogue_lengths,
        dialogue_speakers=phase3_result.dialogue_speakers,
        dialogues=phase3_result.dialogues,
        dialogue_tones=phase3_result.dialogue_tones,
        dialogue_evidences=phase3_result.dialogue_evidences,
        dialogue_identity_clues=phase3_result.dialogue_identity_clues,
        relations=phase4_result.relations,
    )


def annotate_chunk_multi_phase(
    client: AnnotationClient,
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
    cloud_client: AnnotationClient | None = None,
    run_id: str | None = None,
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

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: rename-two-phase-to-multi-phase
    修改内容: 重命名为 annotate_chunk_multi_phase

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: remove-unused-annotation-fields
    修改内容: 移除 character_appearances 参数

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: simplify-phase1-prompt
    修改内容: Phase1 不再使用 prev_chunk_text 和 next_chunk_text，仅 Phase2 使用
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
            cloud_client=cloud_client,
            run_id=run_id,
            rag_retriever=rag_retriever,
            active_entities=active_entities,
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
            cloud_client=cloud_client,
            run_id=run_id,
            rag_retriever=rag_retriever,
            active_entities=active_entities,
        )


def annotate_chunk_parallel(
    client: AnnotationClient,
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
    cloud_client: AnnotationClient | None = None,
    run_id: str | None = None,
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

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: parallel-three-phase
    修改内容: 扩展为三阶段并行：Phase1+Phase2 并行，Phase3 在 Phase1 完成后执行

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: refactor-multi-phase-extract-private-functions
    修改内容: 提取私有函数，简化为调度函数

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: remove-unused-annotation-fields
    修改内容: 移除 character_appearances 参数

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: simplify-phase1-prompt
    修改内容: Phase1 不再使用 prev_chunk_text 和 next_chunk_text
    """
    logger.debug("annotate_chunk_parallel start chunk_id={}", chunk_id)

    with ThreadPoolExecutor(max_workers=3) as executor:
        phase1_future = executor.submit(
            _run_phase1,
            client=client,
            text=text,
            alias_map=alias_map,
            chunk_id=chunk_id,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            active_entities=active_entities,
            cloud_client=cloud_client,
            run_id=run_id,
        )
        phase2_future = executor.submit(
            _run_phase2,
            client=client,
            text=text,
            chunk_id=chunk_id,
            prev_chunk_text=prev_chunk_text,
            next_chunk_text=next_chunk_text,
            novel_title=novel_title,
            main_characters=main_characters,
            position_pct=position_pct,
            chapter_id=chapter_id,
            cloud_client=cloud_client,
            run_id=run_id,
            rag_retriever=rag_retriever,
        )

        annotation = phase1_future.result()
        foreshadowing = phase2_future.result()

        known_characters = [c.name for c in annotation.characters] if annotation.characters else None
        phase3_result = _run_phase3_if_needed(
            client=client,
            text=text,
            alias_map=alias_map,
            chunk_id=chunk_id,
            run_id=run_id,
            known_characters=known_characters,
        )
        phase4_result = _Phase4Result(
            relations=annotate_chunk_phase4(
                client=client,
                text=text,
                known_characters=known_characters,
                chunk_id=chunk_id,
                run_id=run_id,
            )
        )

    normalized_foreshadowing = _normalize_foreshadowing_result(
        foreshadowing=foreshadowing,
        text=text,
        chunk_id=chunk_id,
    )

    logger.debug("annotate_chunk_parallel complete chunk_id={}", chunk_id)

    return _build_multi_phase_result(
        annotation=annotation,
        foreshadowing=normalized_foreshadowing,
        phase3_result=phase3_result,
        phase4_result=phase4_result,
    )


def annotate_chunk_serial(
    client: AnnotationClient,
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
    cloud_client: AnnotationClient | None = None,
    run_id: str | None = None,
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

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: refactor-multi-phase-extract-private-functions
    修改内容: 提取私有函数，简化为调度函数

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: remove-unused-annotation-fields
    修改内容: 移除 character_appearances 参数
    """
    logger.debug("annotate_chunk_serial start chunk_id={}", chunk_id)

    annotation = _run_phase1(
        client=client,
        text=text,
        alias_map=alias_map,
        chunk_id=chunk_id,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        active_entities=active_entities,
        cloud_client=cloud_client,
        run_id=run_id,
    )

    foreshadowing = _run_phase2(
        client=client,
        text=text,
        chunk_id=chunk_id,
        prev_chunk_text=prev_chunk_text,
        next_chunk_text=next_chunk_text,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        cloud_client=cloud_client,
        run_id=run_id,
        rag_retriever=rag_retriever,
    )

    normalized_foreshadowing = _normalize_foreshadowing_result(
        foreshadowing=foreshadowing,
        text=text,
        chunk_id=chunk_id,
    )

    known_characters = [c.name for c in annotation.characters] if annotation.characters else None
    phase3_result = _run_phase3_if_needed(
        client=client,
        text=text,
        alias_map=alias_map,
        chunk_id=chunk_id,
        run_id=run_id,
        known_characters=known_characters,
    )
    phase4_result = _Phase4Result(
        relations=annotate_chunk_phase4(
            client=client,
            text=text,
            known_characters=known_characters,
            chunk_id=chunk_id,
            run_id=run_id,
        )
    )

    logger.debug("annotate_chunk_serial complete chunk_id={}", chunk_id)

    return _build_multi_phase_result(
        annotation=annotation,
        foreshadowing=normalized_foreshadowing,
        phase3_result=phase3_result,
        phase4_result=phase4_result,
    )
