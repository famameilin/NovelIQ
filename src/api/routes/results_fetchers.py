"""
创建时间: 2026-03-11
创建者: Claude
任务: API 路由数据获取函数
说明: 从数据库获取分析结果的辅助函数

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-routes-use-repository
修改内容: 重构为使用 Repository 模式，所有函数添加 run_id 参数支持

修改时间: 2026-03-19
修改者: TraeAI
任务: 添加层级关系导出到JSON功能
修改内容: 添加 _fetch_hierarchical_relations 函数和 HierarchicalRelation 导入
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
from src.config import settings
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    EntityRepository,
    StatsRepository,
)


def _parse_json_field(value: Any) -> Any:
    """解析 JSON 字段，处理可能的异常

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-diagnosis-hardcoded-index
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def _parse_int_field(value: Any) -> int | None:
    """解析整数字段，处理可能的异常

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-diagnosis-hardcoded-index
    """
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _normalize_name(name: str | None, alias_map: dict[str, str] | None) -> str | None:
    """
    别名归一化函数

    如果提供了 alias_map 且 name 存在于映射中，则返回规范名；
    否则返回原始名称。

    创建时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-duplicate-normalize-name
    修改内容: 提取重复的 normalize_name 函数为模块级函数

    Args:
        name: 待归一化的名称
        alias_map: 别名到规范名的映射字典

    Returns:
        归一化后的名称
    """
    if name is None:
        return None
    if alias_map and name in alias_map:
        return alias_map[name]
    return name


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


def _fetch_characters(run_id: str, annotation_repo: AnnotationRepository) -> list:
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
    """
    alias_map = annotation_repo.fetch_alias_map(run_id)

    emotion_score_mapping = {
        "strong_positive": 2,
        "mild_positive": 1,
        "neutral": 0,
        "mild_negative": -1,
        "strong_negative": -2,
    }

    rows = annotation_repo.fetch_characters_with_scores(run_id)

    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        name: str = str(row[0])
        canonical = alias_map.get(name, name)
        role_function: str = str(row[1]) if row[1] else "unknown"
        emotion_raw: str | None = str(row[2]) if row[2] else None
        emotion_score = emotion_score_mapping.get(emotion_raw, 0) if emotion_raw else 0

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
        majority_role = max(rf_counts, key=rf_counts.get)
        result.append(
            CharacterStats(
                name=name,
                appearance_count=int(data["count"]),
                role_function=majority_role,
                avg_emotion_score=avg_score,
            )
        )

    result.sort(key=lambda x: x.appearance_count, reverse=True)
    return result[: settings.api.query_limit]


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
        if alias_map:
            words = [alias_map.get(w, w) for w in words]
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
    """
    data = stats_repo.fetch_cloud_analysis(novel_id, run_id)

    if not data:
        return None

    arc_scores_raw = _parse_json_field(data.get("arc_scores"))
    arc_scores_normalized = _normalize_arc_scores(arc_scores_raw, alias_map)

    return DiagnosisResult(
        foreshadow_rate=data.get("foreshadow_rate"),
        arc_scores=arc_scores_normalized,
        narrative_type=data.get("narrative_type"),
        topic_labels=_parse_json_field(data.get("topic_labels")),
        diagnosis=data.get("diagnosis"),
        value_logic_type=data.get("value_logic_type"),
        value_logic_reason=data.get("value_logic_reason"),
        power_stance_score=_parse_int_field(data.get("power_stance_score")),
        power_stance_reason=data.get("power_stance_reason"),
        common_people_dignity=_parse_int_field(data.get("common_people_dignity")),
        dignity_reason=data.get("dignity_reason"),
        cultural_depth_score=data.get("cultural_depth_score"),
        cultural_depth_reason=data.get("cultural_depth_reason"),
        narrative_arc_type=data.get("narrative_arc_type"),
    )


