"""
候选名字收集和筛选

创建时间: 2026-03-27
创建者: TraeAI
任务: disambiguation-module-split
说明: 从 disambiguation.py 拆分，包含候选名字收集和筛选相关函数
"""

from __future__ import annotations

from collections.abc import Sequence

from loguru import logger

from src.models.disambiguation_types import NameCountCandidate
from src.models.local.disambiguation.evidence_renderer import (
    DisambiguationPromptContext,
    build_disambiguation_prompt_context,
    render_disambiguation_graph_hint,
    render_existing_character_hint,
)
from src.storage.repositories.annotation.characters import fetch_all_character_names

from ..sentence import build_context_sentences
from .candidate_filter import CandidateClassification, CandidateFilter
from .state_logic import (
    DISAMBIG_CONFIDENCE_HIGH,
    DISAMBIG_STATE_RESOLVED,
)

EXTENSION_REVIEW_MIN_GAP = 3
EXTENSION_REVIEW_MIN_RATIO = 1.5

DisambigStateSnapshot = dict[str, dict[str, str]]


def _extract_names_from_candidates(candidates: list[NameCountCandidate]) -> list[str]:
    return [str(item.get("name", "")) for item in candidates if str(item.get("name", ""))]


def _build_candidate_payload_by_names(
    all_names: Sequence[NameCountCandidate | dict[str, str | int]],
    candidate_names: list[str],
) -> list[NameCountCandidate]:
    names_set = set(candidate_names)
    payload: list[NameCountCandidate] = []
    for item in all_names:
        name = str(item.get("name", ""))
        if name not in names_set:
            continue

        raw_count = item.get("count", 0)
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            count = 0

        # 中文注释：数据库返回的是宽松字典，这里收口成 NameCountCandidate，
        # 避免把仓储层的松散返回形状继续泄漏到消歧主链。
        payload.append({"name": name, "count": count})
    return payload


def _build_name_count_lookup(all_names: list[NameCountCandidate]) -> dict[str, int]:
    """Build a name -> count lookup for final disambiguation heuristics."""
    name_counts: dict[str, int] = {}
    for item in all_names:
        name = str(item.get("name", ""))
        if not name:
            continue
        raw_count = item.get("count", 0)
        try:
            name_counts[name] = int(raw_count)
        except (TypeError, ValueError):
            name_counts[name] = 0
    return name_counts


def _is_self_resolved_leaf(name: str, alias_map: dict[str, str]) -> bool:
    """
    Whether the name is currently resolved to itself and not acting as another alias's canonical target.

    This targets the "early self-mapped and then locked" case like 贺伯安 -> 贺伯安.
    """
    if alias_map.get(name, name) != name:
        return False
    return not any(alias != name and canonical == name for alias, canonical in alias_map.items())


def _has_more_frequent_related_name(
    name: str,
    name_counts: dict[str, int],
) -> bool:
    """
    判断名字是否存在更高频的相关称呼

    典型场景：
    - 贺伯安 / 伯安
    - 小侯爷 / 侯爷

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: 修复 final candidate 收集逻辑
    说明: 对"已 resolved 但可能只是早期自映射"的名字重新放入 final review
    """
    current_count = name_counts.get(name, 0)
    if current_count <= 0:
        return False

    for candidate, candidate_count in name_counts.items():
        if candidate == name:
            continue
        if candidate not in name:
            continue
        if candidate_count <= current_count:
            continue
        if candidate_count - current_count < EXTENSION_REVIEW_MIN_GAP:
            continue
        if candidate_count / current_count < EXTENSION_REVIEW_MIN_RATIO:
            continue
        return True
    return False


def _collect_final_disambiguation_candidates(
    all_names: list[NameCountCandidate],
    alias_map: dict[str, str],
    state_snapshot: DisambigStateSnapshot | None = None,
) -> list[str]:
    """
    Build candidates for final disambiguation.

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: 项目文件结构整理与拆解

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: 修复 final candidate 收集逻辑
    修改内容: 低频名和高频名扩展形式不再被"早期自映射"锁死，允许重新进入 final review

    新规则：
    - state=resolved 不再直接跳过
    - 对于"自映射且没有其他别名指向它"的叶子节点，如果存在更高频的相关称呼，允许重新进入 final review
    - state 只影响优先级，不直接决定"永不复审"
    """
    names = _extract_names_from_candidates(all_names)
    name_counts = _build_name_count_lookup(all_names)
    candidates: list[str] = []
    seen: set[str] = set()

    for name in names:
        if name in seen:
            continue

        needs_review = False

        if state_snapshot:
            state = state_snapshot.get(name, {}).get("state")

            if state != DISAMBIG_STATE_RESOLVED:
                needs_review = True
            elif _is_self_resolved_leaf(name, alias_map) and _has_more_frequent_related_name(name, name_counts):
                needs_review = True
                logger.debug(f"Re-reviewing self-resolved leaf with stronger related name: {name}")
        else:
            known_names = set(alias_map.keys()) | set(alias_map.values())
            if name not in known_names:
                needs_review = True

        if needs_review:
            candidates.append(name)
            seen.add(name)

    return candidates


