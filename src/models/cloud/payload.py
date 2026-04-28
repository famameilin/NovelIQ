from __future__ import annotations

from dataclasses import asdict
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from src.config import settings
from src.knowledge.authority import KnowledgeGraphAuthorityService, serialize_graph_report_signals
from src.storage.repositories.diagnosis_repository import DiagnosisRepository


def _build_graph_signal_payload(conn: Session, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    构建 diagnosis 允许复用的共享 graph signals。

    diagnosis payload 只搬运 GraphAuthorityReport 的白名单字段，
    不在这里推导 graph diagnosis 结论，也不允许 page-only 字段渗入。
    """

    graph_report = KnowledgeGraphAuthorityService.from_session(conn).build_graph_report(run_id)
    return serialize_graph_report_signals(graph_report)


def build_diagnosis_payload(conn: Session, novel_id: str | None = None, run_id: str | None = None) -> dict:
    """
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
    logger.info("[云端模型] 获取foreshadowing_threads: count=%d", len(foreshadowing_threads))

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
    获取实际主题总数（用于判断 LLM 需要命名多少个主题）。

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
