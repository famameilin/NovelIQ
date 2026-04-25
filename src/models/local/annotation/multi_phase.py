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

修改时间: 2026-04-17
修改者: TraeAI
任务: fix-phase3-active-entities-fallback
修改内容: _run_phase3_if_needed 新增 active_entities 参数，透传上游活跃实体上下文（含 fallback）

修改时间: 2026-04-23
修改者: Codex
任务: p2-multi-phase-shared-context
修改内容: 抽出并行/串行共享的 phase 事件发送与参数透传逻辑，减少两条执行路径重复代码

修改时间: 2026-04-23
任务: annotation-projector-runtime-landing
修改内容: Phase2 伏笔结果归一化委托 foreshadowing projector，调度层不再承担输出投影。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from loguru import logger

from src.api.models.events import StreamEvent
from src.config import settings

from .context import MultiPhaseAnnotationResult
from .phase1 import annotate_chunk_phase1
from .phase2 import annotate_chunk_phase2
from .phase3 import compute_dialogue_lengths_with_llm, extract_dialogues_from_text
from .phase4 import annotate_chunk_phase4
from .projectors.foreshadowing import normalize_foreshadowing_result as project_foreshadowing_result

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient
    from src.models.local.schema import ChunkAnnotation, ForeshadowingResult, RelationChangeSnapshot
    from src.rag import EvidenceRequest, NarrativeEvidenceService
    from src.rag.evidence_types import EvidenceBundle

