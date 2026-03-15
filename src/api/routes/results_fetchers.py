"""
创建时间: 2026-03-11
创建者: Claude
任务: API 路由数据获取函数
说明: 从数据库获取分析结果的辅助函数

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-routes-use-repository
修改内容: 重构为使用 Repository 模式，所有函数添加 run_id 参数支持
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from src.config import settings
from src.api.models.responses import (
    EmotionCurvePoint,
    RhythmCurvePoint,
    CharacterStats,
    TopicInfo,
    DiagnosisResult,
    ChunkStyle,
    ChunkAnnotation,
    ChunkCharacter,
    ChunkRelation,
    ChunkDialogue,
    CharacterRelation,
    GlobalStats,
    ChunkCulture,
    TokenUsageStats,
    TokenUsageSummary,
    TokenUsageByTask,
    TokenUsageByModel,
)
from src.storage.repositories import (
    StatsRepository,
    AnnotationRepository,
    ChunkRepository,
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


def _parse_int_field(value: Any) -> Optional[int]:
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
    return [
        RhythmCurvePoint(chunk_id=row[0], tension_proxy=row[1], tension_composite=row[2]) for row in rows
    ]


def _fetch_characters(run_id: str, annotation_repo: AnnotationRepository) -> list:
    """
    获取角色统计数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 AnnotationRepository
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

    merged: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name: str = str(row[0])
        canonical = alias_map.get(name, name)
        role_function: str = str(row[1]) if row[1] else "unknown"
        emotion_raw: Optional[str] = str(row[2]) if row[2] else None
        emotion_score = emotion_score_mapping.get(emotion_raw, 0) if emotion_raw else 0

        if canonical not in merged:
            merged[canonical] = {
                "count": 1,
                "role_function": role_function,
                "weighted_score": emotion_score,
            }
        else:
            merged[canonical]["count"] += 1
            merged[canonical]["weighted_score"] += emotion_score

    result = []
    for name, data in merged.items():
        avg_score = data["weighted_score"] / data["count"] if data["count"] > 0 else 0
        result.append(
            CharacterStats(
                name=name,
                appearance_count=int(data["count"]),
                role_function=str(data["role_function"]) or "unknown",
                avg_emotion_score=avg_score,
            )
        )

    result.sort(key=lambda x: x.appearance_count, reverse=True)
    return result[: settings.api.query_limit]


def _fetch_topics(run_id: str, chunk_repo: ChunkRepository) -> list:
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
    """
    rows = chunk_repo.fetch_chunk_topics_agg(run_id)

    model_dir = Path("models") / "topic" / run_id
    topic_words_map = {}

    if model_dir.exists():
        try:
            from src.topic import LDATrainer, LDAConfig

            trainer = LDATrainer(LDAConfig())
            topic_model = trainer.load_model(model_dir)
            for topic_id in range(topic_model.num_topics):
                words = topic_model.get_topic_words(topic_id, top_n=10)
                topic_words_map[topic_id] = [w.word for w in words]
        except Exception as e:
            logger.warning(f"Failed to load topic model: {e}")

    return [TopicInfo(topic_id=row[0], words=topic_words_map.get(row[0], []), weight=row[1]) for row in rows]


def _fetch_diagnosis(run_id: str, novel_id: str, stats_repo: StatsRepository) -> DiagnosisResult | None:
    """
    从数据库获取诊断结果

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 StatsRepository
    """
    data = stats_repo.fetch_cloud_analysis(novel_id, run_id)

    if not data:
        return None

    return DiagnosisResult(
        foreshadow_rate=data.get("foreshadow_rate"),
        arc_scores=_parse_json_field(data.get("arc_scores")),
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
        emotion_curve_type=data.get("emotion_curve_type"),
    )


def _fetch_chunk_styles(run_id: str, chunk_repo: ChunkRepository) -> list:
    """
    获取分块风格数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 ChunkRepository
    """
    rows = chunk_repo.fetch_chunk_styles_full(run_id)
    return [
        ChunkStyle(
            chunk_id=row[0],
            mtld=row[1],
            ttr=row[2],
            avg_sent_len=row[3],
            d_value=row[4],
            pause_density=row[5],
            fight_density=row[6],
            dialogue_ratio=row[7],
            sensory_density=row[8],
            metaphor_density=row[9],
            cultural_density=row[10],
        )
        for row in rows
    ]


def _fetch_chunk_annotations(run_id: str, annotation_repo: AnnotationRepository) -> list:
    """
    获取分块标注数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 AnnotationRepository
    """
    annotations_raw = annotation_repo.fetch_chunk_annotations_full(run_id)
    characters_raw = annotation_repo.fetch_chunk_characters_full(run_id)
    relations_raw = annotation_repo.fetch_chunk_relations_full(run_id)
    dialogues_raw = annotation_repo.fetch_chunk_dialogues_full(run_id)

    characters_by_chunk: Dict[int, List[ChunkCharacter]] = defaultdict(list)
    for row in characters_raw:
        cid = row[0]
        characters_by_chunk[cid].append(
            ChunkCharacter(
                name=str(row[1]),
                role_function=str(row[2]) if row[2] else None,
                action=str(row[3]) if row[3] else None,
                emotion_score=str(row[4]) if row[4] else None
            )
        )

    relations_by_chunk: Dict[int, List[ChunkRelation]] = defaultdict(list)
    for row in relations_raw:
        cid = row[0]
        relations_by_chunk[cid].append(
            ChunkRelation(
                from_char=str(row[1]),
                to_char=str(row[2]),
                type=str(row[3]) if row[3] else "",
                change=str(row[4]) if row[4] else ""
            )
        )

    dialogues_by_chunk: Dict[int, List[ChunkDialogue]] = defaultdict(list)
    for row in dialogues_raw:
        cid = row[0]
        dialogues_by_chunk[cid].append(
            ChunkDialogue(
                speaker=str(row[1]),
                tone=None,
                length=int(row[2]) if row[2] is not None else None
            )
        )

    result: List[ChunkAnnotation] = []
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


def _fetch_character_relations(run_id: str, annotation_repo: AnnotationRepository) -> list:
    """
    获取角色关系数据

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: refactor-routes-use-repository
    修改内容: 重构为使用 AnnotationRepository
    """
    rows = annotation_repo.fetch_chunk_relations_full(run_id)
    return [
        CharacterRelation(chunk_id=int(row[0]), from_char=str(row[1]), to_char=str(row[2]), type=str(row[3]) if row[3] else "", change=str(row[4]) if row[4] else "")
        for row in rows
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
    """
    rows = chunk_repo.fetch_chunk_cultures_full(run_id)
    return [
        ChunkCulture(
            chunk_id=row[0],
            confucian_density=row[1],
            taoist_density=row[2],
            buddhist_density=row[3],
            folk_density=row[4],
            allusion_density=row[5],
        )
        for row in rows
    ]


def _fetch_novel_name(run_id: str, novel_id: str, stats_repo: StatsRepository) -> Optional[str]:
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
