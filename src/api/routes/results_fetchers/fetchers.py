"""
数据获取函数

创建时间: 2026-03-28
创建者: TraeAI
任务: consolidate-codebase-architecture
说明: 从 results_fetchers.py 拆分，包含数据获取相关函数
"""

from __future__ import annotations

import binascii
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections import defaultdict
from pathlib import Path
from typing import Any

from loguru import logger

from src.api.models.responses import (
    CharacterRelation,
    CharacterStats,
    ChunkAnnotation,
    ChunkCharacter,
    ChunkCurvePoint,
    ChunkDialogue,
    ChunkRelation,
    ChunkStyle,
    DiagnosisResult,
    GlobalStats,
    HierarchicalRelation,
    TokenUsageByModel,
    TokenUsageByTask,
    TokenUsageStats,
    TokenUsageSummary,
    TopicInfo,
)
from src.api.routes.results_fetchers.normalizers import (
    _normalize_name,
    _normalize_name_list,
    _normalize_text_by_alias_map,
)
from src.api.routes.results_fetchers.parsers import _parse_int_field, _parse_json_field
from src.api.routes.results_fetchers.scoring import _calculate_protagonist_scores, _normalize_arc_scores
from src.config import settings
from src.config.constants import EMOTION_SCORE_MAPPING
from src.knowledge.authority import ExportGraphAuthorityView, KnowledgeGraphAuthorityService
from src.knowledge.authority.graph_outputs import (
    build_graph_page_quality,
    build_graph_page_summary,
    serialize_graph_page_quality,
    serialize_graph_page_summary,
)
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    DiagnosisRepository,
    GraphRepository,
    StatsRepository,
)

GRAPH_PAGE_EVENT_LIMIT = 200


