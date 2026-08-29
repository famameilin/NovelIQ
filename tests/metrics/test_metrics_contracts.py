"""指标契约 registry 可执行校验(双向:声明→模型、模型指标字段→声明)。"""

from __future__ import annotations

import types
from collections import defaultdict
from typing import Union, get_args, get_origin

from pydantic import BaseModel

from src.api.models.graph import GraphMetricsResponse, KeywordsResponse
from src.api.models.responses import (
    BookAggregateStats,
    ChapterMetricSummary,
    CharacterStats,
    CharacterStatsAggregate,
    DiagnosisResult,
    EmotionStats,
    EmotionTrendWindow,
    GlobalStats,
    LinguisticEntitiesResponse,
    LinguisticFeaturesResponse,
    LinguisticGroupStats,
    LinguisticPhrasesResponse,
    NarrativeStructureStats,
    StyleStats,
    TopicAggregateResponse,
    TopicEmotionEntry,
    TopicInfo,
    TopicShiftCandidate,
    Word2VecStatsResponse,
)
from src.api.models.tabs import LinguisticEntitiesTabResponse, TopicsOverviewTabResponse
from src.metrics.contracts import load_metric_contracts

# endpoint 片段 → 承载字段的 response model(可多模型:字段取并集校验)
_ENDPOINT_MODELS: dict[str, tuple[type[BaseModel], ...]] = {
    "/metrics/narrative-structure": (NarrativeStructureStats,),
    "/metrics/emotion-stats": (EmotionStats,),
    "/metrics/character-stats": (CharacterStatsAggregate,),
    "/metrics/style-stats": (StyleStats,),
    "/chapter-metrics": (BookAggregateStats, ChapterMetricSummary),
    "/characters": (CharacterStats,),
    "/emotion-trend": (EmotionTrendWindow,),
    "/diagnosis": (DiagnosisResult,),
    "/topics": (TopicInfo,),
    "/topics/aggregate": (TopicAggregateResponse,),
    "/topics/shifts": (TopicShiftCandidate,),
    "/topics/emotion": (TopicEmotionEntry,),
    "export/global_stats": (GlobalStats,),
    "/graph/metrics": (GraphMetricsResponse,),
    "/keywords": (KeywordsResponse,),
    "/linguistic/features": (LinguisticFeaturesResponse, LinguisticGroupStats),
    "/linguistic/entities": (LinguisticEntitiesResponse,),
    "/linguistic/phrases": (LinguisticPhrasesResponse,),
    "/linguistic/word2vec": (Word2VecStatsResponse,),
    "/tabs/linguistic-entities": (LinguisticEntitiesTabResponse,),
}

# 反向校验范围:承载复合数据的 stats 模型(基本数据透出模型不入范围)
_REVERSE_SCOPE_MODELS: tuple[type[BaseModel], ...] = (
    BookAggregateStats,
    ChapterMetricSummary,
    StyleStats,
    NarrativeStructureStats,
    EmotionStats,
    EmotionTrendWindow,
    CharacterStats,
    CharacterStatsAggregate,
    DiagnosisResult,
    GlobalStats,
    LinguisticGroupStats,
    TopicAggregateResponse,
    TopicShiftCandidate,
    TopicEmotionEntry,
    Word2VecStatsResponse,
    GraphMetricsResponse,
    KeywordsResponse,
    TopicsOverviewTabResponse,
    LinguisticEntitiesTabResponse,
)

# 基本数据字段:计数/坐标/标识/Agent 标注原值/元数据/散文,不入契约
_BASIC_FIELDS: frozenset[str] = frozenset({
    "run_id", "unavailable_reason", "model", "algorithm", "level", "config",
    "total_chapters", "total_paragraphs", "total_chars", "total_tokens",
    "paragraph_count", "sentence_total", "token_total", "window_token_total",
    "hit_paragraphs", "paragraph_total", "appearance_count",
    "chapter_id", "topic_id",
    "window_index", "position", "start_position", "end_position",
    "paragraph_start", "paragraph_end", "chapter_start", "chapter_end",
    "narrative_function", "pivot_moment", "cliffhanger", "emotional_valence",
    "name", "main_characters", "focus_characters", "core_cast", "diagnosis",
    "value_logic_reason", "dignity_reason", "power_stance_reason", "cultural_depth_reason",
    "topics", "chapters", "total_hits", "total_char_count",
})


def _collect_model_fields(*models: type[BaseModel]) -> set[str]:
    fields: set[str] = set()
    for model in models:
        fields.update(model.model_fields.keys())
    return fields


