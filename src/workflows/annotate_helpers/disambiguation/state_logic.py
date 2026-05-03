"""
状态决策和校验逻辑

从 disambiguation.py 拆分，包含状态决策和校验相关函数
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
from functools import lru_cache
from typing import Any, Literal

from loguru import logger

from src.models.local.character_reference_policy import (
    is_global_character_surface_name,
    is_reference_surface_name,
)
from src.models.local.disambiguation import (
    DisambiguationState,
    ExtendedDisambigResult,
    NameReviewState,
    validate_state_invariants,
)
from src.models.local.disambiguation.constants import PROTECTED_CONTEXT_PREFIX
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

# 只有这几类证据信号，才足以推翻模型给出的“自映射”判断
# naming_scene 和 stable_title_or_rank 被排除在外，
# 因为“和 X 出现在同一上下文里”并不等于“就是 X 的别名”
_OVERRIDE_ALLOWED_SIGNALS: frozenset[str] = frozenset(
    {
        EVIDENCE_SIGNAL_UNIQUE_BODY_MARKER,
        EVIDENCE_SIGNAL_IDENTITY_REVEAL,
    }
)

# protected 候选的硬门禁比普通候选更严格：
# 只有明确身份揭示、命名场景、亲缘身份或独特身体标记这类强证据，
# 才允许把“侍卫/丫鬟/某人”之类的受保护称呼合并到具体角色
_PROTECTED_MERGE_ALLOWED_SIGNALS: frozenset[str] = frozenset(
    {
        EVIDENCE_SIGNAL_UNIQUE_BODY_MARKER,
        EVIDENCE_SIGNAL_NAMING_SCENE,
        EVIDENCE_SIGNAL_KINSHIP_IDENTITY,
        EVIDENCE_SIGNAL_IDENTITY_REVEAL,
    }
)

_CANONICAL_EVIDENCE_SCORE: dict[str, int] = {
    EVIDENCE_SIGNAL_IDENTITY_REVEAL: 50,
    EVIDENCE_SIGNAL_NAMING_SCENE: 45,
    EVIDENCE_SIGNAL_KINSHIP_IDENTITY: 35,
    EVIDENCE_SIGNAL_UNIQUE_BODY_MARKER: 30,
    EVIDENCE_SIGNAL_STABLE_TITLE: 10,
    "original_sentence": 8,
}

_EVIDENCE_STRENGTH_SCORE: dict[str | None, int] = {
    None: 0,
    "weak": 1,
    "mixed": 2,
    "strong": 3,
}

_DESCRIPTOR_LIKE_NAME_PATTERN = re.compile(
    r"(?:[黑白灰青赤紫蓝红金银][^，。；：]{0,4}(?:人|少女|少年|女子|男子|公子)|"
    r"(?:灰衣人|黑衣人|青衣人|白发少女|少年|少女|男子|女子|婴儿|婴孩|灵禽))"
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


# 可被证据门禁视为“结构化证据”的信号
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
    """根据证据画像构建审计字段（证据数量、证据类型）

    为 NameReviewState 填充 decision_evidence_count 和 decision_evidence_types，
          实现文档 §10.4 规划的证据门禁审计链条
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
    """统计候选项的结构化证据条目数

    结构化证据 = 原句证据 + 强信号证据
    （排除不够可靠的 `appearance_only`）
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


@lru_cache(maxsize=1)
def _load_protected_canonical_penalty_names() -> frozenset[str]:
    """
    加载需要在 canonical 重选时降权的泛指/职位称呼

    这里复用候选过滤阶段的 protected 名单，避免 canonical 重选再次把
          “侍卫/丫鬟/某人”这类泛称推成 cluster 的代表名
    """
    # 这里改成惰性 + 缓存加载，避免 import state_logic 时立刻触发
    # CandidateFilter 初始化，把“canonical 重选需要的 protected 名单”收敛为按需依赖
    from .candidate_filter import CandidateFilter

    return CandidateFilter().protected


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


def _is_protected_candidate_context(context: str | None) -> bool:
    """
    判断上下文是否来自 protected 候选

    protected 分类不会单独进入响应 schema，因此这里复用 prompt 前缀把分类带到
          证据门禁层，统一覆盖增量/最终、本地/云端消歧链路
    """
    if not context:
        return False
    return context.strip().startswith(PROTECTED_CONTEXT_PREFIX)


def _is_descriptor_like_name(name: str) -> bool:
    """
    判断一个称呼是否更像外貌/泛指描述，而不是稳定 canonical

    配对完成后，canonical 选择不能再被“灰衣人/侍卫/某人”这类描述称呼卡死
          这里故意只做保守降权，不直接判死刑，真正的 tie-break 仍会结合证据与频次
    """
    stripped_name = name.strip()
    if not stripped_name:
        return True
    if is_reference_surface_name(stripped_name):
        return True
    if stripped_name in _load_protected_canonical_penalty_names():
        return True
    return _DESCRIPTOR_LIKE_NAME_PATTERN.search(stripped_name) is not None


def _canonical_signal_score(review: NameReviewState | None) -> int:
    """
    计算单个名字作为 canonical 候选时的证据分

    这里使用 review_status 里的审计字段，而不是依赖当前 alias 方向；
          这样即便 earlier post-process 已经把方向翻错，终消歧阶段仍可重新纠正
    """
    if review is None:
        return 0

    score = 0
    for evidence_type in review.decision_evidence_types:
        score += _CANONICAL_EVIDENCE_SCORE.get(evidence_type, 0)
    score += review.decision_evidence_count
    return score


def _canonical_choice_key(
    name: str,
    review: NameReviewState | None,
    name_counts: dict[str, int] | None,
) -> tuple[int, int, int, int, int, str]:
    """
    生成 canonical 候选排序键

    canonical 选择明确拆成独立阶段后，优先级应是：
          1. 避免描述称呼卡住 canonical
          2. 看程序化证据和证据强度
          3. 再把频次作为最后兜底，而不是直接改写 alias 语义
    """
    review_confidence = _normalize_disambig_confidence(review.confidence) if review is not None else "medium"
    return (
        0 if _is_descriptor_like_name(name) else 1,
        _canonical_signal_score(review),
        _EVIDENCE_STRENGTH_SCORE.get(review.evidence_strength if review is not None else None, 0),
        _disambig_confidence_rank(review_confidence),
        int(name_counts.get(name, 0)) if name_counts else 0,
        name,
    )


def _collect_alias_clusters(
    alias_merges: dict[str, str],
    affected_names: set[str] | None = None,
) -> list[set[str]]:
    """
    从 alias_merges 构建待重选的 cluster

    alias 配对与 canonical 选择必须解耦；这里先只关心“哪些名字已被判成同一人”
    """
    adjacency: dict[str, set[str]] = {}
    for alias, canonical in alias_merges.items():
        adjacency.setdefault(alias, set()).add(canonical)
        adjacency.setdefault(canonical, set()).add(alias)

    if not adjacency:
        return []

    remaining_nodes = set(adjacency)
    candidate_roots = set(adjacency) if affected_names is None else (set(affected_names) & set(adjacency))
    clusters: list[set[str]] = []

    while candidate_roots:
        root = candidate_roots.pop()
        if root not in remaining_nodes:
            continue

        stack = [root]
        cluster: set[str] = set()
        while stack:
            node = stack.pop()
            if node in cluster:
                continue
            cluster.add(node)
            stack.extend(adjacency.get(node, ()))

        remaining_nodes.difference_update(cluster)
        candidate_roots.difference_update(cluster)
        if len(cluster) > 1:
            clusters.append(cluster)

    return clusters


def reselect_cluster_canonicals(
    state: DisambiguationState,
    *,
    name_counts: dict[str, int] | None = None,
    affected_names: set[str] | None = None,
) -> DisambiguationState:
    """
    在 alias 配对完成后，独立重选每个 cluster 的 canonical

    旧逻辑会在写入前按频次直接翻转 canonical 方向，导致
          “灰衣人 -> 白芷”这类已配对成功的结果被反写成“白芷 -> 灰衣人”
          现在改为：
          1. 先保留 alias 配对语义；
          2. 再按 cluster 维度独立重选 canonical；
          3. 频次只做 tie-break，不再直接改写配对阶段的判断
    """
    alias_merges_dict = state.get_alias_merges_dict()
    clusters = _collect_alias_clusters(alias_merges_dict, affected_names=affected_names)
    if not clusters:
        return state

    review_status = state.get_review_status_dict()
    new_known_canonical = set(state.known_canonical_names)
    new_alias_merges = dict(alias_merges_dict)
    new_review_status = dict(review_status)
    rewired_clusters: list[tuple[list[str], str]] = []

    for cluster in clusters:
        # 这里不再信任“当前 alias 方向”本身，因为它可能已经被旧的频次翻转污染；
        # 我们只把 cluster 当作“这些名字属于同一人”的集合，再重新挑代表名
        selected_canonical = max(
            cluster,
            key=lambda candidate_name: _canonical_choice_key(
                candidate_name,
                review_status.get(candidate_name),
                name_counts,
            ),
        )

        cluster_changed = False
        for name in cluster:
            if name == selected_canonical:
                if new_alias_merges.pop(name, None) is not None:
                    cluster_changed = True
                review = new_review_status.get(name)
                if review is not None:
                    normalized_status = (
                        review.status if review.status != DISAMBIG_STATE_UNRESOLVED else DISAMBIG_STATE_REVIEW
                    )
                    updated_review = replace(
                        review,
                        status=normalized_status,
                        proposed_canonical=name,
                    )
                    if updated_review != review:
                        new_review_status[name] = updated_review
                        cluster_changed = True
                continue

            previous_target = new_alias_merges.get(name)
            if previous_target != selected_canonical:
                new_alias_merges[name] = selected_canonical
                cluster_changed = True

            review = new_review_status.get(name)
            if review is not None:
                normalized_status = (
                    review.status if review.status != DISAMBIG_STATE_UNRESOLVED else DISAMBIG_STATE_REVIEW
                )
                updated_review = replace(
                    review,
                    status=normalized_status,
                    proposed_canonical=selected_canonical,
                )
                if updated_review != review:
                    new_review_status[name] = updated_review
                    cluster_changed = True

        new_known_canonical.difference_update(cluster)
        new_known_canonical.add(selected_canonical)
        if cluster_changed:
            rewired_clusters.append((sorted(cluster), selected_canonical))

    new_state = state.with_updates(
        known_canonical_names=frozenset(new_known_canonical),
        alias_merges=frozenset(
            (alias, canonical) for alias, canonical in new_alias_merges.items() if alias != canonical
        ),
        review_status=tuple(new_review_status.items()),
    )
    validate_state_invariants(new_state)

    if rewired_clusters:
        logger.info(
            "Reselected canonicals for {} alias clusters: {}",
            len(rewired_clusters),
            rewired_clusters,
        )

    return new_state


def apply_model_reselected_canonicals(
    state: DisambiguationState,
    canonical_decisions: dict[str, str],
    *,
    clusters: list[set[str]],
) -> DisambiguationState:
    """
    将模型输出的最终代表名重选结果应用到既有 alias cluster

    这一步只允许“在已确认 cluster 内重选代表名”，不允许模型新增/删除成员、
          拆组，或跨 cluster 指向。若输出不合法，直接抛错，避免静默污染最终图谱
    """
    if not clusters:
        return state

    expected_names = {name for cluster in clusters for name in cluster}
    missing_names = expected_names - set(canonical_decisions)
    if missing_names:
        raise ValueError(f"Missing canonical reselect decisions for names: {sorted(missing_names)}")

    alias_merges_dict = state.get_alias_merges_dict()
    review_status = state.get_review_status_dict()
    cluster_lookup = {name: cluster for cluster in clusters for name in cluster}

    # 先把待重选 cluster 之外的 alias 保留下来，确保这次额外调用只影响
    # 最终代表名选择，不会顺手改动无关 cluster 的既有合并结果
    new_alias_merges = {
        alias: canonical for alias, canonical in alias_merges_dict.items() if alias not in expected_names
    }
    for alias, canonical in alias_merges_dict.items():
        if alias not in expected_names and canonical in expected_names:
            raise ValueError(f"Unexpected cross-cluster alias edge: {alias} -> {canonical}")

    new_known_canonical = set(state.known_canonical_names)
    new_review_status = dict(review_status)
    rewired_clusters: list[tuple[list[str], str]] = []

    for cluster in clusters:
        cluster_decisions = {name: canonical_decisions[name] for name in cluster}
        invalid_targets = {
            name: target for name, target in cluster_decisions.items() if target not in cluster_lookup.get(name, set())
        }
        if invalid_targets:
            raise ValueError(f"Invalid canonical reselect targets: {invalid_targets}")

        selected_targets = set(cluster_decisions.values())
        if len(selected_targets) != 1:
            raise ValueError(
                f"Canonical reselect must converge to exactly one target per cluster: "
                f"{sorted(cluster)} -> {sorted(selected_targets)}"
            )

        selected_canonical = next(iter(selected_targets))
        cluster_changed = False
        for name in cluster:
            if name == selected_canonical:
                review = new_review_status.get(name)
                if review is not None:
                    updated_review = replace(
                        review,
                        status=review.status if review.status != DISAMBIG_STATE_UNRESOLVED else DISAMBIG_STATE_REVIEW,
                        proposed_canonical=name,
                    )
                    if updated_review != review:
                        new_review_status[name] = updated_review
                        cluster_changed = True
                continue

            previous_target = new_alias_merges.get(name)
            if previous_target != selected_canonical:
                new_alias_merges[name] = selected_canonical
                cluster_changed = True

            review = new_review_status.get(name)
            if review is not None:
                updated_review = replace(
                    review,
                    status=review.status if review.status != DISAMBIG_STATE_UNRESOLVED else DISAMBIG_STATE_REVIEW,
                    proposed_canonical=selected_canonical,
                )
                if updated_review != review:
                    new_review_status[name] = updated_review
                    cluster_changed = True

        new_known_canonical.difference_update(cluster)
        new_known_canonical.add(selected_canonical)
        if cluster_changed:
            rewired_clusters.append((sorted(cluster), selected_canonical))

    new_state = state.with_updates(
        known_canonical_names=frozenset(new_known_canonical),
        alias_merges=frozenset(
            (alias, canonical) for alias, canonical in new_alias_merges.items() if alias != canonical
        ),
        review_status=tuple(new_review_status.items()),
    )
    validate_state_invariants(new_state)

    if rewired_clusters:
        logger.info(
            "Applied model-selected canonicals for {} alias clusters: {}",
            len(rewired_clusters),
            rewired_clusters,
        )

    return new_state


def _has_protected_merge_evidence(profile: EvidenceProfile | None) -> bool:
    """
    判断受保护候选是否具备允许合并的强证据

    “默认不合并”在后端必须是硬约束，只有明确身份揭示/命名/亲缘/唯一标记
          这类强证据才能放行，避免模型凭共现或一般上下文把通用职位直接并错
    """
    if profile is None:
        return False
    if profile.strength != EVIDENCE_STRENGTH_STRONG:
        return False
    return any(signal in _PROTECTED_MERGE_ALLOWED_SIGNALS for signal in profile.strong_signals)


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

    实现证据分级约束规则

    规则：
    1. 仅【前文摘要-弱证据】支持的判断，alias_confidence 最高为 medium
    2. 若 alias_map 指向已有角色，但证据唯一来源是弱证据，禁止合并



    Args:
        result: 消歧结果
        existing_names: 已存在的角色名列表

    Returns:
        校验后的消歧结果
    """
    existing_set = set(existing_names) if existing_names else set()

    # 结构化证据门禁：高置信合并必须有相应证据支撑
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
        context = context_sentences.get(name, "") if context_sentences else ""
        is_protected_candidate = _is_protected_candidate_context(context)

        current_confidence = result.alias_confidence.get(name, DISAMBIG_CONFIDENCE_MEDIUM)

        if canonical != name and is_protected_candidate and not _has_protected_merge_evidence(profile):
            logger.info(
                "Preventing protected-candidate merge for '{}' -> '{}': no strong protected evidence",
                name,
                canonical,
            )
            result.canonical_decisions[name] = name
            result.alias_confidence[name] = DISAMBIG_CONFIDENCE_MEDIUM
            continue

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

    将 canonical_decisions 分流到三层状态

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: 代词/局部引用需要进入 unresolved_references/reference_resolutions，
          不能污染 known_canonical_names 或 alias_merges。

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
    new_unresolved_references = set(state.unresolved_references)
    new_reference_resolutions: dict[str, str] = dict(state.reference_resolutions)
    new_review_status: dict[str, NameReviewState] = dict(state.review_status)

    for name, canonical in result.canonical_decisions.items():
        new_discovered.add(name)

        raw_confidence = result.alias_confidence.get(name, "medium")
        confidence = _normalize_disambig_confidence(raw_confidence)
        evidence_profile = result.evidence_profiles.get(name)
        evidence_strength = _normalize_evidence_strength(evidence_profile.strength if evidence_profile else None)

        # 保护已有的“非自映射”决定，不要被新的自映射判断直接覆盖
        old_review = new_review_status.get(name)
        if (
            old_review is not None
            and old_review.proposed_canonical is not None
            and old_review.proposed_canonical != name
            and canonical == name  # 新决定是自映射
        ):
            # 除非新置信度更高，否则不要用自映射覆盖已有的非自映射
            if _disambig_confidence_rank(confidence) <= _disambig_confidence_rank(old_review.confidence):
                logger.debug(
                    f"Protecting existing merge '{name}->{old_review.proposed_canonical}' "
                    f"(conf={old_review.confidence}) from self-map downgrade "
                    f"(new conf={confidence})"
                )
                continue

        evidence_count, evidence_types = _build_evidence_audit_fields(evidence_profile)

        # 引用 surface 只能记录为“未解析引用”或“引用 -> 实名解析”，不能写入普通 alias/canonical 主链
        if is_reference_surface_name(name):
            has_confirmed_reference_resolution = (
                canonical != name
                and is_global_character_surface_name(canonical)
                and confidence == DISAMBIG_CONFIDENCE_HIGH
                and evidence_strength in ("mixed", "strong")
            )
            if has_confirmed_reference_resolution:
                new_discovered.add(canonical)
                new_known_canonical.add(canonical)
                new_unresolved_references.discard(name)
                new_reference_resolutions[name] = canonical
                new_review_status[name] = NameReviewState(
                    status=DISAMBIG_STATE_RESOLVED,
                    confidence=confidence,
                    proposed_canonical=canonical,
                    evidence_strength=evidence_strength,
                    decision_evidence_count=evidence_count,
                    decision_evidence_types=evidence_types,
                    decision_source="llm",
                    decision_timestamp=time.time(),
                )
            else:
                new_reference_resolutions.pop(name, None)
                new_unresolved_references.add(name)
                new_review_status[name] = NameReviewState(
                    status=DISAMBIG_STATE_UNRESOLVED,
                    confidence=confidence,
                    proposed_canonical=None,
                    evidence_strength=evidence_strength,
                    decision_evidence_count=evidence_count,
                    decision_evidence_types=evidence_types,
                    decision_source="llm",
                    decision_timestamp=time.time(),
                )
            continue

        if name == canonical:
            is_confirmed_canonical = (
                confidence == DISAMBIG_CONFIDENCE_HIGH and evidence_strength in ("mixed", "strong")
            )
            if is_confirmed_canonical and is_global_character_surface_name(name):
                new_known_canonical.add(name)
            status_value = DISAMBIG_STATE_RESOLVED if is_confirmed_canonical else DISAMBIG_STATE_REVIEW
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
        elif is_global_character_surface_name(canonical):
            new_discovered.add(canonical)
            new_known_canonical.add(canonical)

            new_alias_merges.append((name, canonical))

            status_value = (
                DISAMBIG_STATE_RESOLVED if confidence == DISAMBIG_CONFIDENCE_HIGH else DISAMBIG_STATE_REVIEW
            )
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
        else:
            logger.warning(
                "Ignoring invalid canonical target for '{}': '{}' is a reference surface",
                name,
                canonical,
            )
            new_review_status[name] = NameReviewState(
                status=DISAMBIG_STATE_REVIEW,
                confidence=confidence,
                proposed_canonical=None,
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

    # 降级机制：如果先前已 resolved 的名字现在被降回 review，
    # 就移除它的 alias_merge，避免图谱里残留过期合并结果
    # P1 修复：在降级循环内直接过滤 alias_merges，
    # 而不是循环后重建 new_alias_merges，避免数据流被遮蔽
    old_review_dict = state.get_review_status_dict()
    demoted_aliases: set[str] = set()
    for name, review in new_review_status.items():
        old_review = old_review_dict.get(name)
        if (
            old_review
            and old_review.status == DISAMBIG_STATE_RESOLVED
            and review.status != DISAMBIG_STATE_RESOLVED
        ):
            logger.warning(f"Demoting resolved name '{name}' from '{old_review.status}' to '{review.status}'")
            demoted_aliases.add(name)
    # 单独做一轮 alias 过滤，避免遍历时原地修改列表
    if demoted_aliases:
        new_alias_merges = [(a, c) for a, c in new_alias_merges if a not in demoted_aliases]

    final_alias_merges: list[tuple[str, str]] = []
    seen_aliases: set[str] = set()
    for alias, target in new_alias_merges:
        if (
            alias != target
            and alias not in seen_aliases
            and not is_reference_surface_name(alias)
            and is_global_character_surface_name(target)
        ):
            final_alias_merges.append((alias, target))
            seen_aliases.add(alias)

    new_known_canonical = {name for name in new_known_canonical if is_global_character_surface_name(name)}

    new_state = state.with_updates(
        discovered_names=frozenset(new_discovered),
        known_canonical_names=frozenset(new_known_canonical),
        alias_merges=frozenset(final_alias_merges),
        unresolved_references=frozenset(new_unresolved_references),
        reference_resolutions=frozenset(new_reference_resolutions.items()),
        review_status=tuple(new_review_status.items()),
    )

    validate_state_invariants(new_state)

    return new_state
