"""
数据获取函数

创建时间: 2026-03-28
创建者: TraeAI
任务: consolidate-codebase-architecture
说明: 从 results_fetchers.py 拆分，包含数据获取相关函数
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from loguru import logger

from src.api.models.responses import (
    CharacterRelation,
    CharacterStats,
    ChunkAnnotation,
    ChunkCharacter,
    ChunkCulture,
    ChunkDialogue,
    ChunkRelation,
    ChunkStyle,
    DiagnosisResult,
    EmotionCurvePoint,
    GlobalStats,
    HierarchicalRelation,
    RhythmCurvePoint,
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
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    EntityRepository,
    GraphRepository,
    StatsRepository,
)


def _fetch_emotion_curve(run_id: str, stats_repo: StatsRepository) -> list:
    """
    获取情绪曲线数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 StatsRepository
    """
    rows = stats_repo.fetch_emotion_curve_full(run_id)
    return [
        EmotionCurvePoint(
            chunk_id=row[0], pos_density=row[1], neg_density=row[2], net_density=row[3], smoothed_density=row[4]
        )
        for row in rows
    ]


def _fetch_rhythm_curve(run_id: str, stats_repo: StatsRepository) -> list:
    """
    获取节奏曲线数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 StatsRepository
    """
    rows = stats_repo.fetch_rhythm_curve_full(run_id)
    return [RhythmCurvePoint(chunk_id=row[0], tension_proxy=row[1], tension_composite=row[2]) for row in rows]


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
    """
    alias_map = annotation_repo.fetch_alias_map(run_id)

    rows = annotation_repo.fetch_characters_with_scores(run_id)

    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        name: str = str(row[0])
        canonical = alias_map.get(name, name)
        role_function: str = str(row[1]) if row[1] else "unknown"
        emotion_raw: str | None = str(row[2]) if row[2] else None
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
        dominant_role = max(rf_counts, key=rf_counts.get)
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


def _fetch_topics(
    run_id: str, chunk_repo: ChunkRepository, alias_map: dict[str, str] | None = None
) -> list:
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
    topic_words_map = {}

    if model_dir.exists():
        try:
            from src.topic import LDAConfig, LDATrainer

            trainer = LDATrainer(LDAConfig())
            topic_model = trainer.load_model(model_dir)
            for topic_id in range(topic_model.num_topics):
                topic_words = topic_model.get_topic_words(topic_id, top_n=10)
                topic_words_map[topic_id] = [w.word for w in topic_words]
        except Exception as e:
            logger.warning(f"Failed to load topic model: {e}")

    result: list[TopicInfo] = []
    for row in rows:
        topic_id = row[0]
        words: list[str] = topic_words_map.get(topic_id, [])
        words = _normalize_name_list(words, alias_map) or []
        if words:
            result.append(TopicInfo(topic_id=topic_id, words=words, weight=row[1]))

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
        _normalize_name_list(main_characters_raw, alias_map) if isinstance(main_characters_raw, list) else main_characters_raw
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
        )
        for row in rows
    ]