def _is_metric_annotation(annotation: object) -> bool:
    """指标型注解:数值、数值映射、列表或嵌套模型;str/bool/None 等基本型不算。"""
    if hasattr(annotation, "__metadata__"):  # Annotated
        annotation = annotation.__origin__
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        return any(_is_metric_annotation(a) for a in args)
    if annotation in (int, float):
        return True
    if origin in (dict, list, tuple, set):
        return True
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def test_load_metric_contracts_not_empty() -> None:
    contracts = load_metric_contracts()
    assert len(contracts) >= 10


def test_contract_fields_exist_on_response_models() -> None:
    """契约声明的字段必须能在对应 response model 上找到。"""
    contracts = load_metric_contracts()
    missing: list[str] = []

    for contract in contracts:
        endpoint_parts = [part.strip() for part in contract.endpoint.split(",") if part.strip()]
        model_fields: set[str] = set()
        for part in endpoint_parts:
            for model in _ENDPOINT_MODELS.get(part, ()):
                model_fields.update(model.model_fields.keys())

        if not model_fields:
            missing.append(f"{contract.id}: no mapped response model for endpoint={contract.endpoint!r}")
            continue

        for field in contract.fields:
            if field not in model_fields:
                missing.append(f"{contract.id}.{field} not in models for {contract.endpoint}")

    assert missing == [], "契约字段未落到 response model:\n" + "\n".join(missing)


def test_stats_models_metric_fields_declared() -> None:
    """反向校验:stats 模型上的指标型字段必须已有契约声明(复合数据全进)。"""
    declared = {field for contract in load_metric_contracts() for field in contract.fields}
    undeclared: list[str] = []

    for model in _REVERSE_SCOPE_MODELS:
        for name, field_info in model.model_fields.items():
            if name in _BASIC_FIELDS:
                continue
            if _is_metric_annotation(field_info.annotation) and name not in declared:
                undeclared.append(f"{model.__name__}.{name}")

    assert undeclared == [], "指标字段未立约(需补契约或列入 _BASIC_FIELDS 基本数据):\n" + "\n".join(undeclared)


def test_authoritative_unique_per_concept_field() -> None:
    """同一 concept 下同一 field 最多一条 authoritative=true 契约。"""
    contracts = load_metric_contracts()
    owners: dict[tuple[str, str], list[str]] = defaultdict(list)

    for contract in contracts:
        if not contract.authoritative:
            continue
        for field in contract.fields:
            owners[(contract.concept, field)].append(contract.id)

    conflicts = {f"{concept}/{field}: {ids}" for (concept, field), ids in owners.items() if len(ids) > 1}
    assert conflicts == set(), "同概念字段存在多个权威声明:\n" + "\n".join(sorted(conflicts))


def test_category_c_requires_subjective() -> None:
    """C 类（LLM/主观输入）契约必须标记 objective_subjective=subjective。"""
    contracts = load_metric_contracts()
    violations = [
        f"{c.id}: category={c.category} objective_subjective={c.objective_subjective}"
        for c in contracts
        if c.category == "C" and c.objective_subjective != "subjective"
    ]
    assert violations == [], "C 类契约未标记 subjective:\n" + "\n".join(violations)


def test_contract_ids_unique() -> None:
    contracts = load_metric_contracts()
    ids = [c.id for c in contracts]
    assert len(ids) == len(set(ids))


def test_all_contracts_have_null_semantics() -> None:
    contracts = load_metric_contracts()
    empty = [c.id for c in contracts if not c.null_semantics.strip()]
    assert empty == [], f"缺少 null_semantics: {empty}"


def test_known_renamed_fields_present() -> None:
    """破坏性重命名后的权威字段名必须在契约与模型两侧同时存在。"""
    contracts = load_metric_contracts()
    field_set = {field for c in contracts for field in c.fields}
    model_fields = _collect_model_fields(
        NarrativeStructureStats,
        EmotionStats,
        CharacterStatsAggregate,
        StyleStats,
        DiagnosisResult,
        GlobalStats,
        TopicInfo,
    )
    required = {
        "lexical_pos_neg_ratio",
        "string_token_diversity",
        "relation_change_per_10k_chars",
        "chapter_narrative_function_share",
        "arc_delta",
        "foreshadow_expectation",
    }
    assert required <= field_set
    assert required <= model_fields
    # 旧名不得再出现在契约字段列表
    assert "pos_neg_ratio" not in field_set
    assert "vocab_breadth" not in field_set


def test_contracts_from_raw_override() -> None:
    """契约可从外部声明列表加载(测试/工具注入)。"""
    contracts = load_metric_contracts(
        [
            {
                "id": "tmp_contract",
                "concept": "临时",
                "problem": "回归测试",
                "fields": ["tmp_field"],
                "objective_subjective": "objective",
                "authoritative": False,
                "null_semantics": "无数据时 null",
                "computation_chain": "test",
            }
        ]
    )
    assert len(contracts) == 1
    assert contracts[0].id == "tmp_contract"
    assert contracts[0].fields == ("tmp_field",)
