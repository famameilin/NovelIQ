"""
标注辅助函数模块 - 阶段管理

创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改历史:
- 2026-03-14: 从 cli.annotate_helpers 迁移，解决循环依赖
- 2026-03-14: 添加 run_id 参数支持 (workflows-repository-refactor)
- 2026-03-17: 使用 AnnotationPhaseConfig 简化多参数函数

说明: 本模块包含阶段管理相关的数据类和函数。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.api.models.events import StreamEvent
from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.models.interfaces import AnnotationLike, DisambiguationLike
from src.models.local.disambiguation import DisambiguationState

if TYPE_CHECKING:
    from src.models.local.annotation import MultiPhaseAnnotationResult
    from src.rag import EvidenceBundle, NarrativeEvidenceService


@dataclass
class AnnotationPhaseConfig:
    """标注阶段配置"""

    conn: Any
    all_chunks: list
    novel_id: str
    novel_title: str | None = None
    use_context_enhancement: bool = False
    use_rag: bool = False
    resume: bool = False
    analysis_logger: AnalysisLogger | None = None
    annotate_client: AnnotationLike | None = None
    incremental_disambig_client: DisambiguationLike | None = None
    full_disambig_client: DisambiguationLike | None = None
    run_id: str = ""
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None


class ChunkAnnotationMaxRetriesExceededError(Exception):
    """Chunk标注重试次数耗尽异常"""

    pass


async def _annotate_chunk(
    client: AnnotationLike,
    text: str,
    prev_summary: str | None = None,
    alias_map: dict[str, str] | None = None,
    chunk_id: int | None = None,
    global_context: str | None = None,
    active_entities: str | None = None,
    evidence_bundle: EvidenceBundle | None = None,
    phase1_bundle: EvidenceBundle | None = None,
    phase2_bundle: EvidenceBundle | None = None,
    phase3_bundle: EvidenceBundle | None = None,
    phase4_bundle: EvidenceBundle | None = None,
    phase4_request_template=None,
    evidence_service: NarrativeEvidenceService | None = None,
    fallback_client: AnnotationLike | None = None,
    run_id: str | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    disambig_context: str | None = None,
) -> MultiPhaseAnnotationResult:
    """
    Chunk 标注函数

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 标注流程

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 统一字段命名，添加 run_id 支持

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-validate-names-from-character-appearances
    修改内容: 增加 character_appearances 参数支持

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: simplify-phase1-prompt
    修改内容: 移除 prev_chunk_text 和 next_chunk_text 参数

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: refactor/annotate-async
    修改内容: 改为 async def

    重试策略:
    - 内层: 主标注客户端最多3次（任何错误类型）
    - 内层: 主客户端失败后兜底客户端1次
    - 兜底客户端失败直接终止整个任务
    """
    try:
        return await client.annotate_chunk(
            text,
            prev_summary,
            alias_map=alias_map,
            chunk_id=chunk_id,
            global_context=global_context,
            active_entities=active_entities,
            evidence_bundle=evidence_bundle,
            phase1_bundle=phase1_bundle,
            phase2_bundle=phase2_bundle,
            phase3_bundle=phase3_bundle,
            phase4_bundle=phase4_bundle,
            phase4_request_template=phase4_request_template,
            evidence_service=evidence_service,
            fallback_client=fallback_client,
            run_id=run_id,
            emitter=emitter,
            disambig_context=disambig_context,
        )
    except Exception as e:
        logger.error(f"chunk annotation failed for chunk_id={chunk_id}: {str(e)}")
        logger.error(f"exception type: {type(e).__name__}, repr: {repr(e)}, args: {e.args}")
        raise ChunkAnnotationMaxRetriesExceededError(str(e)) from e


class AnnotationPhaseResult:
    """标注阶段结果数据类"""

    def __init__(
        self,
        annotation_client: AnnotationLike,
        annotation_fallback_client: AnnotationLike | None,
        incremental_disambig_client: DisambiguationLike,
        full_disambig_client: DisambiguationLike,
        evidence_service: NarrativeEvidenceService | None,
        alias_keywords: list[str],
        global_context_str: str | None,
        alias_map: dict[str, str],
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> None:
        self.annotation_client = annotation_client
        self.annotation_fallback_client = annotation_fallback_client
        self.incremental_disambig_client = incremental_disambig_client
        self.full_disambig_client = full_disambig_client
        self.evidence_service = evidence_service
        self.alias_keywords = alias_keywords
        self.global_context_str = global_context_str
        self.alias_map = alias_map
        self.emitter = emitter


def _set_client_session(client: Any, session: Any) -> None:
    """
    为客户端设置会话。

    使用公开方法 set_session 进行会话注入。
    """
    if client is None:
        return
    client.set_session(session)


async def _init_annotation_phase_with_config(
    config: AnnotationPhaseConfig,
) -> AnnotationPhaseResult:
    """初始化标注阶段（使用配置对象）"""
    from .client_init import _init_annotation_clients, _setup_token_usage_callback
    from .context import _init_evidence_service
    from .sentence import _extract_and_save_global_context

    if not config.run_id:
        raise ValueError("run_id is required for annotation phase")

    (annotation_client, annotation_fallback_client, incremental_client, full_client) = _init_annotation_clients(
        config.analysis_logger,
        config.annotate_client,
        config.incremental_disambig_client,
        config.full_disambig_client,
        emitter=config.emitter,
    )

    # 设置 session 用于保存模型交互记录
    if config.conn is not None:
        _set_client_session(annotation_client, config.conn)
        _set_client_session(annotation_fallback_client, config.conn)
        _set_client_session(incremental_client, config.conn)
        _set_client_session(full_client, config.conn)

    clients = [
        annotation_client,
        annotation_fallback_client,
        incremental_client,
        full_client,
    ]
    _setup_token_usage_callback(config.conn, clients, config.novel_id, annotation_client, run_id=config.run_id)

    alias_keywords: list[str] = ["某", "名", "号", "就是", "称号", "全名"]

    evidence_service = _init_evidence_service(
        config.conn,
        config.novel_id,
        config.use_rag,
        run_id=config.run_id,
        emitter=config.emitter,
    )
    if evidence_service is not None:
        await evidence_service.ensure_level3_ready()

    global_context_str = await _extract_and_save_global_context(
        config.conn,
        config.all_chunks,
        config.novel_id,
        config.novel_title,
        config.use_context_enhancement,
        config.resume,
        annotation_client,
        run_id=config.run_id,
    )

    return AnnotationPhaseResult(
        annotation_client=annotation_client,
        annotation_fallback_client=annotation_fallback_client,
        incremental_disambig_client=incremental_client,
        full_disambig_client=full_client,
        evidence_service=evidence_service,
        alias_keywords=alias_keywords,
        global_context_str=global_context_str,
        alias_map={},
        emitter=config.emitter,
    )


async def _init_annotation_phase(
    conn,
    all_chunks: list,
    novel_id: str,
    novel_title: str | None,
    use_context_enhancement: bool,
    use_rag: bool,
    resume: bool,
    analysis_logger: AnalysisLogger | None,
    annotate_client: AnnotationLike | None,
    incremental_disambig_client: DisambiguationLike | None = None,
    full_disambig_client: DisambiguationLike | None = None,
    run_id: str = "",
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> AnnotationPhaseResult:
    """
    初始化标注阶段

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: 标注流程阶段化

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: code-quality-refactor - 简化多参数函数
    修改内容: 改为调用 _init_annotation_phase_with_config，保持向后兼容

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: refactor/annotate-async
    修改内容: 改为 async def

    Returns:
        AnnotationPhaseResult: 包含所有初始化后的资源
    """
    config = AnnotationPhaseConfig(
        conn=conn,
        all_chunks=all_chunks,
        novel_id=novel_id,
        novel_title=novel_title,
        use_context_enhancement=use_context_enhancement,
        use_rag=use_rag,
        resume=resume,
        analysis_logger=analysis_logger,
        annotate_client=annotate_client,
        incremental_disambig_client=incremental_disambig_client,
        full_disambig_client=full_disambig_client,
        run_id=run_id,
        emitter=emitter,
    )
    return await _init_annotation_phase_with_config(config)


async def _process_single_chunk(
    conn,
    chunk_id: int,
    chunk_text: str,
    idx: int,
    total_chunks: int,
    phase_result: AnnotationPhaseResult,
    state: DisambiguationState,
    use_context_enhancement: bool,
    incremental_interval: int,
    run_id: str = "",
    novel_id: str = "",
) -> DisambiguationState:
    """处理单个chunk

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: 标注流程阶段化

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: 修复 _run_incremental_disambiguation 缺少 novel_id 参数的错误
    修改内容: 添加 novel_id 参数并传递给 _run_incremental_disambiguation

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: analyze-dialogue-length-zero
    修改内容: 传递 client 参数到 _store_annotation_results 以支持 LLM 对话归属判断

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-phase3-not-called
    修改内容: 在 _process_single_chunk 中调用 phase3 计算对话长度，而不是在 storage 中

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: disambiguation-state-three-layer
    修改内容: 使用 DisambiguationState 替代 alias_map，使用 _run_incremental_disambiguation_with_state

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: refactor/annotate-async
    修改内容: 改为 async def，await annotate_chunk
    """
    from .context import _prepare_chunk_context_with_level3
    from .disambiguation import _run_incremental_disambiguation_with_state
    from .storage import _store_annotation_results

    logger.info(f"Annotating chunk {idx + 1}/{total_chunks}")

    alias_map = state.get_alias_merges_dict()

    ctx = await _prepare_chunk_context_with_level3(
        conn, chunk_id, chunk_text, alias_map, use_context_enhancement, phase_result.evidence_service, run_id=run_id
    )

    annotation_result = await _annotate_chunk(
        phase_result.annotation_client,
        chunk_text,
        None,
        alias_map=alias_map if alias_map else None,
        chunk_id=chunk_id,
        global_context=phase_result.global_context_str,
        active_entities=ctx.prompt_active_entities,
        phase1_bundle=ctx.phase1_bundle,
        phase2_bundle=ctx.phase2_bundle,
        phase3_bundle=ctx.phase3_bundle,
        phase4_bundle=ctx.phase4_bundle,
        phase4_request_template=ctx.phase4_request_template,
            evidence_service=phase_result.evidence_service,
        disambig_context=ctx.prompt_disambig_context,
        fallback_client=phase_result.annotation_fallback_client,
        run_id=run_id,
        emitter=phase_result.emitter,
    )

    _store_annotation_results(
        conn,
        chunk_id,
        annotation_result.annotation,
        chunk_text,
        use_context_enhancement,
        run_id=run_id,
        foreshadowing=annotation_result.foreshadowing,
        alias_map=alias_map if alias_map else None,
        dialogue_speakers=annotation_result.dialogue_speakers,
        dialogues=annotation_result.dialogues,
        dialogue_tones=annotation_result.dialogue_tones,
        dialogue_identity_clues=annotation_result.dialogue_identity_clues,
        relations=annotation_result.relations,
    )
    logger.debug(f"annotated chunk_id={chunk_id}")

    state = await _run_incremental_disambiguation_with_state(
        conn,
        state,
        phase_result.incremental_disambig_client,
        phase_result.alias_keywords,
        novel_id,
        run_id,
        chunk_id,
        idx,
        incremental_interval,
            evidence_service=phase_result.evidence_service,
    )

    return state


async def _process_chunks_phase(
    conn,
    all_chunks: list,
    annotated_ids: set[int],
    phase_result: AnnotationPhaseResult,
    use_context_enhancement: bool,
    incremental_interval: int,
    run_id: str = "",
    novel_id: str = "",
    resume: bool = False,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[int, DisambiguationState]:
    """处理所有chunks阶段

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: 标注流程阶段化

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: fix-entity-relations-not-saved
    修改内容: 添加 resume 参数，支持从 checkpoint 恢复 alias_map

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: disambiguation-state-three-layer
    修改内容: 使用 _load_disambig_checkpoint 替代 _load_disambig_checkpoint，返回 DisambiguationState

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: refactor/annotate-async
    修改内容: 改为 async def，await _process_single_chunk
    """
    from .disambiguation import (
        DisambiguationMaxRetriesExceededError,
        _load_disambig_checkpoint,
        _save_disambig_checkpoint,
    )
    from .graph_projection import project_graph_tables

    already_annotated = len(annotated_ids)
    success_count = 0
    newly_annotated = 0  # 本次运行新标注的 chunk 数，用于 checkpoint/projection 间隔

    checkpoint_interval = max(1, settings.analysis.checkpoint_interval)
    projection_interval = max(1, settings.analysis.projection_interval)
    state: DisambiguationState = DisambiguationState.empty()
    if resume and run_id:
        state = _load_disambig_checkpoint(conn, run_id)
        if state.discovered_names:
            logger.info(
                f"resumed from checkpoint: {len(state.discovered_names)} discovered, "
                f"{len(state.known_canonical_names)} canonicals, {len(state.alias_merges)} merges"
            )

    total_chunks = len(all_chunks)

    # 发送 annotate 阶段的 total 信息，让前端知道总 chunk 数
    # 注意：不传 percent，让 stage 级别的起始 percent 保持有效
    if emitter and total_chunks > 0:
        await emitter(
            StreamEvent(
                action="progress",
                sub_stage="phase1",
                current=already_annotated,
                total=total_chunks,
                sub_percent=(already_annotated / total_chunks) * 100 if total_chunks > 0 else 0.0,
                message=(
                    f"共 {total_chunks} 个 chunk，{already_annotated} 个已标注，"
                    f"剩余 {total_chunks - already_annotated} 个待标注"
                ),
            )
        )

    for idx, (chunk_id, chunk_text) in enumerate(all_chunks):
        if chunk_id in annotated_ids:
            logger.debug(f"skipping already annotated chunk_id={chunk_id}")
            continue

        if is_cancelled and is_cancelled():
            logger.warning(f"Annotation cancelled at chunk {idx + 1}/{total_chunks}")
            break

        try:
            state = await _process_single_chunk(
                conn,
                chunk_id,
                chunk_text,
                idx,
                total_chunks,
                phase_result,
                state,
                use_context_enhancement,
                incremental_interval,
                run_id=run_id,
                novel_id=novel_id,
            )
            success_count += 1
            newly_annotated += 1
            progress_count = already_annotated + success_count
            if emitter:
                await emitter(
                    StreamEvent(
                        action="progress",
                        sub_stage="phase1",
                        current=progress_count,
                        total=total_chunks,
                        percent=10 + (progress_count / total_chunks) * 70,
                        sub_percent=(progress_count / total_chunks) * 100,
                        # 中文注释：resume 模式下进度条应继续从“已存在结果”往前走，
                        # 但 workflow 返回值仍应只统计本次新成功处理的 chunk 数。
                        message=f"标注 chunk {progress_count}/{total_chunks}",
                    )
                )
            if run_id and newly_annotated % checkpoint_interval == 0:
                _save_disambig_checkpoint(conn, run_id, state)
            if run_id and newly_annotated % projection_interval == 0:
                project_graph_tables(run_id, to_chunk=chunk_id, session=conn)
                # projection 更新了别名表，需刷新消歧缓存
                if phase_result.evidence_service:
                    phase_result.evidence_service.invalidate_cache()

        except ChunkAnnotationMaxRetriesExceededError as e:
            logger.error(f"chunk annotation max retries exceeded for chunk_id={chunk_id}: {str(e)}")
            # 失败的 chunk 不触发 projection，别名缓存保持当前状态
            raise
        except DisambiguationMaxRetriesExceededError as e:
            logger.error(f"disambiguation max retries exceeded for chunk_id={chunk_id}: {str(e)}")
            raise

    if run_id and all_chunks:
        final_chunk_id = all_chunks[-1][0]
        project_graph_tables(run_id, to_chunk=final_chunk_id, session=conn)
    if phase_result.evidence_service:
        phase_result.evidence_service.invalidate_cache()

    return success_count, state


async def _run_disambiguation_phase(
    conn,
    state: DisambiguationState,
    phase_result: AnnotationPhaseResult,
    novel_id: str,
    use_rag: bool,
    run_id: str = "",
) -> DisambiguationState:
    """执行消歧阶段

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: disambiguation-state-three-layer
    修改内容: 使用 DisambiguationState 替代 alias_map，使用 _run_final_disambiguation_with_state
    """
    from .disambiguation import _run_final_disambiguation_with_state

    state = await _run_final_disambiguation_with_state(
        conn,
        state,
        phase_result.full_disambig_client,
        phase_result.alias_keywords,
        novel_id,
        run_id=run_id,
        evidence_service=phase_result.evidence_service,
    )

    return state
