"""
DisambiguationState 单元测试

创建时间: 2026-03-27
创建者: TraeAI
任务: disambiguation-state-three-layer - Task 1.5 编写单元测试
说明: 测试 DisambiguationState 和 validate_state_invariants
"""

import pytest

from src.models.local.disambiguation import (
    DisambiguationState,
    NameReviewState,
    validate_state_invariants,
)


class TestNameReviewState:
    """NameReviewState 测试"""

    def test_create_resolved_state(self):
        state = NameReviewState(
            status="resolved",
            confidence="high",
            proposed_canonical="伯安",
            evidence_strength="strong",
        )
        assert state.status == "resolved"
        assert state.confidence == "high"
        assert state.proposed_canonical == "伯安"
        assert state.evidence_strength == "strong"

    def test_create_review_state(self):
        state = NameReviewState(
            status="review",
            confidence="medium",
            proposed_canonical=None,
            evidence_strength="mixed",
        )
        assert state.status == "review"
        assert state.confidence == "medium"
        assert state.proposed_canonical is None
        assert state.evidence_strength == "mixed"

    def test_frozen_state(self):
        state = NameReviewState(
            status="resolved",
            confidence="high",
            proposed_canonical="伯安",
            evidence_strength="strong",
        )
        with pytest.raises(AttributeError):
            state.status = "review"


class TestDisambiguationState:
    """DisambiguationState 测试"""

    def test_empty_state(self):
        state = DisambiguationState.empty()
        assert state.discovered_names == frozenset()
        assert state.known_canonical_names == frozenset()
        assert state.alias_merges == frozenset()
        assert state.review_status == ()
        assert state.pending_relations == ()
        assert state.entity_types == ()
        assert state.unresolved_references == frozenset()
        assert state.reference_resolutions == frozenset()
        assert state.version == 3

    def test_create_state_with_data(self):
        state = DisambiguationState(
            discovered_names=frozenset(["伯安", "贺伯安"]),
            known_canonical_names=frozenset(["伯安"]),
            alias_merges=frozenset([("贺伯安", "伯安")]),
        )
        assert "伯安" in state.discovered_names
        assert "贺伯安" in state.discovered_names
        assert "伯安" in state.known_canonical_names
        assert ("贺伯安", "伯安") in state.alias_merges

    def test_get_alias_merges_dict(self):
        state = DisambiguationState(
            alias_merges=frozenset([("贺伯安", "伯安"), ("猴子", "侯飞白")]),
        )
        merges_dict = state.get_alias_merges_dict()
        assert merges_dict == {"贺伯安": "伯安", "猴子": "侯飞白"}

    def test_get_review_status_dict(self):
        review_state = NameReviewState(
            status="resolved",
            confidence="high",
            proposed_canonical="伯安",
            evidence_strength="strong",
        )
        state = DisambiguationState(
            review_status=(("贺伯安", review_state),),
        )
        status_dict = state.get_review_status_dict()
        assert status_dict == {"贺伯安": review_state}

    def test_with_updates(self):
        state = DisambiguationState.empty()
        new_state = state.with_updates(
            discovered_names=frozenset(["伯安"]),
            known_canonical_names=frozenset(["伯安"]),
        )
        assert state.discovered_names == frozenset()
        assert new_state.discovered_names == frozenset(["伯安"])
        assert new_state.known_canonical_names == frozenset(["伯安"])

    def test_frozen_state(self):
        state = DisambiguationState(
            discovered_names=frozenset(["伯安"]),
        )
        with pytest.raises(AttributeError):
            state.discovered_names = frozenset(["贺伯安"])

    def test_to_dict_and_from_dict(self):
        original = DisambiguationState(
            discovered_names=frozenset(["伯安", "贺伯安"]),
            known_canonical_names=frozenset(["伯安"]),
            alias_merges=frozenset([("贺伯安", "伯安")]),
            review_status=(
                (
                    "贺伯安",
                    NameReviewState(
                        status="resolved",
                        confidence="high",
                        proposed_canonical="伯安",
                        evidence_strength="strong",
                    ),
                ),
            ),
            pending_relations=({"from": "A", "to": "B", "type": "friend"},),
        )

        data = original.to_dict()
        restored = DisambiguationState.from_dict(data)

        assert restored.discovered_names == original.discovered_names
        assert restored.known_canonical_names == original.known_canonical_names
        assert restored.alias_merges == original.alias_merges
        assert restored.unresolved_references == original.unresolved_references
        assert restored.reference_resolutions == original.reference_resolutions
        assert len(restored.review_status) == 1
        assert restored.pending_relations == original.pending_relations

    def test_from_dict_empty(self):
        state = DisambiguationState.from_dict({})
        assert state.discovered_names == frozenset()
        assert state.known_canonical_names == frozenset()

    def test_from_dict_invalid_version(self):
        state = DisambiguationState.from_dict({"version": 2})
        assert state.version == 3
        assert state.discovered_names == frozenset()
        assert state.known_canonical_names == frozenset()


class TestValidateStateInvariants:
    """validate_state_invariants 测试"""

    def test_empty_state_allows_empty_invalid_canonical_set(self):
        """
        创建时间: 2026-04-29
        任务: 验证引用层状态不变量边界
        新建原因: 锁定 `known_canonical_names` 为空时，invalid_canonicals 检查不会误报或触发后续异常。
        """
        state = DisambiguationState.empty()

        assert validate_state_invariants(state) is True

    def test_valid_state(self):
        state = DisambiguationState(
            discovered_names=frozenset(["伯安", "贺伯安"]),
            known_canonical_names=frozenset(["伯安"]),
            alias_merges=frozenset([("贺伯安", "伯安")]),
        )
        assert validate_state_invariants(state) is True

    def test_self_mapping_not_allowed(self):
        state = DisambiguationState(
            alias_merges=frozenset([("伯安", "伯安")]),
            known_canonical_names=frozenset(["伯安"]),
        )
        with pytest.raises(ValueError, match="Self-mapping not allowed"):
            validate_state_invariants(state)

    def test_canonical_not_in_known_names(self):
        state = DisambiguationState(
            alias_merges=frozenset([("贺伯安", "伯安")]),
            known_canonical_names=frozenset(["其他名字"]),
        )
        with pytest.raises(ValueError, match="Canonical targets not in known_canonical_names"):
            validate_state_invariants(state)

    def test_invalid_proposed_canonical(self):
        state = DisambiguationState(
            known_canonical_names=frozenset(["伯安"]),
            review_status=(
                (
                    "贺伯安",
                    NameReviewState(
                        status="review",
                        confidence="medium",
                        proposed_canonical="不存在的名字",
                        evidence_strength="weak",
                    ),
                ),
            ),
        )
        with pytest.raises(ValueError, match="Invalid proposed_canonical"):
            validate_state_invariants(state)

    def test_valid_proposed_canonical_is_self(self):
        state = DisambiguationState(
            known_canonical_names=frozenset(["伯安"]),
            review_status=(
                (
                    "贺伯安",
                    NameReviewState(
                        status="review",
                        confidence="medium",
                        proposed_canonical="贺伯安",
                        evidence_strength="weak",
                    ),
                ),
            ),
        )
        assert validate_state_invariants(state) is True

    def test_valid_proposed_canonical_is_known(self):
        state = DisambiguationState(
            known_canonical_names=frozenset(["伯安"]),
            review_status=(
                (
                    "贺伯安",
                    NameReviewState(
                        status="resolved",
                        confidence="high",
                        proposed_canonical="伯安",
                        evidence_strength="strong",
                    ),
                ),
            ),
        )
        assert validate_state_invariants(state) is True
