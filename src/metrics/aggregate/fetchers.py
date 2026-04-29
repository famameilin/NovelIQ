"""
Aggregate Metrics 数据提取模块

提取所有数据提取函数

"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.models.local.character_reference_policy import decide_character_reference

from .types import (
    AnnotationData,
    CharacterData,
    CultureData,
    DialogueData,
    EmotionData,
    RelationData,
    StyleData,
    TensionData,
    TextData,
    map_emotion_score,
)

if TYPE_CHECKING:
    from src.knowledge.authority.types import Level1AuthoritySnapshot
    from src.storage.repositories import (
        AnnotationRepository,
        ChunkRepository,
        StatsRepository,
    )


def _build_aggregate_graph_view(
    annotation_repo: AnnotationRepository,
    run_id: str,
):
    """
    获取 aggregate 允许依赖的 graph authority view

    聚合指标属于 graph 下游消费者，只能读取 authority 暴露的稳定事实，
    不能再直接依赖 GraphRepository 的原始 row 形状
    """

    service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
    service.assert_graph_projection_ready(run_id)
    return service.build_graph_view(run_id)


def _build_aggregate_alias_lookup(snapshot: Level1AuthoritySnapshot) -> dict[str, str]:
    """
    构建 aggregate 可复用的 alias -> canonical 映射

    chunk 侧仍可能保留原文别名，但 aggregate 已经改成按 authority
    Level1 规范实体消费规范名，因此这里必须先把原始名字归一化，避免补充情绪分数
    和情绪序列时因为名称漂移被静默归零
    """

    return {
        mapping.alias: mapping.canonical for mapping in snapshot.alias_mappings if mapping.alias and mapping.canonical
    }


def _canonicalize_aggregate_character_name(name: str, alias_lookup: dict[str, str]) -> str:
    """将 chunk 侧角色名折叠到 authority 规范名"""

    return alias_lookup.get(name, name)


def _resolve_aggregate_character_name(
    *,
    surface_name: str | None,
    resolved_global_name: str | None,
    alias_lookup: dict[str, str],
) -> str | None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: aggregate 指标只能消费已准入的全局角色，不能把未解析代词重新混回情绪统计。
    """
    decision = decide_character_reference(
        surface_name,
        alias_map=alias_lookup,
        resolved_global_name=resolved_global_name,
    )
    return decision.resolved_global_name


def fetch_annotation_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> AnnotationData:
    """
    提取 chunk_annotation 表数据

    """
    rows = annotation_repo.fetch_full_annotations(run_id)

    return AnnotationData(
        chunk_ids=[row.chunk_id for row in rows],
        event_types=[row.event_type or "铺垫" for row in rows],
        cliffhangers=[row.cliffhanger or 0 for row in rows],
        pivot_moments=[row.pivot_moment or 0 for row in rows],
        emotional_valences=[row.emotional_valence or "neutral" for row in rows],
    )


def fetch_emotion_data(
    stats_repo: StatsRepository,
    run_id: str,
) -> EmotionData:
    """
    提取 chunk_curves 表数据

    """
    rows = stats_repo.fetch_chunk_curves_full(run_id)
    emotion_values = [row.net_density for row in rows]

    density_rows = stats_repo.fetch_emotion_densities(run_id)
    pos_densities = [row.pos_density for row in density_rows if row.pos_density is not None]
    neg_densities = [row.neg_density for row in density_rows if row.neg_density is not None]

    return EmotionData(
        emotion_values=emotion_values,
        pos_densities=pos_densities,
        neg_densities=neg_densities,
    )


