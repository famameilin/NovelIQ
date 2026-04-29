"""消歧状态数据结构"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from src.models.local.character_reference_policy import is_global_character_surface_name, is_reference_surface_name


@dataclass(frozen=True)
class NameReviewState:
    """记录单个名字的复审状态和置信度"""

    status: Literal["resolved", "review", "unresolved"]
    confidence: Literal["low", "medium", "high"]
    proposed_canonical: str | None
    evidence_strength: Literal["weak", "mixed", "strong"] | None
    # --- 审计字段 ---
    decision_evidence_count: int = 0
    decision_evidence_types: tuple[str, ...] = ()
    decision_evidence_chunks: tuple[int, ...] = ()
    decision_source: str = "llm"
    decision_timestamp: float = 0.0


@dataclass(frozen=True)
class DisambiguationState:
    """
    消歧状态（不可变对象）

    使用 copy-on-write 模式更新状态，每次更新返回新实例

    三层状态分离：
    - discovered_names: 系统已经见过的所有名字（包括别名和规范名）
    - known_canonical_names: 系统确认存在的规范角色名
    - alias_merges: 真实别名合并映射，禁止自映射（A -> A）
    - unresolved_references: 已识别但尚未解析到实名的代词/局部引用
    - reference_resolutions: 代词/局部引用到实名的解析结果，不等同于别名合并
    """

    discovered_names: frozenset[str] = frozenset()
    known_canonical_names: frozenset[str] = frozenset()
    alias_merges: frozenset[tuple[str, str]] = frozenset()
    unresolved_references: frozenset[str] = frozenset()
    reference_resolutions: frozenset[tuple[str, str]] = frozenset()
    review_status: tuple[tuple[str, NameReviewState], ...] = ()
    pending_relations: tuple[dict[str, str], ...] = ()
    entity_types: tuple[tuple[str, str], ...] = ()

    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def empty(cls) -> DisambiguationState:
        """创建空的初始状态"""
        return cls()

    def get_alias_merges_dict(self) -> dict[str, str]:
        """获取别名映射字典形式"""
        return dict(self.alias_merges)

    def get_reference_resolutions_dict(self) -> dict[str, str]:
        """
        创建时间: 2026-04-29
        任务: 角色引用分层重构
        新建原因: 代词解析结果需要独立于 alias_merges 读取，避免被当成普通别名。
        """
        return dict(self.reference_resolutions)

    def get_review_status_dict(self) -> dict[str, NameReviewState]:
        """获取复审状态字典形式"""
        return dict(self.review_status)

    def get_entity_types_dict(self) -> dict[str, str]:
        """获取实体类型映射字典形式"""
        return dict(self.entity_types)

    def with_updates(
        self,
        discovered_names: frozenset[str] | None = None,
        known_canonical_names: frozenset[str] | None = None,
        alias_merges: frozenset[tuple[str, str]] | None = None,
        unresolved_references: frozenset[str] | None = None,
        reference_resolutions: frozenset[tuple[str, str]] | None = None,
        review_status: tuple[tuple[str, NameReviewState], ...] | None = None,
        pending_relations: tuple[dict[str, str], ...] | None = None,
        entity_types: tuple[tuple[str, str], ...] | None = None,
    ) -> DisambiguationState:
        """
        创建更新后的新实例（copy-on-write）

        修改时间: 2026-04-30
        任务: 删除 DisambiguationState.version 及旧兼容逻辑
        修改原因: 最新状态合同不再保留 version 字段，copy-on-write 只传播当前结构化字段。
        """
        return DisambiguationState(
            discovered_names=discovered_names if discovered_names is not None else self.discovered_names,
            known_canonical_names=known_canonical_names
            if known_canonical_names is not None
            else self.known_canonical_names,
            alias_merges=alias_merges if alias_merges is not None else self.alias_merges,
            unresolved_references=unresolved_references
            if unresolved_references is not None
            else self.unresolved_references,
            reference_resolutions=reference_resolutions
            if reference_resolutions is not None
            else self.reference_resolutions,
            review_status=review_status if review_status is not None else self.review_status,
            pending_relations=pending_relations if pending_relations is not None else self.pending_relations,
            entity_types=entity_types if entity_types is not None else self.entity_types,
            created_at=self.created_at,
            updated_at=time.time(),
        )

    def to_dict(self) -> dict:
        """
        序列化为字典（用于 checkpoint 存储）

        修改时间: 2026-04-30
        任务: 删除 DisambiguationState.version 及旧兼容逻辑
        修改原因: checkpoint 只保留最新状态合同，不再写入版本字段。
        """
        return {
            "discovered_names": list(self.discovered_names),
            "known_canonical_names": list(self.known_canonical_names),
            "alias_merges": list(self.alias_merges),
            "unresolved_references": list(self.unresolved_references),
            "reference_resolutions": list(self.reference_resolutions),
            "review_status": [
                {
                    "name": name,
                    "state": {
                        "status": state.status,
                        "confidence": state.confidence,
                        "proposed_canonical": state.proposed_canonical,
                        "evidence_strength": state.evidence_strength,
                        "decision_evidence_count": state.decision_evidence_count,
                        "decision_evidence_types": list(state.decision_evidence_types),
                        "decision_evidence_chunks": list(state.decision_evidence_chunks),
                        "decision_source": state.decision_source,
                        "decision_timestamp": state.decision_timestamp,
                    },
                }
                for name, state in self.review_status
            ],
            "pending_relations": list(self.pending_relations),
            "entity_types": dict(self.entity_types),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def _parse_review_state(cls, item: dict) -> NameReviewState:
        """
        修改时间: 2026-04-30
        任务: 删除 DisambiguationState.version 及旧兼容逻辑
        修改原因: review_status 只按最新结构解析，缺字段时直接失败，不再补旧默认值。
        """
        s = item["state"]
        if not isinstance(item.get("name"), str):
            raise ValueError("review_status entry name must be a string")
        if not isinstance(s, dict):
            raise ValueError("review_status entry state must be a dict")
        return NameReviewState(
            status=s["status"],
            confidence=s["confidence"],
            proposed_canonical=s["proposed_canonical"],
            evidence_strength=s["evidence_strength"],
            decision_evidence_count=s["decision_evidence_count"],
            decision_evidence_types=tuple(s["decision_evidence_types"]),
            decision_evidence_chunks=tuple(s["decision_evidence_chunks"]),
            decision_source=s["decision_source"],
            decision_timestamp=s["decision_timestamp"],
        )

    @classmethod
    def from_dict(cls, data: dict) -> DisambiguationState:
        """
        从字典反序列化（用于 checkpoint 恢复）

        修改时间: 2026-04-30
        任务: 删除 DisambiguationState.version 及旧兼容逻辑
        修改原因: checkpoint 恢复只接受最新结构，遇到旧载荷或缺字段数据时直接 fail fast。
        """
        if not isinstance(data, dict):
            raise TypeError("DisambiguationState.from_dict expects a dict payload")

        required_fields = (
            "discovered_names",
            "known_canonical_names",
            "alias_merges",
            "unresolved_references",
            "reference_resolutions",
            "review_status",
            "pending_relations",
            "entity_types",
            "created_at",
            "updated_at",
        )
        missing_fields = [field_name for field_name in required_fields if field_name not in data]
        if missing_fields:
            raise ValueError(f"Missing required DisambiguationState fields: {', '.join(missing_fields)}")

        review_status_data = data["review_status"]
        if not isinstance(review_status_data, list):
            raise ValueError("review_status must be a list of {name, state} objects")
        review_status = []
        for item in review_status_data:
            if not isinstance(item, dict) or "name" not in item or "state" not in item:
                raise ValueError("review_status entries must contain name and state")
            review_status.append((item["name"], cls._parse_review_state(item)))

        entity_types_raw = data["entity_types"]
        if not isinstance(entity_types_raw, dict):
            raise ValueError("entity_types must be a dict[str, str]")

        alias_merges_raw = data["alias_merges"]
        if not isinstance(alias_merges_raw, list):
            raise ValueError("alias_merges must be a list of [alias, canonical] pairs")
        alias_merges: list[tuple[str, str]] = []
        for item in alias_merges_raw:
            if not isinstance(item, list | tuple) or len(item) != 2:
                raise ValueError("alias_merges entries must be 2-item sequences")
            alias_merges.append((item[0], item[1]))

        reference_resolutions_raw = data["reference_resolutions"]
        if not isinstance(reference_resolutions_raw, list):
            raise ValueError("reference_resolutions must be a list of [reference, canonical] pairs")
        reference_resolutions: list[tuple[str, str]] = []
        for item in reference_resolutions_raw:
            if not isinstance(item, list | tuple) or len(item) != 2:
                raise ValueError("reference_resolutions entries must be 2-item sequences")
            reference_resolutions.append((item[0], item[1]))

        pending_relations_raw = data["pending_relations"]
        if not isinstance(pending_relations_raw, list):
            raise ValueError("pending_relations must be a list of relation dicts")

        return cls(
            discovered_names=frozenset(data["discovered_names"]),
            known_canonical_names=frozenset(data["known_canonical_names"]),
            alias_merges=frozenset(alias_merges),
            unresolved_references=frozenset(data["unresolved_references"]),
            reference_resolutions=frozenset(reference_resolutions),
            review_status=tuple(review_status),
            pending_relations=tuple(pending_relations_raw),
            entity_types=tuple(entity_types_raw.items()),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )


def validate_state_invariants(state: DisambiguationState) -> bool:
    """
    校验 DisambiguationState 的核心不变量

    修改时间: 2026-04-30
    任务: 删除 DisambiguationState.version 及旧兼容逻辑
    修改原因: 最新引用分层状态仍需阻止 reference surface 混入 canonical/alias 主链。
    """
    alias_merges_dict = state.get_alias_merges_dict()

    invalid_canonicals = {
        name for name in state.known_canonical_names if not is_global_character_surface_name(name)
    }
    if invalid_canonicals:
        raise ValueError(f"Reference names cannot enter known_canonical_names: {invalid_canonicals}")

    for alias, canonical in alias_merges_dict.items():
        if alias == canonical:
            raise ValueError(f"Self-mapping not allowed in alias_merges: {alias} -> {canonical}")
        if is_reference_surface_name(alias) or not is_global_character_surface_name(canonical):
            raise ValueError(f"Reference names cannot enter alias_merges: {alias} -> {canonical}")

    canonical_targets = set(alias_merges_dict.values())
    if not canonical_targets <= state.known_canonical_names:
        missing = canonical_targets - state.known_canonical_names
        raise ValueError(f"Canonical targets not in known_canonical_names: {missing}")

    review_dict = state.get_review_status_dict()
    for name, review in review_dict.items():
        if review.proposed_canonical is not None:
            valid_targets = {name} | state.known_canonical_names
            if review.proposed_canonical not in valid_targets:
                raise ValueError(
                    f"Invalid proposed_canonical for '{name}': {review.proposed_canonical}. "
                    f"Must be the name itself or a known canonical name."
                )

    reference_resolutions_dict = state.get_reference_resolutions_dict()
    for reference_name, canonical in reference_resolutions_dict.items():
        if not is_reference_surface_name(reference_name):
            raise ValueError(f"reference_resolutions source must be a reference name: {reference_name}")
        if not is_global_character_surface_name(canonical):
            raise ValueError(
                f"reference_resolutions target must be a global character: {reference_name} -> {canonical}"
            )
        if canonical not in state.known_canonical_names:
            raise ValueError(f"Reference target not in known_canonical_names: {reference_name} -> {canonical}")

    resolved_references = set(reference_resolutions_dict)
    if state.unresolved_references & resolved_references:
        duplicated = state.unresolved_references & resolved_references
        raise ValueError(f"References cannot be both unresolved and resolved: {duplicated}")

    return True


__all__ = [
    "NameReviewState",
    "DisambiguationState",
    "validate_state_invariants",
]