def _encode_graph_events_cursor(offset: int) -> str:
    """Encode an opaque cursor for the next graph event slice."""
    payload = json.dumps({"offset": offset}, separators=(",", ":")).encode("utf-8")
    return urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_graph_events_cursor(cursor: str | None) -> int:
    """Decode the graph event cursor back into a slice offset."""
    if not cursor:
        return 0

    padded_cursor = cursor + ("=" * (-len(cursor) % 4))
    try:
        payload = json.loads(urlsafe_b64decode(padded_cursor.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("invalid graph events cursor") from exc

    offset = payload.get("offset")
    # bool is a subclass of int in Python, but graph cursors only allow plain
    # non-negative integer offsets. Reject boolean payloads so invalid cursors
    # never silently coerce to 0/1.
    if type(offset) is not int or offset < 0:
        raise ValueError("invalid graph events cursor")
    return offset


def _serialize_graph_event(event: Any) -> dict[str, Any]:
    """Flatten authority relation events into the public graph DTO shape."""
    return {
        "relation_event_id": event.relation_event_id,
        "chunk_id": event.chunk_id,
        "from_entity_id": event.from_entity_id,
        "to_entity_id": event.to_entity_id,
        "from_name": event.from_name,
        "to_name": event.to_name,
        "relation_type": event.relation_type,
        "change_type": event.change_type,
        "evidence": event.evidence,
        "confidence": event.confidence,
        "source_relation_row_id": event.source_relation_row_id,
        "directionality": event.directionality,
    }


def _paginate_graph_relation_events(
    relation_events: list[Any],
    *,
    cursor: str | None = None,
    limit: int = GRAPH_PAGE_EVENT_LIMIT,
) -> tuple[list[Any], dict[str, Any]]:
    """
    Slice graph-page relation history without changing authority semantics.

    The input list is expected to already be in the stable authority order
    (newest-first). The cursor is opaque to callers and only carries the next
    offset inside that fixed ordering.
    """
    page_limit = max(1, min(limit, GRAPH_PAGE_EVENT_LIMIT))
    start = _decode_graph_events_cursor(cursor)
    total = len(relation_events)
    if start > total:
        raise ValueError("graph events cursor is out of range")

    end = min(start + page_limit, total)
    next_cursor = _encode_graph_events_cursor(end) if end < total else None
    page_info = {
        "limit": page_limit,
        "returned_count": end - start,
        "total": total,
        "has_more": next_cursor is not None,
        "next_cursor": next_cursor,
    }
    return relation_events[start:end], page_info


def _fetch_chunk_curves(run_id: str, stats_repo: StatsRepository) -> list:
    """
    获取分块曲线数据（情绪 + 节奏）

    修改时间: 2026-03-30
    修改者: CodeBuddy
    任务: db-schema-cleanup
    修改内容: 合并 _fetch_emotion_curve + _fetch_rhythm_curve 为统一接口

    修改时间: 2026-03-31
    修改者: TraeAI
    任务: refactor-hardcoded-index-access
    修改内容: 使用字段名访问替代硬编码索引
    """
    rows = stats_repo.fetch_chunk_curves_full(run_id)
    return [
        ChunkCurvePoint(
            chunk_id=row.chunk_id,
            pos_density=row.pos_density,
            neg_density=row.neg_density,
            net_density=row.net_density,
            smoothed_density=row.smoothed_density,
            tension_proxy=row.tension_proxy,
            tension_composite=row.tension_composite,
        )
        for row in rows
    ]


def _fetch_characters(
    run_id: str,
    annotation_repo: AnnotationRepository,
    arc_scores: dict[str, float] | None = None,
    main_characters: list[str] | None = None,
    limit: int | None = settings.api.query_limit,
) -> list:
    """
    获取角色统计数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 AnnotationRepository

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: fix-role-function-aggregation
    修改内容: 统计 role_function 频次，取众数而非首次出现的值

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: 扩展角色统计字段
    修改内容:
      - 将 role_function 改为 dominant_role_function
      - 新增 role_function_distribution 字段
      - 新增 dominant_role_ratio 字段
      - protagonist_score 和 is_protagonist 暂时为 None（Task 7 会实现）

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: protagonist-score-fusion
    修改内容:
      - 增加 arc_scores 和 main_characters 参数
      - 实现 protagonist_score 四维度融合计算
      - 实现 is_protagonist 判定逻辑

    修改时间: 2026-04-02
    修改者: TraeAI
    任务: P2.1-downstream-switch
    修改内容: 从 graph_entity_aliases 获取权威别名映射
    """
    # 从 graph_entity_aliases 获取权威别名映射
    graph_repo = GraphRepository(annotation_repo.session)
    alias_map = graph_repo.fetch_alias_map(run_id)

    rows = annotation_repo.fetch_characters_with_scores(run_id)

    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        name: str = str(row.name)
        canonical = alias_map.get(name, name)
        role_function: str = str(row.role_function) if row.role_function else "unknown"
        emotion_raw: str | None = str(row.emotion_score) if row.emotion_score else None
        emotion_score = EMOTION_SCORE_MAPPING.get(emotion_raw, 0) if emotion_raw else 0

        if canonical not in merged:
            merged[canonical] = {
                "count": 1,
                "role_function_counts": {role_function: 1},
                "weighted_score": emotion_score,
            }
        else:
            merged[canonical]["count"] += 1
            merged[canonical]["weighted_score"] += emotion_score
            rf_counts = merged[canonical]["role_function_counts"]
            rf_counts[role_function] = rf_counts.get(role_function, 0) + 1

    result = []
    for name, data in merged.items():
        avg_score = data["weighted_score"] / data["count"] if data["count"] > 0 else 0
        rf_counts = data["role_function_counts"]
        total_count = data["count"]
        dominant_role = max(rf_counts, key=lambda k: rf_counts[k] or 0)
        dominant_count = rf_counts[dominant_role]
        dominant_ratio = dominant_count / total_count if total_count > 0 else 0.0

        result.append(
            CharacterStats(
                name=name,
                appearance_count=int(total_count),
                dominant_role_function=dominant_role,
                role_function_distribution=rf_counts,
                dominant_role_ratio=dominant_ratio,
                protagonist_score=None,
                is_protagonist=None,
                avg_emotion_score=avg_score,
            )
        )

    result.sort(key=lambda x: x.appearance_count, reverse=True)

    if arc_scores is not None and main_characters is not None:
        result = _calculate_protagonist_scores(result, arc_scores, main_characters)

    if limit is None:
        return result
    return result[:limit]


def _fetch_topics(run_id: str, chunk_repo: ChunkRepository, alias_map: dict[str, str] | None = None) -> list:
    """
    获取主题数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 ChunkRepository

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 移除 db_path 参数，使用 run_id 作为模型目录标识

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: fix-json-output-issues-v3
    修改内容: 添加空主题过滤逻辑，过滤掉主题词列表为空的主题

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: fix-topics-alias-normalization
    修改内容: 添加 alias_map 参数，对主题词应用别名归一化
    """
    rows = chunk_repo.fetch_chunk_topics_agg(run_id)

    model_dir = Path("models") / "topic" / run_id
    topic_words_map: dict[int, list[str]] = {}
    topic_labels_map: dict[int, str] = {}

    if model_dir.exists():
        try:
            from src.topic import LDAConfig, LDATrainer

            trainer = LDATrainer(LDAConfig())
            topic_model = trainer.load_model(model_dir)
            for topic_id in range(topic_model.num_topics):
                topic_words = topic_model.get_topic_words(topic_id, top_n=10)
                topic_words_map[topic_id] = [w.word for w in topic_words]
                if topic_model.labels:
                    label = topic_model.labels.get(topic_id)
                    if label:
                        topic_labels_map[topic_id] = label
        except (FileNotFoundError, ImportError, OSError, ValueError) as e:
            logger.warning(f"Failed to load topic model: {e}")

    result: list[TopicInfo] = []
    for row in rows:
        topic_id = row.topic_id
        words: list[str] = topic_words_map.get(topic_id, [])
        words = _normalize_name_list(words, alias_map) or []
        label = topic_labels_map.get(topic_id)
        if words:
            result.append(TopicInfo(topic_id=topic_id, words=words, weight=row.total_weight, label=label))

    # 归一化权重：使所有主题权重之和为 1.0，便于前端展示为百分比分布
    if result:
        total_weight = sum(r.weight for r in result)
        if total_weight > 0:
            result = [
                TopicInfo(
                    topic_id=r.topic_id,
                    words=r.words,
                    weight=round(r.weight / total_weight, 6),
                    label=r.label,
                )
                for r in result
            ]

    return result


def _fetch_diagnosis(
    run_id: str, novel_id: str, stats_repo: StatsRepository, alias_map: dict[str, str] | None = None
) -> DiagnosisResult | None:
    """
    从数据库获取诊断结果

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 StatsRepository

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: fix-arc-scores-alias-inconsistency
    修改内容: 添加 alias_map 参数，对 arc_scores 的人物名称进行归一化

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: add-protagonist-fields-to-diagnosis
    修改内容: 添加 protagonist、main_characters、core_cast 字段的解析和别名归一化
    """
    data = stats_repo.fetch_cloud_analysis(novel_id, run_id)

    if not data:
        return None

    arc_scores_raw = _parse_json_field(data.get("arc_scores"))
    arc_scores_normalized = _normalize_arc_scores(arc_scores_raw, alias_map)
    topic_labels_raw = _parse_json_field(data.get("topic_labels"))
    topic_labels_normalized = (
        _normalize_name_list(topic_labels_raw, alias_map) if isinstance(topic_labels_raw, list) else topic_labels_raw
    )

    protagonist_raw = data.get("protagonist")
    protagonist_normalized = _normalize_name(protagonist_raw, alias_map)

    main_characters_raw = _parse_json_field(data.get("main_characters"))
    main_characters_normalized = (
        _normalize_name_list(main_characters_raw, alias_map)
        if isinstance(main_characters_raw, list)
        else main_characters_raw
    )

    core_cast_raw = _parse_json_field(data.get("core_cast"))
    core_cast_normalized = (
        _normalize_name_list(core_cast_raw, alias_map) if isinstance(core_cast_raw, list) else core_cast_raw
    )

    return DiagnosisResult(
        foreshadow_rate=data.get("foreshadow_rate"),
        arc_scores=arc_scores_normalized,
        narrative_type=data.get("narrative_type"),
        topic_labels=topic_labels_normalized,
        diagnosis=_normalize_text_by_alias_map(data.get("diagnosis"), alias_map),
        value_logic_type=data.get("value_logic_type"),
        value_logic_reason=_normalize_text_by_alias_map(data.get("value_logic_reason"), alias_map),
        power_stance_score=_parse_int_field(data.get("power_stance_score")),
        power_stance_reason=_normalize_text_by_alias_map(data.get("power_stance_reason"), alias_map),
        common_people_dignity=_parse_int_field(data.get("common_people_dignity")),
        dignity_reason=_normalize_text_by_alias_map(data.get("dignity_reason"), alias_map),
        cultural_depth_score=data.get("cultural_depth_score"),
        cultural_depth_reason=_normalize_text_by_alias_map(data.get("cultural_depth_reason"), alias_map),
        narrative_arc_type=data.get("narrative_arc_type"),
        protagonist=protagonist_normalized,
        main_characters=main_characters_normalized,
        core_cast=core_cast_normalized,
        theme_color=(theme_color.strip() if (theme_color := data.get("theme_color")) else None),
    )


def _fetch_chunk_styles(run_id: str, chunk_repo: ChunkRepository) -> list:
    """
    获取分块风格数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 ChunkRepository

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: fix-pause-density-d-value-equality
    修改内容: 使用字段名访问替代数字索引，避免索引错位问题
    """
    rows = chunk_repo.fetch_chunk_styles_full(run_id)
    return [
        ChunkStyle(
            chunk_id=row.chunk_id,
            mtld=row.mtld,
            ttr=row.ttr,
            avg_sent_len=row.avg_sent_len,
            d_value=row.d_value,
            pause_density=row.pause_density,
            fight_density=row.fight_density,
            dialogue_ratio=row.dialogue_ratio,
            sensory_density=row.sensory_density,
            metaphor_density=row.metaphor_density,
            imagery_lexicon_density=row.imagery_lexicon_density,
        )
        for row in rows
    ]


def _fetch_chunk_annotations(
    run_id: str,
    annotation_repo: AnnotationRepository,
    alias_map: dict[str, str] | None = None,
    valid_character_names: set[str] | None = None,
    export_graph_view: ExportGraphAuthorityView | None = None,
) -> list:
    """
    获取分块标注数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 AnnotationRepository

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: fix-character-alias-inconsistency
    修改内容: 添加 alias_map 参数，应用别名归一化，将外号替换为正式姓名

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: refactor-duplicate-normalize-name
    修改内容: 使用模块级 _normalize_name 函数替代内部定义

    修改时间: 2026-03-31
    修改者: TraeAI
    任务: refactor-hardcoded-index-access
    修改内容: 使用字段名访问替代硬编码索引
    """
    annotations_raw = annotation_repo.fetch_chunk_annotations_full(run_id)
    characters_raw = annotation_repo.fetch_chunk_characters_full(run_id)
    dialogues_raw = annotation_repo.fetch_chunk_dialogues_full(run_id)

    if export_graph_view is None:
        export_graph_view = (
            KnowledgeGraphAuthorityService.from_session(annotation_repo.session).build_export_view(run_id)
        )

    if not export_graph_view.relation_events:
        pending_relations = annotation_repo.fetch_pending_chunk_relations(run_id, limit=1)
        if pending_relations:
            raise RuntimeError(
                "graph relation events are empty while pending relations still exist; "
                "run graph projection before exporting results."
            )

    characters_by_chunk: dict[int, list[ChunkCharacter]] = defaultdict(list)
    for row in characters_raw:
        cid = row.chunk_id
        normalized_name = _normalize_name(str(row.name), alias_map)
        character_name = normalized_name if normalized_name else str(row.name)
        if valid_character_names is not None and character_name not in valid_character_names:
            logger.warning("跳过分块角色中的悬空引用: chunk_id={}, name={}", cid, character_name)
            continue
        characters_by_chunk[cid].append(
            ChunkCharacter(
                name=character_name,
                role_function=str(row.role_function) if row.role_function else None,
                action=str(row.action) if row.action else None,
                emotion_score=str(row.emotion_score) if row.emotion_score else None,
            )
        )

    relations_by_chunk: dict[int, list[ChunkRelation]] = defaultdict(list)
    for relation_event in export_graph_view.relation_events:
        cid = relation_event.chunk_id
        # 中文注释：authority relation event 已经是规范名，这里只保留 alias_map 兼容，
        # 避免旧数据里混入未完全收敛的别名时导出结果退化。
        from_char = _normalize_name(relation_event.from_name, alias_map) or relation_event.from_name
        to_char = _normalize_name(relation_event.to_name, alias_map) or relation_event.to_name
        if valid_character_names is not None and (
            from_char not in valid_character_names or to_char not in valid_character_names
        ):
            logger.warning(
                "跳过分块关系中的悬空引用: chunk_id={}, from_char={}, to_char={}",
                cid,
                from_char,
                to_char,
            )
            continue
        relations_by_chunk[cid].append(
            ChunkRelation(
                from_char=from_char,
                to_char=to_char,
                type=relation_event.relation_type,
                change=relation_event.change_type,
            )
        )

    dialogues_by_chunk: dict[int, list[ChunkDialogue]] = defaultdict(list)
    for row in dialogues_raw:
        cid = row.chunk_id
        speakers = row.speaker or []
        if not speakers:
            continue
        normalized_speakers = [_normalize_name(s, alias_map) for s in speakers]
        valid_speakers = []
        for normalized_speaker in normalized_speakers:
            if (
                normalized_speaker
                and valid_character_names is not None
                and normalized_speaker not in valid_character_names
            ):
                logger.warning(
                    "将分块对话中的悬空 speaker 置空: chunk_id={}, speaker={}",
                    cid,
                    normalized_speaker,
                )
                continue
            if normalized_speaker:
                valid_speakers.append(normalized_speaker)
        if not valid_speakers:
            continue
        dialogues_by_chunk[cid].append(
            ChunkDialogue(
                speaker=valid_speakers,
                length=int(row.length) if row.length is not None else None,
            )
        )

    result: list[ChunkAnnotation] = []
    for row in annotations_raw:
        chunk_id = int(row.chunk_id)
        result.append(
            ChunkAnnotation(
                chunk_id=chunk_id,
                emotional_valence=str(row.emotional_valence) if row.emotional_valence else None,
                event_type=str(row.event_type) if row.event_type else None,
                pivot_moment=bool(row.pivot_moment) if row.pivot_moment is not None else None,
                cliffhanger=bool(row.cliffhanger) if row.cliffhanger is not None else None,
                has_foreshadowing=bool(row.has_foreshadowing) if row.has_foreshadowing is not None else None,
                foreshadowing_type=str(row.foreshadowing_type) if row.foreshadowing_type else None,
                foreshadowing_desc=str(row.foreshadowing_desc) if row.foreshadowing_desc else None,
                characters=characters_by_chunk.get(chunk_id, []),
                relations=relations_by_chunk.get(chunk_id, []),
                dialogues=dialogues_by_chunk.get(chunk_id, []),
            )
        )

    return result


def _fetch_character_relations(
    run_id: str,
    annotation_repo: AnnotationRepository,
    alias_map: dict[str, str] | None = None,
    valid_character_names: set[str] | None = None,
    export_graph_view: ExportGraphAuthorityView | None = None,
) -> list:
    """获取角色关系数据（graph_relations_current 权威来源）。"""
    if export_graph_view is None:
        export_graph_view = (
            KnowledgeGraphAuthorityService.from_session(annotation_repo.session).build_export_view(run_id)
        )

    if not export_graph_view.current_relations:
        pending_relations = annotation_repo.fetch_pending_chunk_relations(run_id, limit=1)
        if pending_relations:
            raise RuntimeError(
                "graph current relations are empty while pending relations still exist; "
                "run graph projection before reading character relations."
            )

    result: list[CharacterRelation] = []
    for relation in export_graph_view.current_relations:
        from_char = _normalize_name(relation.from_name, alias_map) or relation.from_name
        to_char = _normalize_name(relation.to_name, alias_map) or relation.to_name
        if valid_character_names is not None and (
            from_char not in valid_character_names or to_char not in valid_character_names
        ):
            continue
        result.append(
            CharacterRelation(
                chunk_id=relation.last_seen_chunk,
                from_char=from_char,
                to_char=to_char,
                type=relation.relation_type,
                change="汇总",
            )
        )

    return result


def _fetch_hierarchical_relations(
    run_id: str,
    export_graph_view: ExportGraphAuthorityView,
    alias_map: dict[str, str] | None = None,
    valid_character_names: set[str] | None = None,
) -> list:
    """
    获取层级关系数据（father_of, son_of等）

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 添加层级关系导出到JSON功能
    说明: 从 graph_relation_current 表中获取层级关系类型

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: fix-character-dangling-reference
    修改内容: 添加 valid_character_names 参数，过滤悬空引用的关系

    修改时间: 2026-04-15
    修改者: Codex
    任务: export-graph-derived-authority
    修改内容: 改为消费 ExportGraphAuthorityView，避免导出层继续直连 repository/raw projection
    """
    hierarchical_types = {"child_of", "parent_of", "father_of", "son_of", "sibling_of", "spouse_of"}
    result = []
    for relation in export_graph_view.current_relations:
        rel_type = relation.relation_type
        if rel_type not in hierarchical_types:
            continue
        from_name_raw = relation.from_name
        to_name_raw = relation.to_name
        from_entity = _normalize_name(from_name_raw, alias_map) or from_name_raw
        to_entity = _normalize_name(to_name_raw, alias_map) or to_name_raw
        if valid_character_names is not None:
            if from_entity not in valid_character_names or to_entity not in valid_character_names:
                continue
        rel_id = relation.relation_id
        if rel_id is None:
            continue
        result.append(
            HierarchicalRelation(
                rel_id=rel_id,
                rel_type=rel_type,
                first_chunk=relation.first_seen_chunk,
                last_chunk=relation.last_seen_chunk,
                from_entity=from_entity,
                to_entity=to_entity,
            )
        )
    return result


def _fetch_global_stats(run_id: str, stats_repo: StatsRepository, chunk_repo: ChunkRepository) -> GlobalStats | None:
    """
    获取全局统计数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 StatsRepository 和 ChunkRepository
    """
    stats = stats_repo.fetch_global_stats_dict(run_id)
    total_chunks, total_chars = chunk_repo.fetch_chunk_counts(run_id)

    if not stats and total_chunks == 0:
        return None
    return GlobalStats(
        total_chunks=total_chunks,
        total_chars=total_chars,
        avg_mtld=stats.get("avg_mtld") or stats.get("global_avg_mtld"),
        avg_ttr=stats.get("avg_ttr") or stats.get("global_avg_ttr"),
        avg_sent_len=stats.get("avg_sent_len") or stats.get("global_avg_sent_len"),
        rhythm_avg=stats.get("rhythm_avg"),
        rhythm_std=stats.get("rhythm_std"),
        rhythm_max=stats.get("rhythm_max"),
        rhythm_min=stats.get("rhythm_min"),
        global_avg_sent_len=stats.get("global_avg_sent_len"),
        global_avg_ttr=stats.get("global_avg_ttr"),
    )


def _fetch_novel_name(run_id: str, novel_id: str, stats_repo: StatsRepository) -> str | None:
    """
    获取小说名称

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 StatsRepository
    """
    return stats_repo.fetch_novel_title(novel_id, run_id)


def _fetch_token_usage_stats(run_id: str, novel_id: str, stats_repo: StatsRepository) -> TokenUsageStats:
    """
    获取 token 使用统计

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 StatsRepository
    """
    try:
        stats = stats_repo.fetch_token_usage_stats(run_id, novel_id)
        summary = TokenUsageSummary(
            call_count=stats["summary"]["call_count"],
            total_prompt_tokens=stats["summary"]["total_prompt_tokens"],
            total_completion_tokens=stats["summary"]["total_completion_tokens"],
            total_tokens=stats["summary"]["total_tokens"],
        )
        by_task = {
            task: TokenUsageByTask(
                call_count=data["call_count"],
                total_tokens=data["total_tokens"],
            )
            for task, data in stats["by_task"].items()
        }
        by_model = {
            model: TokenUsageByModel(
                call_count=data["call_count"],
                total_tokens=data["total_tokens"],
            )
            for model, data in stats["by_model"].items()
        }
        return TokenUsageStats(
            summary=summary,
            by_task=by_task,
            by_model=by_model,
        )
    except Exception as e:
        logger.warning(f"Failed to fetch token usage stats: {e}")
        return TokenUsageStats()


def _fetch_known_characters(run_id: str, annotation_repo: AnnotationRepository) -> list[str]:
    """
    获取已知角色列表（规范名）

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 从 checkpoint 获取规范角色名列表

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: consolidate-codebase-architecture
    修改内容: 删除旧格式兼容代码，数据格式错误时抛出异常

    Args:
        run_id: 运行ID
        annotation_repo: 注解仓库

    Returns:
        规范角色名列表

    Raises:
        ValueError: checkpoint 数据格式无效
    """
    repo = DiagnosisRepository(annotation_repo.session)
    known_characters, _ = repo.fetch_character_disambig_data(run_id)
    return known_characters


def _fetch_alias_merges_only(run_id: str, annotation_repo: AnnotationRepository) -> dict[str, str]:
    """
    获取别名映射（只包含 alias != canonical）

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 从 checkpoint 获取真实别名映射

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: consolidate-codebase-architecture
    修改内容: 删除旧格式兼容代码，数据格式错误时抛出异常

    Args:
        run_id: 运行ID
        annotation_repo: 注解仓库

    Returns:
        别名到规范名的映射（只包含 alias != canonical）

    Raises:
        ValueError: checkpoint 数据格式无效
    """
    repo = DiagnosisRepository(annotation_repo.session)
    _, alias_merges = repo.fetch_character_disambig_data(run_id)
    return alias_merges


def _fetch_graph_snapshot(
    run_id: str,
    annotation_repo: AnnotationRepository,
    *,
    events_cursor: str | None = None,
    events_limit: int = GRAPH_PAGE_EVENT_LIMIT,
) -> dict[str, Any]:
    """获取知识图谱快照（nodes/edges/events/summary）。

    修改时间: 2026-04-05
    修改者: GLM-5
    修改内容: 将边数据转换为前端期望的格式（source/target/relation_type/weight）
    """
    pending_relations = annotation_repo.fetch_pending_chunk_relations(run_id, limit=1)
    if pending_relations:
        raise RuntimeError("graph projection is still pending; finish projection before reading graph snapshot.")

    authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
    graph_view = authority_service.build_graph_view(run_id)
    nodes = [
        {
            "entity_id": str(row.entity_id),
            "name": row.name,
            "entity_type": row.entity_type,
            "first_seen_chunk": row.first_seen_chunk,
            "last_seen_chunk": row.last_seen_chunk,
            "role": row.primary_role_function,
            "status": row.status,
        }
        for row in graph_view.stable_states
    ]

    edges = [
        {
            "source": str(edge.from_entity_id) if edge.from_entity_id is not None else edge.from_name,
            "target": str(edge.to_entity_id) if edge.to_entity_id is not None else edge.to_name,
            "relation_type": edge.relation_type,
            "weight": edge.support_count or 1,
            "from_name": edge.from_name,
            "to_name": edge.to_name,
            "change_count": edge.change_count,
            "tension_index": edge.tension_index,
            "is_active": edge.is_active,
        }
        for edge in graph_view.confirmed_relations
    ]

    # Keep page-facing history samples lightweight, but compute quality against
    # the full authority event history so long-running books do not hide older
    # low-confidence signals once they exceed the UI sample cap.
    paged_relation_events, events_page = _paginate_graph_relation_events(
        graph_view.relation_events,
        cursor=events_cursor,
        limit=events_limit,
    )
    events = [_serialize_graph_event(event) for event in paged_relation_events]
    # Graph page owns display-level summary/quality assembly. The authority
    # service intentionally stops at stable facts so product tweaks do not
    # contaminate downstream diagnosis/export contracts.
    # 中文注释：graph page 的 summary / quality 属于 product-layer contract，
    # 这里显式从 authority facts 组装页面 DTO，避免 diagnosis/export 共享层再被
    # 页面高亮或样本字段反向污染。
    summary = serialize_graph_page_summary(
        build_graph_page_summary(graph_view.stable_states, graph_view.confirmed_relations)
    )
    quality = serialize_graph_page_quality(
        build_graph_page_quality(graph_view.confirmed_relations, graph_view.relation_events)
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "events": events,
        "events_page": events_page,
        "summary": summary,
        "quality": quality,
    }


def _fetch_graph_events_page(
    run_id: str,
    annotation_repo: AnnotationRepository,
    *,
    events_cursor: str | None = None,
    events_limit: int = GRAPH_PAGE_EVENT_LIMIT,
) -> dict[str, Any]:
    """
    获取 graph page relation events 的增量分页结果。

    该 contract 仅属于 graph product surface。authority 仍然保留全量
    relation history，分页窗口只在页面层切片。
    """
    pending_relations = annotation_repo.fetch_pending_chunk_relations(run_id, limit=1)
    if pending_relations:
        raise RuntimeError("graph projection is still pending; finish projection before reading graph events.")

    authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
    graph_view = authority_service.build_graph_view(run_id)
    paged_relation_events, page_info = _paginate_graph_relation_events(
        graph_view.relation_events,
        cursor=events_cursor,
        limit=events_limit,
    )

    return {
        "events": [_serialize_graph_event(event) for event in paged_relation_events],
        "page_info": page_info,
    }
