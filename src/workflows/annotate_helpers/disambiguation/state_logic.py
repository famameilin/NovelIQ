"""
状态决策和校验逻辑

创建时间: 2026-03-27
创建者: TraeAI
任务: disambiguation-module-split
说明: 从 disambiguation.py 拆分，包含状态决策和校验相关函数
"""

from __future__ import annotations

import time
from typing import Any, Literal

from loguru import logger

from src.models.local.disambiguation import (
    DisambiguationState,
    ExtendedDisambigResult,
    NameReviewState,
    validate_state_invariants,
)
from src.models.local.disambiguation.evidence import (
    EVIDENCE_SIGNAL_IDENTITY_REVEAL,
    EVIDENCE_SIGNAL_KINSHIP_IDENTITY,
    EVIDENCE_SIGNAL_NAMING_SCENE,
    EVIDENCE_SIGNAL_STABLE_TITLE,
    EVIDENCE_SIGNAL_UNIQUE_BODY_MARKER,
    EVIDENCE_STRENGTH_STRONG,
    EVIDENCE_STRENGTH_WEAK,
    EvidenceProfile,
)

DISAMBIG_CONFIDENCE_LOW = "low"
DISAMBIG_CONFIDENCE_MEDIUM = "medium"
DISAMBIG_CONFIDENCE_HIGH = "high"
VALID_DISAMBIG_CONFIDENCE = {
    DISAMBIG_CONFIDENCE_LOW,
    DISAMBIG_CONFIDENCE_MEDIUM,
    DISAMBIG_CONFIDENCE_HIGH,
}

_DisambigStateLiteral = Literal["resolved", "review", "unresolved"]
DISAMBIG_STATE_RESOLVED: _DisambigStateLiteral = "resolved"
DISAMBIG_STATE_REVIEW: _DisambigStateLiteral = "review"
DISAMBIG_STATE_UNRESOLVED: _DisambigStateLiteral = "unresolved"

# Only these evidence signals justify overriding a model's self-mapping decision.
# naming_scene and stable_title_or_rank are excluded because "being mentioned in
# the same context as X" does NOT imply "is an alias of X".
_OVERRIDE_ALLOWED_SIGNALS: frozenset[str] = frozenset(
    {
        EVIDENCE_SIGNAL_UNIQUE_BODY_MARKER,
        EVIDENCE_SIGNAL_IDENTITY_REVEAL,
    }
)


def _normalize_disambig_confidence(confidence: Any) -> Literal["low", "medium", "high"]:
    if isinstance(confidence, str):
        normalized = confidence.lower().strip()
        if normalized in VALID_DISAMBIG_CONFIDENCE:
            return normalized  # type: ignore[return-value]
    return "medium"


_CONFIDENCE_RANK: dict[str, int] = {"low": 1, "medium": 2, "high": 3}


def _disambig_confidence_rank(confidence: str) -> int:
    return _CONFIDENCE_RANK.get(confidence, 2)


# Signals that count as "structured evidence" for the evidence gate.
_STRUCTURED_EVIDENCE_SIGNALS = frozenset(
    {
        EVIDENCE_SIGNAL_NAMING_SCENE,
        EVIDENCE_SIGNAL_UNIQUE_BODY_MARKER,
        EVIDENCE_SIGNAL_KINSHIP_IDENTITY,
        EVIDENCE_SIGNAL_IDENTITY_REVEAL,
        EVIDENCE_SIGNAL_STABLE_TITLE,
    }
)


def _build_evidence_audit_fields(profile: EvidenceProfile | None) -> tuple[int, tuple[str, ...]]:
    """Build audit fields (evidence count, evidence types) from an evidence profile.

    创建时间: 2026-04-02
    创建者: CodeAI
    任务: fix/decision-evidence-audit
    说明: 为 NameReviewState 填充 decision_evidence_count 和 decision_evidence_types，
          实现文档 §10.4 规划的证据门禁审计链条。
    """
    if profile is None:
        return 0, ()
    count = 0
    types: list[str] = []
    if profile.has_original_sentence:
        count += 1
        types.append("original_sentence")
    for signal in profile.strong_signals:
        if signal in _STRUCTURED_EVIDENCE_SIGNALS:
            count += 1
            types.append(signal)
    return count, tuple(types)


