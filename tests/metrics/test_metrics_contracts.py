"""指标契约 registry 可执行校验。"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from src.api.models.responses import (
    CharacterStatsAggregate,
    DiagnosisResult,
    EmotionStats,
    GlobalStats,
    NarrativeStructureStats,
    StyleStats,
    TopicInfo,
)
from src.metrics.contracts import load_metric_contracts

# endpoint 片段 → 承载字段的 response model
_ENDPOINT_MODELS: dict[str, type[BaseModel]] = {
    "/metrics/narrative-structure": NarrativeStructureStats,
    "/metrics/emotion-stats": EmotionStats,
    "/metrics/character-stats": CharacterStatsAggregate,
    "/metrics/style-stats": StyleStats,
    "/diagnosis": DiagnosisResult,
    "/topics": TopicInfo,
    "export/global_stats": GlobalStats,
}


def _collect_model_fields(*models: type[BaseModel]) -> set[str]:
    fields: set[str] = set()
    for model in models:
        fields.update(model.model_fields.keys())
    return fields


def test_load_metric_contracts_not_empty() -> None:
    contracts = load_metric_contracts()
    assert len(contracts) >= 10


def test_contract_fields_exist_on_response_models() -> None:
    """YAML 声明的字段必须能在对应 response model 上找到。"""
    contracts = load_metric_contracts()
    missing: list[str] = []

    for contract in contracts:
        endpoint_parts = [part.strip() for part in contract.endpoint.split(",") if part.strip()]
        model_fields: set[str] = set()
        for part in endpoint_parts:
            model = _ENDPOINT_MODELS.get(part)
            if model is None:
                # 兼容 "/chapter-metrics" 等并列端点：只校验主聚合模型字段
                continue
            model_fields.update(model.model_fields.keys())

        if not model_fields:
            missing.append(f"{contract.id}: no mapped response model for endpoint={contract.endpoint!r}")
            continue

        for field in contract.fields:
            if field not in model_fields:
                missing.append(f"{contract.id}.{field} not in models for {contract.endpoint}")

    assert missing == [], "契约字段未落到 response model:\n" + "\n".join(missing)


def test_authoritative_unique_per_concept_field() -> None:
    """同一 concept 下同一 field 最多一条 authoritative=true 契约。"""
    contracts = load_metric_contracts()
    owners: dict[tuple[str, str], list[str]] = defaultdict(list)

    for contract in contracts:
        if not contract.authoritative:
            continue
        for field in contract.fields:
            owners[(contract.concept, field)].append(contract.id)

    conflicts = {
        f"{concept}/{field}: {ids}"
        for (concept, field), ids in owners.items()
        if len(ids) > 1
    }
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
