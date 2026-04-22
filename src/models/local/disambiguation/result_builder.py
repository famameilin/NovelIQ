"""
消歧结果构建模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
说明: 提取消歧结果构建逻辑

修改时间: 2026-03-18
修改者: TraeAI
任务: entity-type-relation-extraction
修改内容: 新增 ExtendedDisambigResult 数据类和 build_extended_result_from_response 函数

修改时间: 2026-03-26
修改者: TraeAI
任务: disambiguation-evidence-grading
修改内容: 添加 evidence_sources 字段，支持证据来源追踪
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from src.models.disambiguation_types import NameCountCandidate

from ..schema import CloudDisambiguateResponseModel, DisambigConfidence, DisambiguateResponseModel, EntityType
from .evidence import EvidenceProfile, build_evidence_profile


@dataclass
class ExtendedDisambigResult:
    """
    扩展消歧结果数据类

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 包含别名映射、实体类型和实体关系的完整消歧结果

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: fix/disambig-thinking-save
    修改内容: 添加 _thinking_content 字段保存 thinking 内容

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: disambiguation-evidence-grading
    修改内容: 添加 evidence_sources 字段。支持证据来源追踪

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: 简化消歧响应模型
    修改内容: 删除 common_name_map 字段，将 merge_target_map 重命名为 alias_map

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: disambiguation-state-three-layer
    修改内容: 将 alias_map 重命名为 canonical_decisions，明确表达模型判断而非运行时状态
    """

    canonical_decisions: dict[str, str]
    entity_types: dict[str, EntityType]
    entity_relations: list[dict[str, str]]
    alias_confidence: dict[str, str] = field(default_factory=dict)
    evidence_profiles: dict[str, EvidenceProfile] = field(default_factory=dict)
    _thinking_content: str | None = None
    _reasoning_tokens: int | None = None


def _candidate_names(candidates: list[NameCountCandidate] | list[str]) -> list[str]:
    if candidates and isinstance(candidates[0], str):
        return [str(name) for name in candidates]
    return [str(candidate["name"]) for candidate in candidates]  # type: ignore[index]


def normalize_disambiguate_response(
    response_data: DisambiguateResponseModel | CloudDisambiguateResponseModel,
) -> DisambiguateResponseModel:
    """
    将云端兼容响应归一化为内部标准消歧模型。

    创建时间: 2026-04-20
    创建者: Codex
    任务: fix-cloud-disambig-mapping-schema
    说明: 运行时内部逻辑仍以 dict 结构消费消歧结果，因此在 API 入口把
          CloudDisambiguateResponseModel 转回 DisambiguateResponseModel，避免影响下游状态机。
    """
    if isinstance(response_data, DisambiguateResponseModel):
        return response_data

    cloud_response = response_data
    thinking_content = getattr(cloud_response, "_thinking_content", None) or getattr(
        cloud_response,
        "thinking_content",
        None,
    )
    reasoning_tokens = getattr(cloud_response, "_reasoning_tokens", None) or getattr(
        cloud_response,
        "reasoning_tokens",
        None,
    )

    canonical_decisions: dict[str, str] = {}
    for decision_record in cloud_response.canonical_decisions:
        canonical_decisions[str(decision_record.name)] = str(decision_record.canonical)

    alias_confidence: dict[str, DisambigConfidence] = {}
    for confidence_record in cloud_response.alias_confidence:
        alias_confidence[str(confidence_record.name)] = confidence_record.confidence

    entity_types: dict[str, EntityType] = {}
    for entity_type_record in cloud_response.entity_types:
        entity_types[str(entity_type_record.name)] = entity_type_record.entity_type

    evidence_sources: dict[str, list[str]] = {}
    for evidence_record in cloud_response.evidence_sources:
        evidence_sources[str(evidence_record.name)] = [str(source) for source in evidence_record.sources]

    return DisambiguateResponseModel(
        canonical_decisions=canonical_decisions,
        alias_confidence=alias_confidence,
        entity_types=entity_types,
        entity_relations=list(cloud_response.entity_relations),
        _thinking_content=thinking_content,
        _reasoning_tokens=reasoning_tokens,
        evidence_sources=evidence_sources,
    )


def build_result_from_response(
    response_data: DisambiguateResponseModel | CloudDisambiguateResponseModel,
    candidates: list[NameCountCandidate] | list[str],
) -> dict[str, str]:
    """
    从 DisambiguateResponseModel 构建结果字典，确保所有候选名都有映射

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 重构本地消歧客户端集成 Instructor

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
    修改内容: 提取为独立模块函数

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: fix-type-errors
    修改内容: 支持 list[str] 类型参数，用于匿名消歧场景

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: 简化消歧响应模型
    修改内容: 将 alias_map 改为 canonical_decisions
    """
    normalized_response = normalize_disambiguate_response(response_data)
    name_list = _candidate_names(candidates)

    result: dict[str, str] = {}
    for name in name_list:
        if name in normalized_response.canonical_decisions:
            result[name] = str(normalized_response.canonical_decisions[name])
        else:
            result[name] = name
    return result


def build_extended_result_from_response(
    response_data: DisambiguateResponseModel | CloudDisambiguateResponseModel,
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str] | None = None,
) -> ExtendedDisambigResult:
    """
    从 DisambiguateResponseModel 构建扩展结果，包含别名映射、实体类型和实体关系

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 返回完整的消歧结果，包括alias_map、entity_types和entity_relations

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: fix/disambig-thinking-save
    修改内容: 复制 _thinking_content 到 ExtendedDisambigResult

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: disambiguation-evidence-grading
    修改内容: 提取 evidence_sources 字段

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: disambiguation-state-three-layer
    修改内容: 将 alias_map 改为 canonical_decisions，明确表达模型判断而非运行时状态
    """
    normalized_response = normalize_disambiguate_response(response_data)
    canonical_decisions = build_result_from_response(normalized_response, candidates)
    name_list = _candidate_names(candidates)

    alias_confidence: dict[str, str] = {}
    for name in name_list:
        alias_confidence[name] = str(normalized_response.alias_confidence.get(name, "medium"))
    evidence_profiles: dict[str, EvidenceProfile] = {}
    for name in name_list:
        context = context_sentences.get(name, "") if context_sentences else ""
        evidence_profiles[name] = build_evidence_profile(context)
    entity_types = dict(normalized_response.entity_types)
    valid_entity_type_keys = set(name_list) | set(canonical_decisions.values())
    filtered_entity_types = {k: v for k, v in entity_types.items() if k in valid_entity_type_keys}
    if len(filtered_entity_types) < len(entity_types):
        invalid_keys = set(entity_types.keys()) - set(filtered_entity_types.keys())
        logger.debug(
            "Filtered {} invalid entity_type keys: {}",
            len(entity_types) - len(filtered_entity_types),
            invalid_keys,
        )
    entity_types = filtered_entity_types
    entity_relations: list[dict[str, str]] = []
    for rel in normalized_response.entity_relations:
        entity_relations.append(
            {
                "from": rel.from_entity,
                "to": rel.to_entity,
                "type": rel.type,
            }
        )
    thinking_content = getattr(normalized_response, "_thinking_content", None) or getattr(
        normalized_response, "thinking_content", None
    )
    reasoning_tokens = getattr(normalized_response, "_reasoning_tokens", None) or getattr(
        normalized_response, "reasoning_tokens", None
    )
    return ExtendedDisambigResult(
        canonical_decisions=canonical_decisions,
        entity_types=entity_types,
        entity_relations=entity_relations,
        alias_confidence=alias_confidence,
        evidence_profiles=evidence_profiles,
        _thinking_content=thinking_content,
        _reasoning_tokens=reasoning_tokens,
    )


def align_canonical_by_frequency(
    result: ExtendedDisambigResult,
    candidates: list[NameCountCandidate],
    min_ratio: float = 1.5,
    global_freq: dict[str, int] | None = None,
) -> ExtendedDisambigResult:
    """基于原文频次对齐 canonical 方向，确保高频名作为 canonical。

    遍历 result.canonical_decisions 中每个 (alias, canonical) 对，
    如果 alias 频次高于 canonical 且比例 > min_ratio，
    则交换方向使高频名成为 canonical。

    Args:
        result: LLM 消歧结果
        candidates: 候选人名及频次列表（当前批次）
        min_ratio: 触发翻转的最小频次比（alias_count / canonical_count）
        global_freq: 全量名字频次表。当 canonical 不在 candidates 中时
            从此表查找频次，避免 canonical_count=0 导致翻转被跳过。

    Returns:
        修改后的 ExtendedDisambigResult（原地修改并返回）
    """
    freq: dict[str, int] = {str(c["name"]): int(c.get("count", 0)) for c in candidates}
    if global_freq:
        for name, count in global_freq.items():
            freq.setdefault(name, count)
    decisions = result.canonical_decisions
    flipped: list[tuple[str, str, str, int, int]] = []

    for alias, canonical in list(decisions.items()):
        if alias == canonical:
            continue
        alias_count = freq.get(alias, 0)
        canonical_count = freq.get(canonical, 0)
        if canonical_count == 0 or alias_count <= canonical_count:
            continue
        ratio = alias_count / canonical_count
        if ratio < min_ratio:
            continue

        # 翻转方向：高频名成为 canonical
        decisions[canonical] = alias
        decisions[alias] = alias  # 原 alias 变为 self-mapping

        # 级联修正：将指向 alias 的其他映射更新为新 canonical
        for other_alias, other_canonical in list(decisions.items()):
            if other_alias != canonical and other_canonical == alias:
                decisions[other_alias] = alias

        flipped.append((alias, canonical, alias, alias_count, canonical_count))

    if flipped:
        for old_alias, old_canonical, new_canonical, a_count, c_count in flipped:
            logger.info(
                "canonical direction aligned by frequency: {} (count={}) -> {} (count={}), flipped to {} as canonical",
                old_alias,
                a_count,
                old_canonical,
                c_count,
                new_canonical,
            )

    return result
