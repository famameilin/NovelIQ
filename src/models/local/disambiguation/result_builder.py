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

from src.models.disambiguation_types import NameCountCandidate

from ..schema import DisambiguateResponseModel
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
    修改内容: 添加 evidence_sources 字段，支持证据来源追踪

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: 简化消歧响应模型
    修改内容: 删除 common_name_map 字段，将 merge_target_map 重命名为 alias_map
    """

    alias_map: dict[str, str]
    entity_types: dict[str, str]
    entity_relations: list[dict[str, str]]
    alias_confidence: dict[str, str] = field(default_factory=dict)
    evidence_profiles: dict[str, EvidenceProfile] = field(default_factory=dict)
    _thinking_content: str | None = None


def _candidate_names(candidates: list[NameCountCandidate] | list[str]) -> list[str]:
    if candidates and isinstance(candidates[0], str):
        return [str(name) for name in candidates]
    return [str(candidate["name"]) for candidate in candidates]  # type: ignore[index]


def build_result_from_response(
    response_data: DisambiguateResponseModel,
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
    修改内容: 将 merge_target_map 改为 alias_map
    """
    name_list = _candidate_names(candidates)

    result: dict[str, str] = {}
    for name in name_list:
        if name in response_data.alias_map:
            result[name] = str(response_data.alias_map[name])
        else:
            result[name] = name
    return result


def build_extended_result_from_response(
    response_data: DisambiguateResponseModel,
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
    任务: 简化消歧响应模型
    修改内容: 删除 common_name_map 相关逻辑，将 merge_target_map 改为 alias_map
    """
    alias_map = build_result_from_response(response_data, candidates)

    name_list = _candidate_names(candidates)

    alias_confidence: dict[str, str] = {}
    for name in name_list:
        alias_confidence[name] = str(response_data.alias_confidence.get(name, "medium"))

    evidence_profiles: dict[str, EvidenceProfile] = {}
    for name in name_list:
        context = context_sentences.get(name, "") if context_sentences else ""
        evidence_profiles[name] = build_evidence_profile(context)

    entity_types = dict(response_data.entity_types)

    entity_relations: list[dict[str, str]] = []
    for rel in response_data.entity_relations:
        entity_relations.append(
            {
                "from": rel.from_entity,
                "to": rel.to_entity,
                "type": rel.type,
            }
        )

    thinking_content = getattr(response_data, "_thinking_content", None) or getattr(
        response_data, "thinking_content", None
    )

    return ExtendedDisambigResult(
        alias_map=alias_map,
        entity_types=entity_types,
        entity_relations=entity_relations,
        alias_confidence=alias_confidence,
        evidence_profiles=evidence_profiles,
        _thinking_content=thinking_content,
    )
