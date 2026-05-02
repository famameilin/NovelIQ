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
from src.lexicons.genre_detector_rules import DOMAIN_KEYWORDS
from src.lexicons.registry import LexiconRegistry
from src.storage.repositories import ChunkRepository
from src.storage.repositories.diagnosis_repository import DiagnosisRepository

GENRE_LABEL_MAP = {
    "scifi": "科幻",
    "mystery": "悬疑",
    "historical": "历史",
    "xianxia": "仙侠",
    "fantasy": "玄幻",
    "urban": "都市",
    "general": "通用",
}
STYLE_HINT_LABEL_MAP = {
    "power": "权谋",
    "shuwen": "爽文",
}


def _is_pending_graph_projection_error(exc: GraphReadinessError) -> bool:
    """
    创建时间: 2026-05-02
    任务: diagnosis-graph-readiness-fallback
    新建原因: diagnosis 只允许对“projection 仍 pending”做零值降级；
              如果 authority 明确报告 blocking failed rows，必须继续抛错，不能伪装成空图信号。
    """
    return "still pending" in exc.message


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
        if not _is_pending_graph_projection_error(exc):
            raise
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


def _collect_fulltext_indicator_hits(chunk_texts: list[tuple[int, str]]) -> dict[str, int]:
    """
    创建时间: 2026-05-02
    任务: diagnosis-genre-hints-and-fantasy-label
    新建原因: sampled detector 容易被泛情绪词和稀疏采样带偏；
              diagnosis payload 需要一层全书强指示词统计，给 LLM 提供可审计但不强制的题材提示。
    """
    full_text = "\n".join(text for _, text in chunk_texts if text)
    if not full_text:
        return {}

    indicator_hits: dict[str, int] = {}
    for genre_code, config in DOMAIN_KEYWORDS.items():
        hit_count = 0
        for indicator in config.get("indicators", []):
            hit_count += full_text.count(indicator)
        if hit_count > 0:
            indicator_hits[genre_code] = hit_count
    return indicator_hits


def _build_ordered_hints(
    weighted_genres: list[tuple[str, float]],
    indicator_hits: dict[str, int],
    *,
    label_map: dict[str, str],
    fallback_labels: list[str],
) -> tuple[list[str], dict[str, list[dict[str, float | int | str]]]]:
    """
    创建时间: 2026-05-02
    任务: diagnosis-genre-hints-and-fantasy-label
    新建原因: 题材提示与第二标签提示共用同一套排序逻辑；
              这里单独抽成 helper，便于后续做独立单测并显式约束排序/去重语义。
    """
    ordered_codes: list[str] = []
    for genre_code, _hit_count in sorted(indicator_hits.items(), key=lambda item: (-item[1], item[0])):
        if genre_code in label_map and genre_code not in ordered_codes:
            ordered_codes.append(genre_code)
    for genre_code, _weight in weighted_genres:
        if genre_code in label_map and genre_code not in ordered_codes:
            ordered_codes.append(genre_code)

    ordered_labels: list[str] = []
    for genre_code in ordered_codes:
        label = label_map.get(genre_code)
        if label and label not in ordered_labels:
            ordered_labels.append(label)
        if len(ordered_labels) >= 3:
            break

    if not ordered_labels:
        ordered_labels = list(fallback_labels)

    hint_details: dict[str, list[dict[str, float | int | str]]] = {
        "sampled_detector": [
            {
                "label": label_map.get(genre_code, genre_code),
                "weight": round(weight, 4),
            }
            for genre_code, weight in weighted_genres
            if genre_code in label_map
        ],
        "fulltext_indicators": [
            {
                "label": label_map.get(genre_code, genre_code),
                "hits": hit_count,
            }
            for genre_code, hit_count in sorted(indicator_hits.items(), key=lambda item: (-item[1], item[0]))
            if genre_code in label_map
        ],
    }
    return ordered_labels, hint_details