def _fetch_chunk_annotations(
    run_id: str,
    annotation_repo: AnnotationRepository,
    alias_map: dict[str, str] | None = None,
    valid_character_names: set[str] | None = None,
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
    """
    annotations_raw = annotation_repo.fetch_chunk_annotations_full(run_id)
    characters_raw = annotation_repo.fetch_chunk_characters_full(run_id)
    dialogues_raw = annotation_repo.fetch_chunk_dialogues_full(run_id)

    relation_events_raw: list[dict[str, Any]] = []
    if hasattr(annotation_repo, "session"):
        graph_repo = GraphRepository(annotation_repo.session)
        relation_events_raw = graph_repo.fetch_relation_events(run_id)

    characters_by_chunk: dict[int, list[ChunkCharacter]] = defaultdict(list)
    for row in characters_raw:
        cid = row[0]
        normalized_name = _normalize_name(str(row[1]), alias_map)
        character_name = normalized_name if normalized_name else str(row[1])
        if valid_character_names is not None and character_name not in valid_character_names:
            logger.warning("跳过分块角色中的悬空引用: chunk_id={}, name={}", cid, character_name)
            continue
        characters_by_chunk[cid].append(
            ChunkCharacter(
                name=character_name,
                role_function=str(row[2]) if row[2] else None,
                action=str(row[3]) if row[3] else None,
                emotion_score=str(row[4]) if row[4] else None,
            )
        )

    relations_by_chunk: dict[int, list[ChunkRelation]] = defaultdict(list)
    for row in relation_events_raw:
        cid = int(row["chunk_id"])
        from_name_raw = str(row["from_name"])
        to_name_raw = str(row["to_name"])
        from_normalized = _normalize_name(from_name_raw, alias_map)
        to_normalized = _normalize_name(to_name_raw, alias_map)
        from_char = from_normalized if from_normalized else from_name_raw
        to_char = to_normalized if to_normalized else to_name_raw
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
                type=str(row["relation_type"]) if row.get("relation_type") else "",
                change=str(row["change_type"]) if row.get("change_type") else "",
            )
        )

    dialogues_by_chunk: dict[int, list[ChunkDialogue]] = defaultdict(list)
    for row in dialogues_raw:
        cid = row[0]
        speaker = row[1] if row[1] else None
        normalized_speaker = _normalize_name(speaker, alias_map)
        if normalized_speaker and valid_character_names is not None and normalized_speaker not in valid_character_names:
            logger.warning("将分块对话中的悬空 speaker 置空: chunk_id={}, speaker={}", cid, normalized_speaker)
            normalized_speaker = None
        if normalized_speaker is None:
            continue
        dialogues_by_chunk[cid].append(
            ChunkDialogue(
                speaker=normalized_speaker,
                length=int(row[2]) if row[2] is not None else None,
            )
        )

    result: list[ChunkAnnotation] = []
    for row in annotations_raw:
        chunk_id = int(row[0])
        result.append(
            ChunkAnnotation(
                chunk_id=chunk_id,
                emotional_valence=str(row[1]) if row[1] else None,
                event_type=str(row[2]) if row[2] else None,
                pivot_moment=bool(row[3]) if row[3] is not None else None,
                cliffhanger=bool(row[4]) if row[4] is not None else None,
                has_foreshadowing=bool(row[5]) if row[5] is not None else None,
                foreshadowing_type=str(row[6]) if row[6] else None,
                foreshadowing_desc=str(row[7]) if row[7] else None,
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
) -> list:
    """获取角色关系数据（graph_relations_current 权威来源）。"""
    if not hasattr(annotation_repo, "session"):
        return []

    graph_repo = GraphRepository(annotation_repo.session)
    graph_relations = graph_repo.fetch_current_relations(run_id, active_only=False)

    result: list[CharacterRelation] = []
    for row in graph_relations:
        from_char = _normalize_name(row["from_name"], alias_map) or row["from_name"]
        to_char = _normalize_name(row["to_name"], alias_map) or row["to_name"]
        if valid_character_names is not None and (
            from_char not in valid_character_names or to_char not in valid_character_names
        ):
            continue
        result.append(
            CharacterRelation(
                chunk_id=row["last_seen_chunk"],
                from_char=from_char,
                to_char=to_char,
                type=row["type"],
                change="汇总",
            )
        )

    return result


def _fetch_hierarchical_relations(
    novel_id: str,
    run_id: str,
    entity_repo: EntityRepository,
    valid_character_names: set[str] | None = None,
) -> list:
    """
    获取层级关系数据（father_of, son_of等）

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 添加层级关系导出到JSON功能
    说明: 从entity_relations表中获取层级关系类型

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: fix-character-dangling-reference
    修改内容: 添加 valid_character_names 参数，过滤悬空引用的关系
    """
    relations = entity_repo.fetch_hierarchical_relations_with_names(novel_id, run_id)
    result = []
    for rel in relations:
        from_entity = rel["from_entity"]
        to_entity = rel["to_entity"]
        if valid_character_names is not None:
            if from_entity not in valid_character_names or to_entity not in valid_character_names:
                logger.warning(
                    f"跳过悬空引用的层级关系: rel_id={rel['rel_id']}, "
                    f"from_entity={from_entity}, to_entity={to_entity}"
                )
                continue
        result.append(
            HierarchicalRelation(
                rel_id=rel["rel_id"],
                rel_type=rel["rel_type"],
                first_chunk=rel["first_chunk"],
                last_chunk=rel["last_chunk"],
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


def _fetch_chunk_cultures(run_id: str, chunk_repo: ChunkRepository) -> list:
    """
    获取分块文化数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 ChunkRepository

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 简化文化指标系统
    修改内容: 只返回 imagery_lexicon_density
    """
    rows = chunk_repo.fetch_chunk_cultures_full(run_id)
    return [
        ChunkCulture(
            chunk_id=row[0],
            imagery_lexicon_density=row[1],
        )
        for row in rows
    ]


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
    from sqlalchemy import text

    result = annotation_repo.session.execute(
        text("SELECT alias_map FROM disambig_checkpoint WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).fetchone()

    if not result or not result[0]:
        return []

    raw_data = json.loads(result[0])

    if not isinstance(raw_data, dict):
        raise ValueError(
            f"Invalid checkpoint data format for run_id={run_id}: "
            f"expected dict, got {type(raw_data).__name__}"
        )

    if "known_canonical_names" not in raw_data:
        raise ValueError(f"Missing 'known_canonical_names' in checkpoint data for run_id={run_id}")

    known_canonical_names = raw_data.get("known_canonical_names")
    if not isinstance(known_canonical_names, list):
        raise ValueError(
            f"Invalid 'known_canonical_names' format for run_id={run_id}: "
            f"expected list, got {type(known_canonical_names).__name__}"
        )

    return known_canonical_names


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
    from sqlalchemy import text

    result = annotation_repo.session.execute(
        text("SELECT alias_map FROM disambig_checkpoint WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).fetchone()

    if not result or not result[0]:
        return {}

    raw_data = json.loads(result[0])

    if not isinstance(raw_data, dict):
        raise ValueError(
            f"Invalid checkpoint data format for run_id={run_id}: "
            f"expected dict, got {type(raw_data).__name__}"
        )

    if "alias_merges" not in raw_data:
        raise ValueError(f"Missing 'alias_merges' in checkpoint data for run_id={run_id}")

    alias_merges_list = raw_data.get("alias_merges")
    if not isinstance(alias_merges_list, list):
        raise ValueError(
            f"Invalid 'alias_merges' format for run_id={run_id}: "
            f"expected list, got {type(alias_merges_list).__name__}"
        )

    return {alias: canonical for alias, canonical in alias_merges_list if alias != canonical}