PhaseEventAction = Literal["start", "progress", "complete", "output", "thinking"]


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

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: fix-multi-speaker-support
    修改内容: 删除 dialogue_evidences 字段
    """

    dialogue_lengths: dict[str, int] | None = None
    dialogue_speakers: dict[int, list[str]] | None = None
    dialogues: list[tuple[int, str]] | None = None
    dialogue_tones: dict[int, str] | None = None
    dialogue_identity_clues: dict[int, str | None] | None = None


@dataclass
class _Phase4Result:
    relations: list[RelationChangeSnapshot] | None = None


@dataclass(frozen=True)
class _MultiPhaseExecutionContext:
    """
    多阶段标注共享执行上下文。

    创建时间: 2026-04-23
    任务: p2-multi-phase-shared-context
    新建原因: 将并行/串行路径重复透传的 phase 参数集中管理，避免两侧调用签名漂移。
    """

    client: AnnotationClient
    text: str
    alias_map: dict[str, str] | None = None
    chunk_id: int | None = None
    prev_chunk_text: str | None = None
    next_chunk_text: str | None = None
    novel_title: str | None = None
    main_characters: str | None = None
    position_pct: float | None = None
    chapter_id: int | None = None
    active_entities: str | None = None
    phase1_bundle: EvidenceBundle | None = None
    phase2_bundle: EvidenceBundle | None = None
    phase3_bundle: EvidenceBundle | None = None
    phase4_bundle: EvidenceBundle | None = None
    phase4_request_template: EvidenceRequest | None = None
    evidence_service: NarrativeEvidenceService | None = None
    fallback_client: AnnotationClient | None = None
    run_id: str | None = None
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None
    disambig_context: str | None = None


async def _emit_phase_event(
    context: _MultiPhaseExecutionContext,
    *,
    action: PhaseEventAction,
    phase_name: str,
    sub_percent: int,
    message: str,
) -> None:
    """
    发送统一的 phase 事件。

    创建时间: 2026-04-23
    任务: p2-multi-phase-shared-context
    新建原因: 将 parallel/serial 中重复的 StreamEvent 构造逻辑收口到单一入口。
    """
    if context.emitter is None:
        return
    await context.emitter(
        StreamEvent(
            action=action,
            sub_stage=phase_name,
            chunk_id=context.chunk_id,
            sub_percent=sub_percent,
            message=message,
        )
    )


async def _run_phase1_from_context(context: _MultiPhaseExecutionContext) -> ChunkAnnotation:
    """
    从共享上下文执行 Phase1。

    创建时间: 2026-04-23
    任务: p2-multi-phase-shared-context
    新建原因: 统一 Phase1 参数透传，避免并行/串行路径分别维护同一套 kwargs。
    """
    return await _run_phase1(
        client=context.client,
        text=context.text,
        alias_map=context.alias_map,
        chunk_id=context.chunk_id,
        novel_title=context.novel_title,
        main_characters=context.main_characters,
        position_pct=context.position_pct,
        chapter_id=context.chapter_id,
        active_entities=context.active_entities,
        evidence_bundle=context.phase1_bundle,
        fallback_client=context.fallback_client,
        run_id=context.run_id,
        disambig_context=context.disambig_context,
    )


async def _run_phase2_from_context(context: _MultiPhaseExecutionContext) -> ForeshadowingResult | None:
    """
    从共享上下文执行 Phase2。

    创建时间: 2026-04-23
    任务: p2-multi-phase-shared-context
    新建原因: 统一 Phase2 参数透传，避免 chunk 前后文在 parallel/serial 中重复拼接。
    """
    return await _run_phase2(
        client=context.client,
        text=context.text,
        chunk_id=context.chunk_id,
        prev_chunk_text=context.prev_chunk_text,
        next_chunk_text=context.next_chunk_text,
        novel_title=context.novel_title,
        main_characters=context.main_characters,
        position_pct=context.position_pct,
        chapter_id=context.chapter_id,
        evidence_bundle=context.phase2_bundle,
        fallback_client=context.fallback_client,
        run_id=context.run_id,
    )


async def _run_phase3_from_context(
    context: _MultiPhaseExecutionContext,
    known_characters: list[str] | None,
) -> _Phase3Result:
    """
    从共享上下文执行 Phase3。

    创建时间: 2026-04-23
    任务: p2-multi-phase-shared-context
    新建原因: 锁定 Phase3 透传字段，避免 active_entities/fallback/evidence_bundle 在两条路径里走偏。
    """
    return await _run_phase3_if_needed(
        client=context.client,
        text=context.text,
        alias_map=context.alias_map,
        evidence_bundle=context.phase3_bundle,
        chunk_id=context.chunk_id,
        run_id=context.run_id,
        known_characters=known_characters,
        active_entities=context.active_entities,
        fallback_client=context.fallback_client,
    )


async def _run_phase4_from_context(
    context: _MultiPhaseExecutionContext,
    known_characters: list[str] | None,
) -> _Phase4Result:
    """
    从共享上下文执行 Phase4。

    创建时间: 2026-04-23
    任务: p2-multi-phase-shared-context
    新建原因: 统一 Phase4 的共享 evidence/fallback 透传，减少串并行路径重复实现。
    """
    phase4_bundle = await _resolve_phase4_bundle(context, known_characters)
    relations = await annotate_chunk_phase4(
        client=context.client,
        text=context.text,
        known_characters=known_characters,
        # 中文注释：Phase4 统一只消费上游传入的 evidence_bundle，
        # multi_phase 负责调度，不在这里重建关系抽取上下文。
        evidence_bundle=phase4_bundle,
        chunk_id=context.chunk_id,
        run_id=context.run_id,
        fallback_client=context.fallback_client,
    )
    return _Phase4Result(relations=relations)


async def _resolve_phase4_bundle(
    context: _MultiPhaseExecutionContext,
    known_characters: list[str] | None,
) -> EvidenceBundle | None:
    """
    创建时间: 2026-04-25
    修改时间: 2026-04-25
    任务: evidence-service-request-unification
    修改说明: Phase4 的 relation request 需要等 Phase1 产出 known_characters 后再补全 requested_names/seed_entities；
          这一步统一委托 evidence service，multi_phase 只负责调度。
    """
    if context.phase4_bundle is not None:
        return context.phase4_bundle
    if context.phase4_request_template is None or context.evidence_service is None:
        return None
    return await context.evidence_service.collect_annotation_phase4_bundle(
        context.phase4_request_template,
        known_characters,
    )


def _resolve_known_characters(annotation: ChunkAnnotation) -> list[str] | None:
    """
    从 Phase1 结果提取 canonical 角色名列表。

    创建时间: 2026-04-23
    任务: p2-multi-phase-shared-context
    新建原因: 将串并行公共的 known_characters 派生逻辑收口。
    """
    return [character.name for character in annotation.characters] if annotation.characters else None


def _normalize_phase_outputs(
    context: _MultiPhaseExecutionContext,
    annotation: ChunkAnnotation,
    foreshadowing: ForeshadowingResult | None,
) -> tuple[list[str] | None, ForeshadowingResult | None]:
    """
    归一化 Phase1/2 的共享派生产物。

    创建时间: 2026-04-23
    任务: p2-multi-phase-shared-context
    新建原因: 统一 known_characters 与伏笔校验的派生流程，减少 parallel/serial 的重复收尾代码。
    """
    known_characters = _resolve_known_characters(annotation)
    normalized_foreshadowing = _normalize_foreshadowing_result(
        foreshadowing=foreshadowing,
        text=context.text,
        chunk_id=context.chunk_id,
    )
    return known_characters, normalized_foreshadowing


async def _run_phase1(
    client: AnnotationClient,
    text: str,
    alias_map: dict[str, str] | None,
    chunk_id: int | None,
    novel_title: str | None,
    main_characters: str | None,
    position_pct: float | None,
    chapter_id: int | None,
    active_entities: str | None,
    evidence_bundle: EvidenceBundle | None,
    fallback_client: AnnotationClient | None,
    run_id: str | None,
    disambig_context: str | None = None,
) -> ChunkAnnotation:
    """执行 Phase1 基础标注

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: refactor-multi-phase-extract-private-functions

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def
    """
    return await annotate_chunk_phase1(
        client=client,
        text=text,
        alias_map=alias_map,
        chunk_id=chunk_id,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        active_entities=active_entities,
        evidence_bundle=evidence_bundle,
        fallback_client=fallback_client,
        run_id=run_id,
        disambig_context=disambig_context,
    )


async def _run_phase2(
    client: AnnotationClient,
    text: str,
    chunk_id: int | None,
    prev_chunk_text: str | None,
    next_chunk_text: str | None,
    novel_title: str | None,
    main_characters: str | None,
    position_pct: float | None,
    chapter_id: int | None,
    evidence_bundle: EvidenceBundle | None,
    fallback_client: AnnotationClient | None,
    run_id: str | None,
) -> ForeshadowingResult | None:
    """执行 Phase2 伏笔分析

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: refactor-multi-phase-extract-private-functions

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def
    """
    return await annotate_chunk_phase2(
        client=client,
        text=text,
        chunk_id=chunk_id,
        prev_chunk_text=prev_chunk_text,
        next_chunk_text=next_chunk_text,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        # 中文注释：优先透传上游已准备好的 evidence bundle，
        # 保证 AnnotationClient -> multi_phase -> Phase2 的真实入口也能复用同一份证据上下文。
        evidence_bundle=evidence_bundle,
        fallback_client=fallback_client,
        run_id=run_id,
    )


async def _run_phase3_if_needed(
    client: AnnotationClient,
    text: str,
    alias_map: dict[str, str] | None,
    evidence_bundle: EvidenceBundle | None,
    chunk_id: int | None,
    run_id: str | None,
    known_characters: list[str] | None,
    active_entities: str | None = None,
    fallback_client: AnnotationClient | None = None,
) -> _Phase3Result:
    """根据条件执行 Phase3 对话归属判断

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: refactor-multi-phase-extract-private-functions

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def

    修改时间: 2026-04-17
    修改者: TraeAI
    任务: fix-phase3-active-entities-fallback
    修改内容: 新增 active_entities 参数，透传上游已解析好的活跃实体上下文（含 fallback）

    修改时间: 2026-04-20
    修改者: Codex
    任务: strict-phase34-fallback
    修改内容: 继续透传 fallback_client，统一多阶段标注的失败语义
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

    dlg_result = await compute_dialogue_lengths_with_llm(
        client=client,
        text=text,
        alias_map=alias_map,
        # 中文注释：Phase3 和 Phase2 一样只复用上游同一份 evidence_bundle，
        # 保持多阶段标注共享同一组 Level1/2/3 证据，而不是各阶段各自拼上下文。
        # 透传 active_entities，确保 Phase3 使用与 Phase1 相同的活跃实体上下文（含 fallback）。
        evidence_bundle=evidence_bundle,
        chunk_id=chunk_id,
        run_id=run_id,
        known_characters=known_characters,
        return_tones=True,
        return_identity_clues=True,
        active_entities=active_entities,
        fallback_client=fallback_client,
    )

    result.dialogue_lengths = dlg_result.speaker_lengths or None
    result.dialogue_speakers = dlg_result.canonical_attribution or None
    result.dialogues = dlg_result.dialogues or None
    result.dialogue_tones = dlg_result.dialogue_tones or None
    result.dialogue_identity_clues = dlg_result.dialogue_identity_clues or None

    logger.debug(
        "Phase3: dialogue_lengths={} dialogue_speakers={} "
        "dialogues={} dialogue_tones={} dialogue_identity_clues={} chunk_id={}",
        result.dialogue_lengths,
        result.dialogue_speakers,
        result.dialogues,
        result.dialogue_tones,
        result.dialogue_identity_clues,
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

    修改时间: 2026-04-23
    任务: annotation-projector-runtime-landing
    修改内容: 保留兼容入口，实际校验与归一化委托 foreshadowing projector。
    """
    return project_foreshadowing_result(foreshadowing, text, chunk_id)


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

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: fix-multi-speaker-support
    修改内容: 删除 dialogue_evidences 字段
    """
    return MultiPhaseAnnotationResult(
        annotation=annotation,
        foreshadowing=foreshadowing,
        dialogue_lengths=phase3_result.dialogue_lengths,
        dialogue_speakers=phase3_result.dialogue_speakers,
        dialogues=phase3_result.dialogues,
        dialogue_tones=phase3_result.dialogue_tones,
        dialogue_identity_clues=phase3_result.dialogue_identity_clues,
        relations=phase4_result.relations,
    )


async def annotate_chunk_multi_phase(
    client: AnnotationClient,
    text: str,
    prev_summary: str | None = None,
    alias_map: dict[str, str] | None = None,
    chunk_id: int | None = None,
    global_context: str | None = None,
    prev_chunk_text: str | None = None,
    active_entities: str | None = None,
    evidence_bundle: EvidenceBundle | None = None,
    phase1_bundle: EvidenceBundle | None = None,
    phase2_bundle: EvidenceBundle | None = None,
    phase3_bundle: EvidenceBundle | None = None,
    phase4_bundle: EvidenceBundle | None = None,
    phase4_request_template: EvidenceRequest | None = None,
    evidence_service: NarrativeEvidenceService | None = None,
    disambig_context: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    fallback_client: AnnotationClient | None = None,
    run_id: str | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> MultiPhaseAnnotationResult:
    """
    多阶段标注模式

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def，使用 asyncio.gather 并行执行
    """
    parallel = settings.analysis.multi_phase_annotation.parallel

    if parallel:
        return await annotate_chunk_parallel(
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
            fallback_client=fallback_client,
            run_id=run_id,
            active_entities=active_entities,
            phase1_bundle=phase1_bundle or evidence_bundle,
            phase2_bundle=phase2_bundle or evidence_bundle,
            phase3_bundle=phase3_bundle or phase1_bundle or evidence_bundle,
            phase4_bundle=phase4_bundle or evidence_bundle,
            phase4_request_template=phase4_request_template,
            evidence_service=evidence_service,
            emitter=emitter,
            disambig_context=disambig_context,
        )
    else:
        return await annotate_chunk_serial(
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
            fallback_client=fallback_client,
            run_id=run_id,
            active_entities=active_entities,
            phase1_bundle=phase1_bundle or evidence_bundle,
            phase2_bundle=phase2_bundle or evidence_bundle,
            phase3_bundle=phase3_bundle or phase1_bundle or evidence_bundle,
            phase4_bundle=phase4_bundle or evidence_bundle,
            phase4_request_template=phase4_request_template,
            evidence_service=evidence_service,
            emitter=emitter,
            disambig_context=disambig_context,
        )


async def annotate_chunk_parallel(
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
    evidence_bundle: EvidenceBundle | None = None,
    phase1_bundle: EvidenceBundle | None = None,
    phase2_bundle: EvidenceBundle | None = None,
    phase3_bundle: EvidenceBundle | None = None,
    phase4_bundle: EvidenceBundle | None = None,
    phase4_request_template: EvidenceRequest | None = None,
    evidence_service: NarrativeEvidenceService | None = None,
    fallback_client: AnnotationClient | None = None,
    run_id: str | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    disambig_context: str | None = None,
) -> MultiPhaseAnnotationResult:
    """
    并行模式：Phase1 和 Phase2 并行执行，Phase3 在 Phase1 完成后执行

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def，使用 asyncio.gather 替代 ThreadPoolExecutor
    """
    logger.debug("annotate_chunk_parallel start chunk_id={}", chunk_id)
    import asyncio

    context = _MultiPhaseExecutionContext(
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
        phase1_bundle=phase1_bundle or evidence_bundle,
        phase2_bundle=phase2_bundle or evidence_bundle,
        phase3_bundle=phase3_bundle or phase1_bundle or evidence_bundle,
        phase4_bundle=phase4_bundle or evidence_bundle,
        phase4_request_template=phase4_request_template,
        evidence_service=evidence_service,
        fallback_client=fallback_client,
        run_id=run_id,
        emitter=emitter,
        disambig_context=disambig_context,
    )

    await _emit_phase_event(context, action="start", phase_name="phase1", sub_percent=0, message="开始 phase1")
    await _emit_phase_event(context, action="start", phase_name="phase2", sub_percent=0, message="开始 phase2")

    annotation, foreshadowing = await asyncio.gather(
        _run_phase1_from_context(context),
        _run_phase2_from_context(context),
    )

    await _emit_phase_event(context, action="complete", phase_name="phase1", sub_percent=25, message="phase1 完成")
    await _emit_phase_event(context, action="complete", phase_name="phase2", sub_percent=50, message="phase2 完成")

    known_characters, normalized_foreshadowing = _normalize_phase_outputs(context, annotation, foreshadowing)

    await _emit_phase_event(context, action="start", phase_name="phase3", sub_percent=50, message="开始 phase3")
    await _emit_phase_event(context, action="start", phase_name="phase4", sub_percent=75, message="开始 phase4")

    phase3_result, phase4_result = await asyncio.gather(
        _run_phase3_from_context(context, known_characters),
        _run_phase4_from_context(context, known_characters),
    )

    await _emit_phase_event(context, action="complete", phase_name="phase3", sub_percent=75, message="phase3 完成")
    await _emit_phase_event(context, action="complete", phase_name="phase4", sub_percent=100, message="phase4 完成")

    logger.debug("annotate_chunk_parallel complete chunk_id={}", chunk_id)

    return _build_multi_phase_result(
        annotation=annotation,
        foreshadowing=normalized_foreshadowing,
        phase3_result=phase3_result,
        phase4_result=phase4_result,
    )


async def annotate_chunk_serial(
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
    evidence_bundle: EvidenceBundle | None = None,
    phase1_bundle: EvidenceBundle | None = None,
    phase2_bundle: EvidenceBundle | None = None,
    phase3_bundle: EvidenceBundle | None = None,
    phase4_bundle: EvidenceBundle | None = None,
    phase4_request_template: EvidenceRequest | None = None,
    evidence_service: NarrativeEvidenceService | None = None,
    fallback_client: AnnotationClient | None = None,
    run_id: str | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    disambig_context: str | None = None,
) -> MultiPhaseAnnotationResult:
    """
    串行模式

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def
    """
    logger.debug("annotate_chunk_serial start chunk_id={}", chunk_id)
    context = _MultiPhaseExecutionContext(
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
        phase1_bundle=phase1_bundle or evidence_bundle,
        phase2_bundle=phase2_bundle or evidence_bundle,
        phase3_bundle=phase3_bundle or phase1_bundle or evidence_bundle,
        phase4_bundle=phase4_bundle or evidence_bundle,
        phase4_request_template=phase4_request_template,
        evidence_service=evidence_service,
        fallback_client=fallback_client,
        run_id=run_id,
        emitter=emitter,
        disambig_context=disambig_context,
    )

    await _emit_phase_event(context, action="start", phase_name="phase1", sub_percent=0, message="开始 phase1")
    annotation = await _run_phase1_from_context(context)
    await _emit_phase_event(context, action="complete", phase_name="phase1", sub_percent=25, message="phase1 完成")

    await _emit_phase_event(context, action="start", phase_name="phase2", sub_percent=25, message="开始 phase2")
    foreshadowing = await _run_phase2_from_context(context)
    await _emit_phase_event(context, action="complete", phase_name="phase2", sub_percent=50, message="phase2 完成")

    known_characters, normalized_foreshadowing = _normalize_phase_outputs(context, annotation, foreshadowing)

    await _emit_phase_event(context, action="start", phase_name="phase3", sub_percent=50, message="开始 phase3")
    phase3_result = await _run_phase3_from_context(context, known_characters)
    await _emit_phase_event(context, action="complete", phase_name="phase3", sub_percent=75, message="phase3 完成")

    await _emit_phase_event(context, action="start", phase_name="phase4", sub_percent=75, message="开始 phase4")
    phase4_result = await _run_phase4_from_context(context, known_characters)
    await _emit_phase_event(context, action="complete", phase_name="phase4", sub_percent=100, message="phase4 完成")
    logger.info(f"Phase4 completed for chunk_id={chunk_id}")

    logger.debug("annotate_chunk_serial complete chunk_id={}", chunk_id)

    return _build_multi_phase_result(
        annotation=annotation,
        foreshadowing=normalized_foreshadowing,
        phase3_result=phase3_result,
        phase4_result=phase4_result,
    )
