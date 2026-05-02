from __future__ import annotations

from dataclasses import asdict
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from src.api.exceptions import GraphReadinessError
from src.config import settings
from src.knowledge.authority import KnowledgeGraphAuthorityService, serialize_graph_report_signals
from src.knowledge.authority.types import GraphAuthorityReport, GraphQualitySignals, GraphSharedSummary
from src.lexicons.genre_detector import detect_genre_weighted
from src.lexicons.genre_detector_rules import MIN_CONFIDENCE
from src.lexicons.registry import LexiconRegistry
from src.storage.repositories import ChunkRepository
from src.storage.repositories.diagnosis_repository import DiagnosisRepository

GENRE_LABEL_MAP = {
    "scifi": "科幻",
    "mystery": "悬疑",
    "historical": "历史",
    "xianxia": "仙侠",
    "urban": "都市",
    "power": "权谋",
    "shuwen": "爽文",
    "general": "通用",
}


def _build_graph_signal_payload(conn: Session, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    修改时间: 2026-05-02
    任务: diagnosis-graph-readiness-fallback
    修改原因: diagnosis 只复用 graph-owned aggregate signals；当 graph projection 仍有 pending 行时，
              这里应像 aggregate 一样降级为零值共享信号，而不是让整条分析任务失败。

    构建 diagnosis 允许复用的共享 graph signals

    diagnosis payload 只搬运 GraphAuthorityReport 的白名单字段，
    不在这里推导 graph diagnosis 结论，也不允许 page-only 字段渗入
    """
    try:
        graph_report = KnowledgeGraphAuthorityService.from_session(conn).build_graph_report(run_id)
    except GraphReadinessError as exc:
        logger.warning(
            "[云端模型] graph signals 回退为零值共享信号: run_id={} 原因={}",
            run_id,
            exc.message,
        )
        graph_report = GraphAuthorityReport(
            summary=GraphSharedSummary(),
            quality=GraphQualitySignals(),
        )
    return serialize_graph_report_signals(graph_report)


def _build_genre_labels(conn: Session, run_id: str) -> list[str]:
    """
    2026-04-29，任务：拆分 diagnosis 题材与风格标签
    新建原因：`genre_labels` 需要成为稳定题材真相源，统一复用现有加权 genre detector，而不是继续交给 LLM 自由发挥。

    修改时间: 2026-04-29
    任务: split-genre-style-labels-review-fixes
    修改原因: review 发现 summary-only/shared-signal 入口会传入不具备 SQL execute 能力的轻量 session stand-in；
              这里仅对这类非正式 DB session 明确回退到 `["通用"]`，避免打断既有 fail-fast 测试入口。
    """
    if not callable(getattr(conn, "execute", None)):
        logger.warning(
            "[云端模型] 题材标签回退为通用: run_id={} 原因=session 不支持 execute()，跳过 chunk genre detector",
            run_id,
        )
        return ["通用"]

    chunk_texts = ChunkRepository(conn).fetch_chunk_texts(run_id)
    if not chunk_texts:
        return ["通用"]

    registry = LexiconRegistry()
    registry.load()
    weighted_result = detect_genre_weighted(chunk_texts, registry=registry)
    genre_weights = weighted_result.genre_weights
    if not genre_weights:
        return ["通用"]

    dominant_genre, _dominant_weight = genre_weights[0]
    if dominant_genre == "general":
        return ["通用"]

    genre_labels: list[str] = []
    for index, (genre_code, weight) in enumerate(genre_weights):
        if genre_code == "general":
            continue
        if index > 0 and weight < MIN_CONFIDENCE:
            continue
        label = GENRE_LABEL_MAP.get(genre_code)
        if label and label not in genre_labels:
            genre_labels.append(label)
        if len(genre_labels) >= 3:
            break

    return genre_labels or ["通用"]


def build_diagnosis_payload(conn: Session, novel_id: str | None = None, run_id: str | None = None) -> dict:
    """
    修改时间: 2026-04-30
    任务: diagnosis-latest-only-reference-contract
    修改原因: diagnosis payload 不再写入 reference_contract_version；当前结构默认按最新合同消费，
              这里只保留真正会被下游读取的业务字段。

    构建诊断payload
    """
    logger.info(
        "[云端模型] 构建诊断payload开始: novel_id=%s run_id=%s",
        novel_id,
        run_id,
    )

    effective_run_id = run_id or ""
    repo = DiagnosisRepository(conn)

    pivot_blocks: list[dict[str, Any]] = []
    for chunk_id, chunk_text, event_type in repo.fetch_pivot_blocks(
        effective_run_id, limit=settings.diagnosis.pivot_blocks_limit
    ):
        pivot_blocks.append(
            {
                "chunk_id": chunk_id,
                "text": chunk_text[: settings.diagnosis.text_limits.pivot_block] if chunk_text else "",
                "event_type": event_type,
            }
        )
    logger.info("[云端模型] 获取pivot_blocks: count=%d", len(pivot_blocks))

    pivot_moments: list[dict[str, Any]] = []
    for chunk_id, chunk_text in repo.fetch_pivot_moments(
        effective_run_id, limit=settings.diagnosis.pivot_moments_limit
    ):
        pivot_moments.append(
            {
                "chunk_id": chunk_id,
                "text": chunk_text[: settings.diagnosis.text_limits.pivot_moment] if chunk_text else "",
            }
        )
    logger.info("[云端模型] 获取pivot_moments: count=%d", len(pivot_moments))

    high_tension: list[dict[str, Any]] = []
    for chunk_id, chunk_text, tension in repo.fetch_high_tension_chunks(
        effective_run_id, limit=settings.diagnosis.high_tension_limit
    ):
        high_tension.append(
            {
                "chunk_id": chunk_id,
                "text": chunk_text[: settings.diagnosis.text_limits.high_tension] if chunk_text else "",
                "tension": round(tension, 4),
            }
        )
    logger.info("[云端模型] 获取high_tension: count=%d", len(high_tension))

    relations: list[dict[str, Any]] = []
    for chunk_id, from_char, to_char, rel_type, change in repo.fetch_relation_changes(
        effective_run_id, limit=settings.diagnosis.relation_changes_limit
    ):
        relations.append(
            {
                "chunk_id": chunk_id,
                "from": from_char,
                "to": to_char,
                "type": rel_type,
                "change": change,
            }
        )
    logger.info("[云端模型] 获取relation_changes: count=%d", len(relations))

    foreshadowing_threads = [asdict(thread) for thread in repo.fetch_foreshadowing_threads(effective_run_id)]
    foreshadow_expectation = repo.calculate_foreshadow_expectation(effective_run_id)
    genre_labels = _build_genre_labels(conn, effective_run_id)
    logger.info("[云端模型] 获取foreshadowing_threads: count=%d", len(foreshadowing_threads))
    logger.info("[云端模型] 题材标签: %s", genre_labels)

    stage_summaries = repo.fetch_stage_summaries(effective_run_id)
    logger.info("[云端模型] 获取阶段性摘要: count=%d", len(stage_summaries))

    topic_words = repo.fetch_topic_words(effective_run_id, top_n=settings.diagnosis.topic_words_top_n)
    logger.info("[云端模型] 获取topic_words: count=%d", len(topic_words))

    # 获取实际主题总数
    total_topics = _get_total_topic_count(effective_run_id, repo)

    # LLM 高质量命名上限：超过 MAX_TOPICS_FOR_NAMING 的只发头部
    # 单书默认 25 通常全部发送；若用户配了 100+ 则只发前 30 个
    MAX_TOPICS_FOR_NAMING = 30
    send_count = min(total_topics, MAX_TOPICS_FOR_NAMING) if total_topics > 0 else total_topics
    topic_words = repo.fetch_topic_words(effective_run_id, top_n=send_count)
    logger.info(
        "[云端模型] 主题总数: %d (发送前%d个给LLM%s)",
        total_topics,
        send_count,
        f", 超出{MAX_TOPICS_FOR_NAMING}个只命名头部" if send_count < total_topics else "",
    )

    known_characters, alias_merges = repo.fetch_character_disambig_data(effective_run_id)
    graph_summary, graph_quality_report = _build_graph_signal_payload(conn, effective_run_id)

    payload = {
        "novel_id": novel_id,
        "pivot_blocks": pivot_blocks,
        "pivot_moments": pivot_moments,
        "high_tension_paragraphs": high_tension,
        "character_relations": relations,
        "foreshadow_expectation": foreshadow_expectation,
        "genre_labels": genre_labels,
        "foreshadowing_threads": foreshadowing_threads,
        "summaries": stage_summaries,
        "topic_words": topic_words,
        "total_topics": total_topics,
        "known_characters": known_characters,
        "alias_merges": alias_merges,
        "graph_summary": graph_summary,
        "graph_quality_report": graph_quality_report,
    }

    logger.info(
        "[云端模型] 诊断payload构建完成: "
        "pivot_blocks=%d pivot_moments=%d high_tension=%d "
        "relations=%d foreshadowing_threads=%d summaries=%d topic_words=%d "
        "known_characters=%d alias_merges=%d graph_nodes=%d",
        len(pivot_blocks),
        len(pivot_moments),
        len(high_tension),
        len(relations),
        len(foreshadowing_threads),
        len(stage_summaries),
        len(topic_words),
        len(known_characters),
        len(alias_merges),
        graph_summary.get("node_count", 0),
    )

    return payload


def _get_total_topic_count(run_id: str, repo: DiagnosisRepository) -> int:
    """
    获取实际主题总数（用于判断 LLM 需要命名多少个主题）

    单书模式（~25 个）：全部发给 LLM，全部需要命名
    多书模式（100+ 个）：只发头部，LLM 只需命名发送的那些
    """
    from sqlalchemy import func as sa_func
    from sqlalchemy import select

    from src.storage.models import ChunkTopic

    stmt = select(sa_func.count(ChunkTopic.topic_id.distinct())).where(ChunkTopic.run_id == run_id)
    result = repo.session.execute(stmt)
    total = result.scalar() or 0
    return total
