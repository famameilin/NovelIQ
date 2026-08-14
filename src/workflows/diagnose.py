"""
诊断工作流模块（LangGraph 诊断 Agent）

诊断 agent 通过工具化自主取证（聚合指标/转折素材/人物/主题/图谱信号），
最终输出 CloudAnalysis，不再预构建一次性大 payload
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from loguru import logger
from sqlalchemy.orm import Session

from src.agents.stream import AgentStream
from src.api.exceptions import GraphReadinessError
from src.api.models.events import StreamEvent
from src.config.analysis_logger import AnalysisLogger
from src.models.cloud.schema import CloudAnalysis
from src.storage.repositories import RunRepository, StatsRepository


def _log_diagnosis_results(result: CloudAnalysis) -> None:
    """
    输出诊断结果日志
    """
    logger.info("\n=== Diagnosis Summary ===")
    logger.info(f"Novel ID: {result.novel_id}")
    logger.info(f"Genre Labels: {', '.join(result.genre_labels) if result.genre_labels else '[]'}")
    logger.info(f"Style Labels: {', '.join(result.style_labels) if result.style_labels else '[]'}")
    if result.foreshadow_expectation is not None:
        logger.info(f"Foreshadow Expectation: {result.foreshadow_expectation:.2%}")
    if result.value_logic_type:
        logger.info(f"Value Logic Type: {result.value_logic_type}")
    if result.value_logic_reason:
        logger.info(f"Value Logic Reason: {result.value_logic_reason}")
    if result.power_stance_score is not None:
        logger.info(f"Power Stance Score: {result.power_stance_score}/5")
    if result.power_stance_reason:
        logger.info(f"Power Stance Reason: {result.power_stance_reason}")
    if result.common_people_dignity is not None:
        logger.info(f"Common People Dignity: {result.common_people_dignity}/5")
    if result.dignity_reason:
        logger.info(f"Dignity Reason: {result.dignity_reason}")
    if result.diagnosis:
        logger.info(f"\nDiagnosis:\n{result.diagnosis}")


def _persist_main_character_attributes(
    session: Session,
    *,
    run_id: str,
    main_characters: list[str],
) -> None:
    """2026-08-09 用于把诊断主角名单固化为图节点属性"""
    from sqlalchemy import select

    from src.knowledge.authority import KnowledgeGraphAuthorityService
    from src.storage.models import GraphEntity

    if not main_characters:
        return
    try:
        view = KnowledgeGraphAuthorityService.from_session(session).build_export_view(run_id)
    except (ValueError, GraphReadinessError):
        # 图未就绪或数据异常时静默跳过主角属性固化（后续图版本补写）
        return
    preferred = set(main_characters)
    representative_ids: set[int] = set()
    for item in view.canonical_entities:
        if item.entity_id is None:
            continue
        aliases = set(item.aliases)
        if item.name in preferred or (aliases & preferred):
            representative_ids.add(int(item.entity_id))
    if not representative_ids:
        return
    graph_entities = list(
        session.execute(
            select(GraphEntity).where(
                GraphEntity.run_id == run_id,
            )
        ).scalars()
    )
    # 2026-08-13 P2-2 重跑诊断先清除该 run 全部实体的 is_main_character 标记，
    # 避免旧名单残留（只置位不清理会让已下榜角色仍显示为主角）。
    # attributes 是 JSON 列，这里读改写后整体写回，与下文置位共用同一批实体。
    for graph_entity in graph_entities:
        attributes = dict(graph_entity.attributes or {})
        if attributes.pop("is_main_character", None) is not None:
            graph_entity.attributes = attributes
    for graph_entity in graph_entities:
        if graph_entity.entity_id not in representative_ids:
            continue
        attributes = dict(graph_entity.attributes or {})
        attributes["is_main_character"] = True
        graph_entity.attributes = attributes
    session.flush()


async def run_diagnose(
    run_id: str,
    session: Session,
    analysis_logger: AnalysisLogger | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> CloudAnalysis:
    """
    执行诊断流程（诊断 Agent 工具化自主取证）

    Args:
        run_id: 运行ID
        session: 数据库连接
        analysis_logger: 分析日志器

    Returns:
        CloudAnalysis: 诊断分析结果
    """
    from src.agents import run_diagnosis_agent

    run_repo = RunRepository(session)
    run = run_repo.get_run(run_id)
    if not run:
        raise ValueError(f"run {run_id} not found")
    novel_id = str(run.get("novel_id", "")).strip() or ""
    if not novel_id:
        raise ValueError(f"run {run_id} is missing novel_id, cannot build diagnosis payload")
    # RunRepository._to_dict 的键是 "title"（非 "novel_title"）
    novel_title = str(run.get("title", "")).strip() or None

    agent_stream = AgentStream(emitter, sub_stage="diagnosis") if emitter is not None else None

    result = await run_diagnosis_agent(
        session=session,
        run_id=run_id,
        novel_id=novel_id,
        novel_title=novel_title,
        stream=agent_stream,
    )

    stats_repo = StatsRepository(session)
    stats_repo.insert_cloud_analysis(run_id, result)
    _persist_main_character_attributes(
        session,
        run_id=run_id,
        main_characters=list(result.main_characters),
    )
    logger.debug(f"diagnosis persisted run_id={run_id}")

    _log_diagnosis_results(result)

    if emitter:
        await emitter(
            StreamEvent(action="complete", stage="diagnose", current=1, total=1, percent=100.0, sub_percent=100.0)
        )

    return result