def _count_structured_evidence(profile: EvidenceProfile | None) -> int:
    """Count structured evidence items for a candidate.

    Structured evidence = original sentences + strong signals
    (excluding appearance_only which is not reliable).
    """
    if profile is None:
        return 0
    count = 0
    if profile.has_original_sentence:
        count += 1
    for signal in profile.strong_signals:
        if signal in _STRUCTURED_EVIDENCE_SIGNALS:
            count += 1
    return count


def _normalize_evidence_strength(strength: Any) -> Literal["weak", "mixed", "strong"] | None:
    if isinstance(strength, str):
        normalized = strength.lower().strip()
        if normalized in ("weak", "mixed", "strong"):
            return normalized  # type: ignore[return-value]
    return None


def _name_variants_for_matching(name: str) -> set[str]:
    return {name} if name else set()


def _find_existing_name_mentions(context: str, existing_names: list[str] | None) -> list[str]:
    if not context or not existing_names:
        return []

    matches: list[str] = []
    for existing_name in existing_names:
        if any(variant in context for variant in _name_variants_for_matching(existing_name)):
            matches.append(existing_name)
    return matches


def _has_only_weak_evidence(profile: EvidenceProfile | None) -> bool:
    if profile is None:
        return False
    return (
        profile.strength == EVIDENCE_STRENGTH_WEAK
        and not profile.has_original_sentence
        and not profile.has_identity_clue
    )


def _has_strong_merge_signal(profile: EvidenceProfile | None) -> bool:
    if profile is None:
        return False
    if profile.strength != EVIDENCE_STRENGTH_STRONG:
        return False
    return any(signal in _OVERRIDE_ALLOWED_SIGNALS for signal in profile.strong_signals)


def _apply_strong_evidence_merge_override(
    name: str,
    result: ExtendedDisambigResult,
    existing_names: list[str] | None,
    context_sentences: dict[str, str] | None,
) -> None:
    profile = result.evidence_profiles.get(name)
    if not _has_strong_merge_signal(profile):
        return

    context = context_sentences.get(name, "") if context_sentences else ""
    matched_existing_names = _find_existing_name_mentions(context, existing_names)
    if len(matched_existing_names) != 1:
        return

    target = matched_existing_names[0]
    if target == name:
        return

    logger.info(
        "Promoting strong-evidence self-mapping '{}' -> '{}' based on unique anchor mention in context",
        name,
        target,
    )
    result.canonical_decisions[name] = target
    result.alias_confidence[name] = DISAMBIG_CONFIDENCE_HIGH


