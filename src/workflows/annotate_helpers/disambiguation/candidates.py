"""
候选名字收集和筛选

从 disambiguation.py 拆分，包含候选名字收集和筛选相关函数
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from loguru import logger

from src.models.disambiguation_types import NameCountCandidate
from src.models.local.disambiguation.evidence_renderer import (
    DisambiguationPromptContext,
    build_disambiguation_prompt_context,
    render_disambiguation_graph_hint,
    render_existing_character_hint,
)
from src.storage.repositories.annotation.characters import (
    fetch_all_character_names,
    fetch_reference_aware_character_names,
    fetch_relation_reference_candidates,
    fetch_relation_reference_contexts,
)
from src.storage.repositories.graph import CurrentRelationRow

from ..sentence import build_context_sentences
from .candidate_filter import CandidateClassification, CandidateFilter
from .state_logic import (
    DISAMBIG_CONFIDENCE_HIGH,
    DISAMBIG_STATE_RESOLVED,
)

EXTENSION_REVIEW_MIN_GAP = 3
EXTENSION_REVIEW_MIN_RATIO = 1.5


@dataclass(frozen=True)
class DisambigStateSnapshotEntry:
    """终消歧候选收集所需的最小 review 快照"""

    state: str
    confidence: str
    canonical: str


@dataclass
class DisambigStateSnapshot:
    """终消歧候选收集的具名快照容器"""

    entries: dict[str, DisambigStateSnapshotEntry] = field(default_factory=dict)

    def get(self, name: str) -> DisambigStateSnapshotEntry | None:
        return self.entries.get(name)

    def setdefault(self, name: str, entry: DisambigStateSnapshotEntry) -> DisambigStateSnapshotEntry:
        return self.entries.setdefault(name, entry)

    def copy(self) -> DisambigStateSnapshot:
        return DisambigStateSnapshot(entries=dict(self.entries))

    def __bool__(self) -> bool:
        return bool(self.entries)


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

        # 数据库返回的是宽松字典，这里收口成 NameCountCandidate，
        # 避免把仓储层的松散返回形状继续泄漏到消歧主链
        payload.append({"name": name, "count": count})
    return payload


def _build_name_count_lookup(all_names: list[NameCountCandidate]) -> dict[str, int]:
    """为最终消歧启发式构建 name -> count 查询表"""
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


def _merge_name_count_candidates(
    *candidate_groups: Sequence[NameCountCandidate | dict[str, str | int]],
) -> list[NameCountCandidate]:
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: chunk_characters 和 relation-only endpoint 现在会同时提供候选，
              这里统一按名字聚合频次，避免增量和终态各自重复写一遍合并逻辑。
    """
    merged_counts: dict[str, int] = {}
    for group in candidate_groups:
        for item in group:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            raw_count = item.get("count", 0)
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                count = 0
            merged_counts[name] = merged_counts.get(name, 0) + count
    return [{"name": name, "count": count} for name, count in sorted(merged_counts.items(), key=lambda x: -x[1])]


def fetch_reference_aware_disambiguation_candidates(
    conn,
    run_id: str,
    *,
    max_chunk_id: int | None = None,
) -> list[NameCountCandidate]:
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: 关系端点候选必须和 chunk_characters 候选一起进入增量/终态消歧，
              否则 relation-only endpoint 永远不会进入 reference_resolutions。
    """
    character_candidates = fetch_reference_aware_character_names(conn, run_id, max_chunk_id=max_chunk_id)
    relation_candidates = fetch_relation_reference_candidates(conn, run_id, max_chunk_id=max_chunk_id)
    return _merge_name_count_candidates(character_candidates, relation_candidates)


def build_candidate_context_sentences(
    conn,
    candidates: list[NameCountCandidate],
    alias_keywords: list[str] | None = None,
    *,
    run_id: str,
    max_chunk_id: int | None = None,
    prev_chunks: int | None = None,
    chunk_start_id: int | None = None,
    chunk_end_id: int | None = None,
) -> dict[str, str]:
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: slot 候选既需要普通例句上下文，也需要关系证据上下文，
              这里统一拼装，避免增量/终态各自漏掉 relation-only endpoint 的可读证据。
    """
    context_sentences = build_context_sentences(
        conn,
        candidates,
        alias_keywords,
        run_id=run_id,
        max_chunk_id=max_chunk_id,
        prev_chunks=prev_chunks,
        chunk_start_id=chunk_start_id,
        chunk_end_id=chunk_end_id,
    )
    relation_contexts = fetch_relation_reference_contexts(
        conn,
        run_id,
        [str(item.get("name", "")).strip() for item in candidates if str(item.get("name", "")).strip()],
        max_chunk_id=max_chunk_id,
        chunk_start_id=chunk_start_id,
        chunk_end_id=chunk_end_id,
    )
    for name, relation_context in relation_contexts.items():
        sentence_context = context_sentences.get(name, "").strip()
        if sentence_context:
            context_sentences[name] = f"{relation_context} | 例句上下文：{sentence_context}"
        else:
            context_sentences[name] = relation_context
    return context_sentences


def _is_self_resolved_leaf(name: str, alias_map: dict[str, str]) -> bool:
    """
    判断该名字当前是否解析到自身，且没有作为其他别名的 canonical 目标

    This targets the "early self-mapped and then locked" case like 贺伯安 -> 贺伯安
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

    对"已 resolved 但可能只是早期自映射"的名字重新放入 final review
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
    构建最终消歧候选集



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
            snapshot_entry = state_snapshot.get(name)
            state = snapshot_entry.state if snapshot_entry is not None else None

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
    relations: Sequence[CurrentRelationRow],
    existing_names: list[str],
    candidate_names: list[str],
) -> DisambiguationPromptContext | None:
    """将图谱权威数据补入消歧任务上下文"""

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
    relations: Sequence[CurrentRelationRow],
    current_chunk_id: int | None = None,
    chunk_start_id: int | None = None,
    chunk_end_id: int | None = None,
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
        chunk_start_id=chunk_start_id,
        chunk_end_id=chunk_end_id,
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

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: 消歧候选需要 reference-aware 入口，未解析代词/局部引用不能在进消歧前被 global-only 出口提前过滤。

    基于当前 chunk 及之前所有 chunk 的标注结果，提取不在 alias_map 中的新人物名


    """
    existing_names = set(alias_map.keys()) | set(alias_map.values()) if alias_map else set()
    all_names = fetch_reference_aware_disambiguation_candidates(conn, run_id, max_chunk_id=current_chunk_id)

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
    snapshot = state_snapshot.copy() if state_snapshot is not None else DisambigStateSnapshot()
    for alias, canonical in alias_map.items():
        snapshot.setdefault(
            alias,
            DisambigStateSnapshotEntry(
                state=DISAMBIG_STATE_RESOLVED,
                confidence=DISAMBIG_CONFIDENCE_HIGH,
                canonical=canonical,
            ),
        )
        snapshot.setdefault(
            canonical,
            DisambigStateSnapshotEntry(
                state=DISAMBIG_STATE_RESOLVED,
                confidence=DISAMBIG_CONFIDENCE_HIGH,
                canonical=canonical,
            ),
        )
    for canonical in known_canonical_names or set():
        snapshot.setdefault(
            canonical,
            DisambigStateSnapshotEntry(
                state=DISAMBIG_STATE_RESOLVED,
                confidence=DISAMBIG_CONFIDENCE_HIGH,
                canonical=canonical,
            ),
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
    """基于候选分类器过滤候选名

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