def _normalize_arc_scores(arc_scores: Any, alias_map: dict[str, str] | None) -> dict[str, float] | list[float]:
    """
    对 arc_scores 的人物名称进行归一化

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: fix-arc-scores-alias-inconsistency
    说明: 将 arc_scores 中的人物绰号替换为规范名，保持与角色表一致

    Args:
        arc_scores: 原始 arc_scores 数据，可能是 dict 或 list
        alias_map: 别名到规范名的映射字典

    Returns:
        归一化后的 arc_scores
    """
    if not arc_scores:
        return arc_scores

    if isinstance(arc_scores, list):
        return arc_scores

    if not isinstance(arc_scores, dict):
        return arc_scores

    if not alias_map:
        return arc_scores

    normalized: dict[str, float] = {}
    for name, score in arc_scores.items():
        if not isinstance(name, str):
            continue
        canonical_name = alias_map.get(name, name)
        normalized[canonical_name] = score

    return normalized


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
    run_id: str, annotation_repo: AnnotationRepository, alias_map: dict[str, str] | None = None
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
    relations_raw = annotation_repo.fetch_chunk_relations_full(run_id)
    dialogues_raw = annotation_repo.fetch_chunk_dialogues_full(run_id)

    characters_by_chunk: dict[int, list[ChunkCharacter]] = defaultdict(list)
    for row in characters_raw:
        cid = row[0]
        normalized_name = _normalize_name(str(row[1]), alias_map)
        characters_by_chunk[cid].append(
            ChunkCharacter(
                name=normalized_name if normalized_name else str(row[1]),
                role_function=str(row[2]) if row[2] else None,
                action=str(row[3]) if row[3] else None,
                emotion_score=str(row[4]) if row[4] else None,
            )
        )

    relations_by_chunk: dict[int, list[ChunkRelation]] = defaultdict(list)
    for row in relations_raw:
        cid = row[0]
        from_normalized = _normalize_name(str(row[1]), alias_map)
        to_normalized = _normalize_name(str(row[2]), alias_map)
        relations_by_chunk[cid].append(
            ChunkRelation(
                from_char=from_normalized if from_normalized else str(row[1]),
                to_char=to_normalized if to_normalized else str(row[2]),
                type=str(row[3]) if row[3] else "",
                change=str(row[4]) if row[4] else "",
            )
        )

    dialogues_by_chunk: dict[int, list[ChunkDialogue]] = defaultdict(list)
    for row in dialogues_raw:
        cid = row[0]
        speaker = row[1] if row[1] else None
        dialogues_by_chunk[cid].append(
            ChunkDialogue(
                speaker=_normalize_name(speaker, alias_map),
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
    run_id: str, annotation_repo: AnnotationRepository, alias_map: dict[str, str] | None = None
) -> list:
    """
    获取角色关系数据

    修改时间: 2026-03-14
    创建者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 AnnotationRepository

    修改时间: 2026-03-19
    创建者: TraeAI
    任务: fix-json-output-issues-v3
    修改内容: 添加去重逻辑，避免同一对人物在同一chunk中出现重复关系

    修改时间: 2026-03-19
    创建者: TraeAI
    任务: fix-character-alias-inconsistency
    修改内容: 添加 alias_map 参数，应用别名归一化，将外号替换为正式姓名

    修改时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-duplicate-normalize-name
    修改内容: 使用模块级 _normalize_name 函数替代内部定义
    """
    rows = annotation_repo.fetch_chunk_relations_full(run_id)

    # 去重：基于 chunk_id + from_char + to_char + type 去重，保留最后出现的记录
    seen: dict[tuple, CharacterRelation] = {}
    for row in rows:
        chunk_id = int(row[0])
        from_normalized = _normalize_name(str(row[1]), alias_map)
        to_normalized = _normalize_name(str(row[2]), alias_map)
        from_char = from_normalized if from_normalized else str(row[1])
        to_char = to_normalized if to_normalized else str(row[2])
        rel_type = str(row[3]) if row[3] else ""
        change = str(row[4]) if row[4] else ""

        # 使用 (chunk_id, from_char, to_char, type) 作为去重键
        key = (chunk_id, from_char, to_char, rel_type)
        seen[key] = CharacterRelation(
            chunk_id=chunk_id,
            from_char=from_char,
            to_char=to_char,
            type=rel_type,
            change=change,
        )

    return list(seen.values())


def _fetch_hierarchical_relations(novel_id: str, run_id: str, entity_repo: EntityRepository) -> list:
    """
    获取层级关系数据（father_of, son_of等）

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 添加层级关系导出到JSON功能
    说明: 从entity_relations表中获取层级关系类型
    """
    relations = entity_repo.fetch_hierarchical_relations_with_names(novel_id, run_id)
    return [
        HierarchicalRelation(
            rel_id=rel["rel_id"],
            rel_type=rel["rel_type"],
            first_chunk=rel["first_chunk"],
            last_chunk=rel["last_chunk"],
            from_entity=rel["from_entity"],
            to_entity=rel["to_entity"],
        )
        for rel in relations
    ]


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