def validate_confidence_with_evidence(
    result: ExtendedDisambigResult,
    existing_names: list[str] | None = None,
    context_sentences: dict[str, str] | None = None,
) -> ExtendedDisambigResult:
    """
    根据证据来源校验置信度

    创建时间: 2026-03-26
    创建者: TraeAI
    任务: disambiguation-evidence-grading
    说明: 实现证据分级约束规则

    规则：
    1. 仅【前文摘要-弱证据】支持的判断，alias_confidence 最高为 medium
    2. 若 alias_map 指向已有角色，但证据唯一来源是弱证据，禁止合并

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: 简化消歧响应模型
    修改内容: 将 merge_target_map 改为 alias_map

    Args:
        result: 消歧结果
        existing_names: 已存在的角色名列表

    Returns:
        校验后的消歧结果
    """
    existing_set = set(existing_names) if existing_names else set()

    # Structured evidence gate: high-confidence merges must have evidence
    for name, canonical in result.canonical_decisions.items():
        current_confidence = result.alias_confidence.get(name, DISAMBIG_CONFIDENCE_MEDIUM)
        if current_confidence == DISAMBIG_CONFIDENCE_HIGH and canonical != name:
            evidence_count = _count_structured_evidence(result.evidence_profiles.get(name))
            if evidence_count == 0:
                logger.info(
                    f"Blocking high-confidence merge for '{name}': "
                    f"no structured evidence (0 evidence items), downgrading to medium"
                )
                result.alias_confidence[name] = DISAMBIG_CONFIDENCE_MEDIUM

    for name, canonical in result.canonical_decisions.items():
        _apply_strong_evidence_merge_override(name, result, existing_names, context_sentences)
        canonical = result.canonical_decisions.get(name, canonical)
        profile = result.evidence_profiles.get(name)
        only_weak_evidence = _has_only_weak_evidence(profile)

        current_confidence = result.alias_confidence.get(name, DISAMBIG_CONFIDENCE_MEDIUM)

        if only_weak_evidence and current_confidence == DISAMBIG_CONFIDENCE_HIGH:
            logger.debug(f"Downgrading confidence for '{name}' from high to medium due to weak evidence only")
            result.alias_confidence[name] = DISAMBIG_CONFIDENCE_MEDIUM

        is_merging_to_existing = canonical in existing_set and canonical != name
        if is_merging_to_existing and only_weak_evidence:
            logger.info(f"Preventing merge of '{name}' to existing character '{canonical}' due to weak evidence only")
            result.canonical_decisions[name] = name
            result.alias_confidence[name] = DISAMBIG_CONFIDENCE_MEDIUM

    return result