def fetch_character_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> CharacterData:
    """
    提取角色数据

    避免 aggregate character stats 依赖 graph participant state 过滤结果
    """
    authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
    snapshot = authority_service.build_level1_snapshot(run_id)
    alias_lookup = _build_aggregate_alias_lookup(snapshot)
    active_characters = [
        entity
        for entity in snapshot.canonical_entities
        if entity.entity_type == "character" and entity.status == "active"
    ]

    # 2. 从 chunk_characters 聚合情感分数（用于补充）
    rows = annotation_repo.fetch_characters_with_scores(run_id)
    emotion_map: dict[str, int] = {}
    for row in rows:
        canonical_name = _resolve_aggregate_character_name(
            surface_name=getattr(row, "surface_name", None) or getattr(row, "name", None),
            resolved_global_name=getattr(row, "resolved_global_name", None),
            alias_lookup=alias_lookup,
        )
        if canonical_name is None:
            continue
        emotion_score_raw = getattr(row, "emotion_score", None)
        emotion_map[canonical_name] = map_emotion_score(emotion_score_raw)

    # 3. 构建角色列表（使用 Level1 canonical entity 作为完整角色种子）
    characters = []
    for entity in active_characters:
        emotion_score = emotion_map.get(entity.name, 0)
        characters.append((entity.name, entity.primary_role_function or "其他", emotion_score))

    # 4. 构建情感序列（仍从 chunk_characters 获取）
    char_emotion_rows = annotation_repo.fetch_character_emotion_sequence(run_id)
    char_emotion_map: dict[str, list[float]] = {}
    for row in char_emotion_rows:
        canonical_name = _resolve_aggregate_character_name(
            surface_name=getattr(row, "surface_name", None) or getattr(row, "name", None),
            resolved_global_name=getattr(row, "resolved_global_name", None),
            alias_lookup=alias_lookup,
        )
        if canonical_name is None:
            continue
        if canonical_name not in char_emotion_map:
            char_emotion_map[canonical_name] = []
        score = float(map_emotion_score(getattr(row, "emotion_score", None)))
        char_emotion_map[canonical_name].append(score)
    char_emotion_scores = list(char_emotion_map.items())

    return CharacterData(
        characters=characters,
        char_emotion_scores=char_emotion_scores,
    )


# 2026-04-28，任务：统一关系图谱密度口径。
# 修改原因：aggregate 之前只看有边的节点，导致孤立参与者不会进入密度分母，
# 和 graph page 基于整张参与者子图的展示口径对不上。
def fetch_relation_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> RelationData:
    """提取 graph_* 关系数据（权威来源）"""
    graph_view = _build_aggregate_graph_view(annotation_repo, run_id)
    current_relations = list(graph_view.confirmed_relations)
    relation_events = list(graph_view.relation_events)

    return RelationData(
        relations=[(relation.from_name, relation.to_name) for relation in current_relations],
        full_relations=[
            (event.from_name, event.to_name, event.relation_type, event.change_type) for event in relation_events
        ],
        participant_names=[state.name for state in graph_view.participant_states if state.name],
    )


def fetch_text_data(
    chunk_repo: ChunkRepository,
    run_id: str,
) -> TextData:
    """提取 chunks 表文本数据"""
    texts = chunk_repo.fetch_all_chunk_texts(run_id)

    all_tokens: list[str] = []
    for text in texts:
        tokens = re.findall(r"[\u4e00-\u9fa5]+|[a-zA-Z]+", text)
        all_tokens.extend(tokens)

    return TextData(texts=texts, all_tokens=all_tokens)


def fetch_culture_data(
    stats_repo: StatsRepository,
    run_id: str,
) -> CultureData:
    """
    提取 chunk_culture 表数据

    """
    culture_rows = stats_repo.fetch_chunk_culture(run_id)
    imagery_densities = [row.imagery_lexicon_density for row in culture_rows if row.imagery_lexicon_density is not None]

    return CultureData(
        imagery_densities=imagery_densities,
    )


def fetch_tension_data(
    stats_repo: StatsRepository,
    run_id: str,
) -> TensionData:
    """
    提取 chunk_curves 表的 tension_composite 数据

    """
    rows = stats_repo.fetch_chunk_curves_full(run_id)
    tension_composite_scores = [row.tension_composite for row in rows if row.tension_composite is not None]
    return TensionData(tension_composite_scores=tension_composite_scores)


def fetch_dialogue_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> DialogueData:
    """
    提取 chunk_dialogues 表的 tone 数据

    从对话表获取语气类型数据用于聚合计算

    """
    rows = annotation_repo.fetch_chunk_dialogues_full(run_id)
    tones = [row.tone for row in rows if row.tone is not None]
    return DialogueData(tones=tones)


def fetch_style_data(
    chunk_repo: ChunkRepository,
    run_id: str,
) -> StyleData:
    """
    提取 chunk_styles 表的风格指标数据

    从 chunk_styles 表获取 dialogue_ratio 和 avg_sent_len 数据用于聚合计算
    """
    rows = chunk_repo.fetch_chunk_styles(run_id)
    dialogue_ratios = [row.dialogue_ratio for row in rows if row.dialogue_ratio is not None]
    avg_sent_lens = [row.avg_sent_len for row in rows if row.avg_sent_len is not None]
    return StyleData(dialogue_ratios=dialogue_ratios, avg_sent_lens=avg_sent_lens)