def _build_diagnosis_label_hints(
    conn: Session,
    run_id: str,
) -> tuple[
    list[str],
    dict[str, list[dict[str, float | int | str]]],
    list[str],
    dict[str, list[dict[str, float | int | str]]],
]:
    """
    修改时间: 2026-05-02
    任务: split-diagnosis-genre-and-style-labels
    修改原因: diagnosis 结果不再把 `权谋/爽文` 混进题材数组；
              payload 需要分别下发题材提示和风格提示，让 LLM 在两个数组里各自做最终判断。

    修改时间: 2026-04-29
    任务: split-genre-style-labels-review-fixes
    修改原因: review 发现 summary-only/shared-signal 入口会传入不具备 SQL execute 能力的轻量 session stand-in；
              这里仅对这类非正式 DB session 明确回退到 `["通用"]` 提示，避免打断既有 fail-fast 测试入口。
              duck-typing 检查是 pragmatically 的防御层：类型系统按 Session 标注，但运行时可能传入 stand-in。
    """
    assert set(GENRE_LABEL_MAP.keys()).isdisjoint(set(STYLE_HINT_LABEL_MAP.keys())), (
        "GENRE_LABEL_MAP and STYLE_HINT_LABEL_MAP must stay disjoint"
    )
    empty_hint_details: dict[str, list[dict[str, float | int | str]]] = {
        "sampled_detector": [],
        "fulltext_indicators": [],
    }
    if not callable(getattr(conn, "execute", None)):
        logger.warning(
            "[云端模型] 诊断标签提示回退: run_id={} 原因=session 不支持 execute()，跳过 chunk genre detector",
            run_id,
        )
        return ["通用"], empty_hint_details, [], empty_hint_details

    chunk_texts = ChunkRepository(conn).fetch_chunk_texts(run_id)
    if not chunk_texts:
        return ["通用"], empty_hint_details, [], empty_hint_details

    registry = LexiconRegistry()
    registry.load()
    weighted_result = detect_genre_weighted(chunk_texts, registry=registry)
    weighted_genres = [
        (genre_code, weight)
        for genre_code, weight in weighted_result.genre_weights
        if genre_code != "general"
    ]
    indicator_hits = _collect_fulltext_indicator_hits(chunk_texts)
    genre_hints, genre_hint_details = _build_ordered_hints(
        weighted_genres,
        indicator_hits,
        label_map=GENRE_LABEL_MAP,
        fallback_labels=["通用"],
    )
    style_hints, style_hint_details = _build_ordered_hints(
        weighted_genres,
        indicator_hits,
        label_map=STYLE_HINT_LABEL_MAP,
        fallback_labels=[],
    )
    return genre_hints, genre_hint_details, style_hints, style_hint_details


def build_diagnosis_payload(conn: Session, novel_id: str | None = None, run_id: str | None = None) -> dict:
    """
    修改时间: 2026-05-02
    任务: diagnosis-genre-hints-and-fantasy-label
    修改原因: diagnosis payload 不再把规则题材结果当成最终真相写给 LLM；
              这里只下发 `genre_hints` 与明细，正式 `genre_labels` 改由 diagnosis LLM 结合全局语义决定。

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
    genre_hints, genre_hint_details, style_hints, style_hint_details = _build_diagnosis_label_hints(
        conn, effective_run_id
    )
    logger.info("[云端模型] 获取foreshadowing_threads: count=%d", len(foreshadowing_threads))
    logger.info("[云端模型] 题材提示: %s", genre_hints)
    logger.info("[云端模型] 风格提示: %s", style_hints)

    stage_summaries = repo.fetch_stage_summaries(effective_run_id)
    logger.info("[云端模型] 获取阶段性摘要: count=%d", len(stage_summaries))

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
        "genre_hints": genre_hints,
        "genre_hint_details": genre_hint_details,
        "style_hints": style_hints,
        "style_hint_details": style_hint_details,
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