def apply_disambiguation_decisions(
    state: DisambiguationState,
    result: ExtendedDisambigResult,
) -> DisambiguationState:
    """
    将模型决策应用到状态

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 将 canonical_decisions 分流到三层状态

    处理逻辑：
    1. A -> A 自映射：加入 discovered_names 和 known_canonical_names，不写入 alias_merges
    2. A -> B 别名合并：A、B 加入 discovered_names，B 加入 known_canonical_names，写入 alias_merges[A] = B
    3. canonical 被撤销时：更新 alias_merges 和 review_status 中的引用

    Args:
        state: 当前消歧状态
        result: 模型输出结果（包含 canonical_decisions）

    Returns:
        更新后的新状态实例
    """
    new_discovered = set(state.discovered_names)
    new_known_canonical = set(state.known_canonical_names)
    new_alias_merges: list[tuple[str, str]] = list(state.alias_merges)
    new_review_status: dict[str, NameReviewState] = dict(state.review_status)

    for name, canonical in result.canonical_decisions.items():
        new_discovered.add(name)

        raw_confidence = result.alias_confidence.get(name, "medium")
        confidence = _normalize_disambig_confidence(raw_confidence)
        evidence_profile = result.evidence_profiles.get(name)
        evidence_strength = _normalize_evidence_strength(evidence_profile.strength if evidence_profile else None)

        # Protect existing non-self-map decisions from being overwritten by self-maps.
        old_review = new_review_status.get(name)
        if (
            old_review is not None
            and old_review.proposed_canonical is not None
            and old_review.proposed_canonical != name
            and canonical == name  # new decision is self-map
        ):
            # Don't overwrite a non-self-map with a self-map unless confidence is higher
            if _disambig_confidence_rank(confidence) <= _disambig_confidence_rank(old_review.confidence):
                logger.debug(
                    f"Protecting existing merge '{name}->{old_review.proposed_canonical}' "
                    f"(conf={old_review.confidence}) from self-map downgrade "
                    f"(new conf={confidence})"
                )
                continue

        if name == canonical:
            is_confirmed_canonical = confidence == DISAMBIG_CONFIDENCE_HIGH and evidence_strength in ("mixed", "strong")
            if is_confirmed_canonical:
                new_known_canonical.add(name)
            status_value = DISAMBIG_STATE_RESOLVED if is_confirmed_canonical else DISAMBIG_STATE_REVIEW
            evidence_count, evidence_types = _build_evidence_audit_fields(evidence_profile)
            new_review_status[name] = NameReviewState(
                status=status_value,
                confidence=confidence,
                proposed_canonical=name,
                evidence_strength=evidence_strength,
                decision_evidence_count=evidence_count,
                decision_evidence_types=evidence_types,
                decision_source="llm",
                decision_timestamp=time.time(),
            )
        else:
            new_discovered.add(canonical)
            new_known_canonical.add(canonical)

            new_alias_merges.append((name, canonical))

            status_value = DISAMBIG_STATE_RESOLVED if confidence == DISAMBIG_CONFIDENCE_HIGH else DISAMBIG_STATE_REVIEW
            evidence_count, evidence_types = _build_evidence_audit_fields(evidence_profile)
            new_review_status[name] = NameReviewState(
                status=status_value,
                confidence=confidence,
                proposed_canonical=canonical,
                evidence_strength=evidence_strength,
                decision_evidence_count=evidence_count,
                decision_evidence_types=evidence_types,
                decision_source="llm",
                decision_timestamp=time.time(),
            )

    old_canonicals = state.known_canonical_names
    new_canonicals = frozenset(new_known_canonical)
    demoted_canonicals = old_canonicals - new_canonicals

    if demoted_canonicals:
        logger.info(f"Canonical demotion detected: {demoted_canonicals}")

        canonical_replacement: dict[str, str] = {}
        for demoted in demoted_canonicals:
            for alias, target in result.canonical_decisions.items():
                if alias == demoted and target != demoted:
                    canonical_replacement[demoted] = target
                    break

        for demoted, new_target in canonical_replacement.items():
            for i, (alias, target) in enumerate(new_alias_merges):
                if target == demoted:
                    new_alias_merges[i] = (alias, new_target)
                    logger.debug(f"Updated alias_merges: {alias} -> {new_target} (was {demoted})")

        for name, review in list(new_review_status.items()):
            if review.proposed_canonical in demoted_canonicals:
                new_target = canonical_replacement.get(review.proposed_canonical, name)
                new_review_status[name] = NameReviewState(
                    status="review",
                    confidence=review.confidence,
                    proposed_canonical=new_target,
                    evidence_strength=review.evidence_strength,
                    decision_evidence_count=review.decision_evidence_count,
                    decision_evidence_types=review.decision_evidence_types,
                    decision_source=review.decision_source,
                    decision_timestamp=review.decision_timestamp,
                )

    # Demotion mechanism: if a previously resolved name is now demoted to review,
    # remove its alias_merge entry to prevent stale merges in the graph.
    # P1 fix: filter alias_merges INLINE during the demotion loop instead of
    # rebuilding new_alias_merges after the loop (which obscured the data flow).
    old_review_dict = state.get_review_status_dict()
    demoted_aliases: set[str] = set()
    for name, review in new_review_status.items():
        old_review = old_review_dict.get(name)
        if old_review and old_review.status == DISAMBIG_STATE_RESOLVED and review.status != DISAMBIG_STATE_RESOLVED:
            logger.warning(f"Demoting resolved name '{name}' from '{old_review.status}' to '{review.status}'")
            demoted_aliases.add(name)
    # Apply alias_filter in a separate pass to avoid modifying list during iteration.
    if demoted_aliases:
        new_alias_merges = [(a, c) for a, c in new_alias_merges if a not in demoted_aliases]

    final_alias_merges: list[tuple[str, str]] = []
    seen_aliases: set[str] = set()
    for alias, target in new_alias_merges:
        if alias != target and alias not in seen_aliases:
            final_alias_merges.append((alias, target))
            seen_aliases.add(alias)

    new_state = state.with_updates(
        discovered_names=frozenset(new_discovered),
        known_canonical_names=frozenset(new_known_canonical),
        alias_merges=frozenset(final_alias_merges),
        review_status=tuple(new_review_status.items()),
    )

    validate_state_invariants(new_state)

    return new_state
