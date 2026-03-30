"""
消歧状态数据结构

创建时间: 2026-03-27
创建者: TraeAI
任务: disambiguation-state-three-layer - Task 1 定义新的数据结构
说明: 定义不可变的 NameReviewState 和 DisambiguationState 数据类，使用 copy-on-write 模式更新状态
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class NameReviewState:
    """
    名字复审状态

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 记录单个名字的消歧状态和置信度
    """

    status: Literal["resolved", "review", "unresolved"]
    confidence: Literal["low", "medium", "high"]
    proposed_canonical: str | None
    evidence_strength: Literal["weak", "mixed", "strong"] | None


@dataclass(frozen=True)
class DisambiguationState:
    """
    消歧状态（不可变对象）

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 使用 copy-on-write 模式更新状态，每次更新返回新实例

    三层状态分离：
    - discovered_names: 系统已经见过的所有名字（包括别名和规范名）
    - known_canonical_names: 系统确认存在的规范角色名
    - alias_merges: 真实别名合并映射，禁止自映射（A -> A）
    """

    discovered_names: frozenset[str] = frozenset()
    known_canonical_names: frozenset[str] = frozenset()
    alias_merges: frozenset[tuple[str, str]] = frozenset()
    review_status: tuple[tuple[str, NameReviewState], ...] = ()
    pending_relations: tuple[dict[str, str], ...] = ()

    version: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def empty(cls) -> DisambiguationState:
        """创建空的初始状态"""
        return cls()

    def get_alias_merges_dict(self) -> dict[str, str]:
        """获取别名映射字典形式"""
        return dict(self.alias_merges)

    def get_review_status_dict(self) -> dict[str, NameReviewState]:
        """获取复审状态字典形式"""
        return dict(self.review_status)

    def with_updates(
        self,
        discovered_names: frozenset[str] | None = None,
        known_canonical_names: frozenset[str] | None = None,
        alias_merges: frozenset[tuple[str, str]] | None = None,
        review_status: tuple[tuple[str, NameReviewState], ...] | None = None,
        pending_relations: tuple[dict[str, str], ...] | None = None,
    ) -> DisambiguationState:
        """创建更新后的新实例（copy-on-write）"""
        return DisambiguationState(
            discovered_names=discovered_names if discovered_names is not None else self.discovered_names,
            known_canonical_names=known_canonical_names
            if known_canonical_names is not None
            else self.known_canonical_names,
            alias_merges=alias_merges if alias_merges is not None else self.alias_merges,
            review_status=review_status if review_status is not None else self.review_status,
            pending_relations=pending_relations if pending_relations is not None else self.pending_relations,
            version=self.version,
            created_at=self.created_at,
            updated_at=time.time(),
        )

    def to_dict(self) -> dict:
        """序列化为字典（用于 checkpoint 存储）"""
        return {
            "discovered_names": list(self.discovered_names),
            "known_canonical_names": list(self.known_canonical_names),
            "alias_merges": list(self.alias_merges),
            "review_status": [
                {
                    "name": name,
                    "state": {
                        "status": state.status,
                        "confidence": state.confidence,
                        "proposed_canonical": state.proposed_canonical,
                        "evidence_strength": state.evidence_strength,
                    },
                }
                for name, state in self.review_status
            ],
            "pending_relations": list(self.pending_relations),
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DisambiguationState:
        """从字典反序列化（用于 checkpoint 恢复）"""
        if not data:
            return cls.empty()

        version = data.get("version", 1)
        if version != 1:
            return cls.empty()

        review_status_data = data.get("review_status", [])
        review_status = tuple(
            (
                item["name"],
                NameReviewState(
                    status=item["state"]["status"],
                    confidence=item["state"]["confidence"],
                    proposed_canonical=item["state"].get("proposed_canonical"),
                    evidence_strength=item["state"].get("evidence_strength"),
                ),
            )
            for item in review_status_data
            if isinstance(item, dict) and "name" in item and "state" in item
        )

        return cls(
            discovered_names=frozenset(data.get("discovered_names", [])),
            known_canonical_names=frozenset(data.get("known_canonical_names", [])),
            alias_merges=frozenset(
                tuple(item)
                for item in data.get("alias_merges", [])
                if isinstance(item, (list, tuple)) and len(item) == 2
            ),
            review_status=review_status,
            pending_relations=tuple(data.get("pending_relations", [])),
            version=version,
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


def validate_state_invariants(state: DisambiguationState) -> bool:
    """
    校验状态不变量

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 校验 DisambiguationState 的三个核心不变量

    Returns:
        True 如果所有不变量满足，否则抛出 ValueError
    """
    alias_merges_dict = state.get_alias_merges_dict()

    for alias, canonical in alias_merges_dict.items():
        if alias == canonical:
            raise ValueError(f"Self-mapping not allowed in alias_merges: {alias} -> {canonical}")

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

    return True


__all__ = [
    "NameReviewState",
    "DisambiguationState",
    "validate_state_invariants",
]