def _augment_prompt_context_with_graph(
    prompt_context: DisambiguationPromptContext | None,
    alias_map: dict[str, str],
    relations: list[dict],
    existing_names: list[str],
    candidate_names: list[str],
) -> DisambiguationPromptContext | None:
    """将图谱权威数据补入消歧任务上下文。"""

    graph_hint = render_disambiguation_graph_hint(
        alias_map,
        relations,
        existing_names,
        candidate_names=candidate_names,
    )
    if prompt_context is None and graph_hint is None:
        return None

    return build_disambiguation_prompt_context(
        existing_character_hint=prompt_context.existing_character_hint if prompt_context else None,
        graph_hint=graph_hint or (prompt_context.graph_hint if prompt_context else None),
        shared_evidence_context=prompt_context.shared_evidence_context if prompt_context else None,
    )


def _build_existing_character_hint_from_db(
    conn,
    candidate_names: list[str],
    existing_names: list[str],
    alias_keywords: list[str],
    run_id: str,
    alias_map: dict[str, str],
    relations: list[dict],
    current_chunk_id: int | None = None,
) -> DisambiguationPromptContext | None:
    all_names = fetch_all_character_names(conn, run_id, max_chunk_id=current_chunk_id)
    existing_payload = _build_candidate_payload_by_names(all_names, existing_names)
    if not existing_payload:
        return None

    existing_context_sentences = build_context_sentences(
        conn,
        existing_payload,
        alias_keywords,
        run_id=run_id,
        max_chunk_id=current_chunk_id,
    )
    prompt_context = build_disambiguation_prompt_context(
        existing_character_hint=render_existing_character_hint(
            existing_names,
            existing_context_sentences,
            candidate_names=candidate_names,
        )
    )

    return _augment_prompt_context_with_graph(
        prompt_context,
        alias_map,
        relations,
        existing_names,
        candidate_names,
    )


def extract_new_names_from_db(
    conn,
    alias_map: dict[str, str],
    run_id: str,
    current_chunk_id: int | None = None,
) -> list[NameCountCandidate]:
    """
    从数据库中提取新出现的人名（带频次）

    基于当前 chunk 及之前所有 chunk 的标注结果，提取不在 alias_map 中的新人物名。

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复增量消歧只提取当前chunk的问题
    修改内容: 从所有已标注的chunk中提取新名字，使用 fetch_chunk_characters_full

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复候选人名没有频次的问题
    修改内容: 返回带频次的字典列表 [{"name": "伯安", "count": 312}, ...]
    """
    existing_names = set(alias_map.keys()) | set(alias_map.values()) if alias_map else set()
    all_names = fetch_all_character_names(conn, run_id, max_chunk_id=current_chunk_id)

    candidates: list[NameCountCandidate] = []
    for item in all_names:
        name = str(item.get("name", "")).strip()
        if not name or name in existing_names:
            continue
        raw_count = item.get("count", 0)
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            count = 0
        candidates.append({"name": name, "count": count})

    return candidates


def _ensure_state_snapshot_has_known_names(
    alias_map: dict[str, str],
    state_snapshot: DisambigStateSnapshot | None,
    known_canonical_names: set[str] | frozenset[str] | None = None,
) -> DisambigStateSnapshot:
    snapshot: DisambigStateSnapshot = dict(state_snapshot or {})
    for alias, canonical in alias_map.items():
        snapshot.setdefault(
            alias,
            {
                "state": DISAMBIG_STATE_RESOLVED,
                "confidence": DISAMBIG_CONFIDENCE_HIGH,
                "canonical": canonical,
            },
        )
        snapshot.setdefault(
            canonical,
            {
                "state": DISAMBIG_STATE_RESOLVED,
                "confidence": DISAMBIG_CONFIDENCE_HIGH,
                "canonical": canonical,
            },
        )
    for canonical in known_canonical_names or set():
        snapshot.setdefault(
            canonical,
            {
                "state": DISAMBIG_STATE_RESOLVED,
                "confidence": DISAMBIG_CONFIDENCE_HIGH,
                "canonical": canonical,
            },
        )
    return snapshot


def filter_candidates_by_class(
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str] | None = None,
    candidate_filter: CandidateFilter | None = None,
) -> tuple[
    list[NameCountCandidate],
    list[NameCountCandidate],
    list[NameCountCandidate],
    list[CandidateClassification],
]:
    """基于候选分类器过滤候选名。

    返回:
        filtered: 被黑名单过滤的候选（丢弃）
        deferred: 延后处理的候选（本轮不送模型，但保留到后续复审/终消歧）
        remaining: 保留的候选（protected + normal，送消歧）
        classifications: 所有候选的分类结果（用于审计和 prompt 标记）
    """
    if candidate_filter is None:
        candidate_filter = CandidateFilter()

    filtered_cls, deferred_cls, remaining_cls = candidate_filter.classify_batch(
        [dict(c) for c in candidates],
        context_sentences,
    )

    filtered_names = {c.name for c in filtered_cls}
    deferred_names = {c.name for c in deferred_cls}
    filtered: list[NameCountCandidate] = [c for c in candidates if c["name"] in filtered_names]
    deferred: list[NameCountCandidate] = [c for c in candidates if c["name"] in deferred_names]
    remaining: list[NameCountCandidate] = [
        c for c in candidates if c["name"] not in filtered_names and c["name"] not in deferred_names
    ]
    all_classifications = filtered_cls + deferred_cls + remaining_cls

    if filtered:
        logger.info(
            f"Candidate filter: filtered {len(filtered)} candidates: "
            f"{[c.name + '(' + c.reason + ')' for c in filtered_cls]}"
        )

    if deferred:
        logger.info(
            f"Candidate filter: deferred {len(deferred)} candidates: "
            f"{[c.name + '(' + c.reason + ')' for c in deferred_cls]}"
        )

    return filtered, deferred, remaining, all_classifications
