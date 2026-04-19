"""
Aggregate Metrics 数据提取模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
说明: 提取所有数据提取函数

修改历史:
- 2026-03-13: 创建数据提取函数 (refactor-metrics-layer-functions)
- 2026-03-13: event_type 默认值改为"铺垫" (chunk-annotation-schema-refactor)
- 2026-03-14: 使用 Repository 接口 (metrics-repository-refactor)
- 2026-03-18: 提取为独立模块函数 (code-quality-refactor Task 11)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.knowledge.authority import KnowledgeGraphAuthorityService

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
    获取 aggregate 允许依赖的 graph authority view。

    中文注释：聚合指标属于 graph 下游消费者，只能读取 authority 暴露的稳定事实，
    不能再直接依赖 GraphRepository 的原始 row 形状。
    """

    return KnowledgeGraphAuthorityService.from_session(annotation_repo.session).build_graph_view(run_id)


def _build_aggregate_alias_lookup(
    authority_service: KnowledgeGraphAuthorityService,
    run_id: str,
) -> dict[str, str]:
    """
    构建 aggregate 可复用的 alias -> canonical 映射。

    中文注释：chunk 侧仍可能保留原文别名，但 aggregate 已经改成按 authority
    stable state 消费规范名，因此这里必须先把原始名字归一化，避免补充情绪分数
    和情绪序列时因为名称漂移被静默归零。
    """

    snapshot = authority_service.build_level1_snapshot(run_id)
    return {
        mapping.alias: mapping.canonical
        for mapping in snapshot.alias_mappings
        if mapping.alias and mapping.canonical
    }


def _canonicalize_aggregate_character_name(name: str, alias_lookup: dict[str, str]) -> str:
    """将 chunk 侧角色名折叠到 authority 规范名。"""

    return alias_lookup.get(name, name)


def fetch_annotation_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> AnnotationData:
    """提取 chunk_annotation 表数据"""
    rows = annotation_repo.fetch_full_annotations(run_id)

    return AnnotationData(
        chunk_ids=[row[0] for row in rows],
        event_types=[row[1] or "铺垫" for row in rows],
        cliffhangers=[row[2] or 0 for row in rows],
        pivot_moments=[row[3] or 0 for row in rows],
        emotional_valences=[row[4] or "neutral" for row in rows],
    )


def fetch_emotion_data(
    stats_repo: StatsRepository,
    run_id: str,
) -> EmotionData:
    """
    提取 chunk_curves 表数据

    修改时间: 2026-03-31
    修改者: TraeAI
    任务: refactor-hardcoded-index-access
    修改内容: 使用字段名访问替代硬编码索引
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
    提取角色数据。

    修改时间: 2026-04-02
    修改者: TraeAI
    任务: P2.1-downstream-switch
    修改内容: 从 graph_entities 读取权威角色列表，补充 chunk_characters 的情感分数
    """
    authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
    graph_view = authority_service.build_graph_view(run_id)
    alias_lookup = _build_aggregate_alias_lookup(authority_service, run_id)
    active_states = [state for state in graph_view.stable_states if state.status == "active"]

    # 2. 从 chunk_characters 聚合情感分数（用于补充）
    rows = annotation_repo.fetch_characters_with_scores(run_id)
    emotion_map: dict[str, int] = {}
    for row in rows:
        name, _, emotion_score_raw = row
        canonical_name = _canonicalize_aggregate_character_name(name, alias_lookup)
        emotion_map[canonical_name] = map_emotion_score(emotion_score_raw)

    # 3. 构建角色列表（使用 authority stable state 作为正式输入）
    characters = []
    for state in active_states:
        emotion_score = emotion_map.get(state.name, 0)
        characters.append((state.name, state.primary_role_function or "其他", emotion_score))

    # 4. 构建情感序列（仍从 chunk_characters 获取）
    char_emotion_rows = annotation_repo.fetch_character_emotion_sequence(run_id)
    char_emotion_map: dict[str, list[float]] = {}
    for name, score_raw in char_emotion_rows:
        canonical_name = _canonicalize_aggregate_character_name(name, alias_lookup)
        if canonical_name not in char_emotion_map:
            char_emotion_map[canonical_name] = []
        score = float(map_emotion_score(score_raw))
        char_emotion_map[canonical_name].append(score)
    char_emotion_scores = list(char_emotion_map.items())

    # 5. 确定主角（从 authority stable state 中找 role_function 为"主体"的）
    protagonist_name = None
    for state in active_states:
        if state.primary_role_function == "主体":
            protagonist_name = state.name
            break

    return CharacterData(
        characters=characters,
        char_emotion_scores=char_emotion_scores,
        protagonist_name=protagonist_name,
    )


def fetch_relation_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> RelationData:
    """提取 graph_* 关系数据（权威来源）。"""
    graph_view = _build_aggregate_graph_view(annotation_repo, run_id)
    current_relations = list(graph_view.confirmed_relations)
    relation_events = list(graph_view.relation_events)
    if not current_relations and not relation_events:
        pending_relations = annotation_repo.fetch_pending_chunk_relations(run_id, limit=1)
        if pending_relations:
            raise RuntimeError(
                "graph relation tables are empty while pending relations still exist; "
                "run graph projection before aggregate metrics."
            )

    return RelationData(
        relations=[(relation.from_name, relation.to_name) for relation in current_relations],
        full_relations=[
            (event.from_name, event.to_name, event.relation_type, event.change_type) for event in relation_events
        ],
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

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 简化文化指标系统
    修改内容: 只返回 imagery_densities
    """
    culture_rows = stats_repo.fetch_chunk_culture(run_id)

    return CultureData(
        imagery_densities=[row[0] for row in culture_rows if row[0] is not None],
    )


def fetch_tension_data(
    stats_repo: StatsRepository,
    run_id: str,
) -> TensionData:
    """
    提取 chunk_curves 表的 tension_composite 数据

    修改时间: 2026-03-31
    修改者: TraeAI
    任务: refactor-hardcoded-index-access
    修改内容: 使用字段名访问替代硬编码索引
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

    创建时间: 2026-03-25
    创建者: TraeAI
    任务: fix-tone-distribution-semantic-error
    说明: 从对话表获取语气类型数据用于聚合计算

    修改时间: 2026-03-31
    修改者: TraeAI
    任务: refactor-hardcoded-index-access
    修改内容: 使用字段名访问替代硬编码索引
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

    创建时间: 2026-04-04
    创建者: TraeAI
    任务: fix-style-stats-missing-fields
    说明: 从 chunk_styles 表获取 dialogue_ratio 和 avg_sent_len 数据用于聚合计算
    """
    rows = chunk_repo.fetch_chunk_styles(run_id)
    dialogue_ratios = [row[1] for row in rows if row[1] is not None]
    avg_sent_lens = [row[3] for row in rows if row[3] is not None]
    return StyleData(dialogue_ratios=dialogue_ratios, avg_sent_lens=avg_sent_lens)
