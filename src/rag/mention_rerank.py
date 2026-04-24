"""
Level3 mention-aware 确定性 rerank。

创建时间: 2026-04-24
任务: level3-mention-rerank
说明: 在向量粗召回和 paragraph 局部聚焦之后，用可解释的业务特征重排 mention 检索结果。
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.repositories.chunk import SimilarChunkRow

IDENTITY_CLUE_WORDS = (
    "名叫",
    "叫作",
    "叫做",
    "自称",
    "正是",
    "便是",
    "就是",
    "认出",
    "身份",
    "原来",
    "乃是",
)
FEMALE_ROLE_WORDS = ("女子", "少女", "姑娘", "妇人")
MALE_ROLE_WORDS = ("男子", "汉子", "少年", "青年", "老者", "老人", "公子", "书生", "和尚", "道士")

FEATURE_WEIGHT = 0.04
ACTIVE_ENTITY_WEIGHT = 0.06
CANDIDATE_NAME_WEIGHT = 0.05
IDENTITY_CLUE_WEIGHT = 0.05
ROLE_CONFLICT_PENALTY = 0.08


def rerank_mention_level3_results(
    results: list[SimilarChunkRow],
    *,
    active_entity_names: set[str] | None = None,
    candidate_names: set[str] | None = None,
    current_chunk: int | None = None,
) -> list[SimilarChunkRow]:
    """
    创建时间: 2026-04-24
    任务: level3-mention-rerank
    说明: 对 Level3 召回结果应用轻量确定性 rerank；只改变排序字段，不改 EvidenceBundle 结构。
    """
    if not results:
        return []

    active_names = {name.strip() for name in (active_entity_names or set()) if name.strip()}
    candidate_name_set = {name.strip() for name in (candidate_names or set()) if name.strip()}
    reranked = [
        _score_row(
            result,
            active_entity_names=active_names,
            candidate_names=candidate_name_set,
            current_chunk=current_chunk,
        )
        for result in results
    ]
    return sorted(reranked, key=_sort_key, reverse=True)


def _score_row(
    result: SimilarChunkRow,
    *,
    active_entity_names: set[str],
    candidate_names: set[str],
    current_chunk: int | None,
) -> SimilarChunkRow:
    """
    创建时间: 2026-04-24
    任务: level3-mention-rerank
    说明: 给单条候选计算业务 rerank 分；mention 特征、候选名和历史身份线索都写入可解释字段。

    修改时间: 2026-04-24
    任务: split-level3-score-fields
    修改说明: business rerank 基于显式语义分字段计算，并单独产出 `business_rerank_score` / `final_rank_score`，
              避免继续复用含义漂移的 `similarity`。
    """
    evidence_text = _evidence_text(result)
    normalized_chunk_semantic_score = (
        result.chunk_semantic_score
        if result.chunk_semantic_score is not None
        else None
    )
    normalized_paragraph_semantic_score = (
        result.paragraph_semantic_score
        if result.paragraph_semantic_score is not None
        else None
    )
    if normalized_chunk_semantic_score is None and normalized_paragraph_semantic_score is None:
        normalized_chunk_semantic_score = result.similarity
    semantic_score = (
        normalized_paragraph_semantic_score
        if normalized_paragraph_semantic_score is not None
        else normalized_chunk_semantic_score if normalized_chunk_semantic_score is not None else result.similarity
    )
    feature_overlap = tuple(feature for feature in result.matched_features if feature and feature in evidence_text)
    active_entity_bonus = ACTIVE_ENTITY_WEIGHT if _contains_any(evidence_text, active_entity_names) else 0.0
    candidate_related_bonus = CANDIDATE_NAME_WEIGHT if _contains_any(evidence_text, candidate_names) else 0.0
    identity_clue_bonus = IDENTITY_CLUE_WEIGHT if _has_identity_clue(evidence_text) else 0.0
    time_decay = _time_decay(result.chunk_id, current_chunk)
    penalties = _role_conflict_penalties(result.matched_features, evidence_text)
    rerank_penalty = ROLE_CONFLICT_PENALTY if penalties else 0.0
    business_rerank_score = (
        semantic_score
        + len(feature_overlap) * FEATURE_WEIGHT
        + active_entity_bonus
        + candidate_related_bonus
        + identity_clue_bonus
        + time_decay
        - rerank_penalty
    )

    return replace(
        result,
        similarity=round(business_rerank_score, 6),
        chunk_semantic_score=normalized_chunk_semantic_score,
        paragraph_semantic_score=normalized_paragraph_semantic_score,
        business_rerank_score=round(business_rerank_score, 6),
        final_rank_score=round(business_rerank_score, 6),
        feature_overlap=feature_overlap,
        active_entity_bonus=active_entity_bonus,
        identity_clue_bonus=identity_clue_bonus,
        candidate_related_bonus=candidate_related_bonus,
        time_decay=time_decay,
        rerank_penalty=rerank_penalty,
        penalties=penalties,
    )


def _evidence_text(result: SimilarChunkRow) -> str:
    """
    创建时间: 2026-04-24
    任务: level3-mention-rerank
    说明: paragraph preview 命中时优先把局部片段纳入特征匹配，同时保留完整 chunk 兜底。

    修改时间: 2026-04-24
    任务: fix-mention-rerank-visible-evidence-only
    修改说明: 一旦已选定 local_preview，就只允许基于这段实际会展示给模型的局部 evidence 做加权；
              避免隐藏在完整 chunk 其他位置的身份线索影响排序，导致排序依据与 prompt 可见证据不一致。
    """
    if result.local_preview:
        return result.local_preview
    return result.text or ""


def _contains_any(text: str, names: set[str]) -> bool:
    """
    创建时间: 2026-04-24
    任务: level3-mention-rerank
    说明: 判断候选 evidence 是否包含活跃实体或当前候选名，空集合直接返回 False。
    """
    return any(name in text for name in names)


def _has_identity_clue(text: str) -> bool:
    """
    创建时间: 2026-04-24
    任务: level3-mention-rerank
    说明: 捕捉历史片段中的身份揭示词，作为轻量加权信号而非身份裁决。
    """
    return any(word in text for word in IDENTITY_CLUE_WORDS)


def _time_decay(chunk_id: int, current_chunk: int | None) -> float:
    """
    创建时间: 2026-04-24
    任务: level3-mention-rerank
    说明: 给更近的历史片段小幅加分；未来 chunk 理论上已被 cutoff 排除，这里不额外放行。
    """
    if current_chunk is None or chunk_id >= current_chunk:
        return 0.0
    distance = current_chunk - chunk_id
    if distance <= 10:
        return 0.04
    if distance <= 50:
        return 0.02
    if distance <= 200:
        return 0.01
    return 0.0


def _role_conflict_penalties(matched_features: tuple[str, ...], evidence_text: str) -> tuple[str, ...]:
    """
    创建时间: 2026-04-24
    任务: level3-mention-rerank
    说明: 对明显性别/角色词冲突做轻微扣分，避免“红衣女子”命中“红衣男子”排得过高。
    """
    mention_text = " ".join(matched_features)
    mention_is_female = any(word in mention_text for word in FEMALE_ROLE_WORDS)
    mention_is_male = any(word in mention_text for word in MALE_ROLE_WORDS)
    evidence_is_female = any(word in evidence_text for word in FEMALE_ROLE_WORDS)
    evidence_is_male = any(word in evidence_text for word in MALE_ROLE_WORDS)

    penalties: list[str] = []
    if mention_is_female and evidence_is_male and not evidence_is_female:
        penalties.append("role_conflict:female_vs_male")
    if mention_is_male and evidence_is_female and not evidence_is_male:
        penalties.append("role_conflict:male_vs_female")
    return tuple(penalties)


def _sort_key(result: SimilarChunkRow) -> tuple[float, float, int]:
    """
    创建时间: 2026-04-24
    任务: level3-mention-rerank
    说明: final_rank_score 优先，其次回退语义分；chunk_id 只作为稳定排序的最后兜底。

    修改时间: 2026-04-24
    任务: split-level3-score-fields
    修改说明: 优先按 `final_rank_score` 排序，旧字段只作为兼容回退。
    """
    rank_score = (
        result.final_rank_score
        if result.final_rank_score is not None
        else result.business_rerank_score if result.business_rerank_score is not None else result.similarity
    )
    semantic_base_score = (
        result.paragraph_semantic_score
        if result.paragraph_semantic_score is not None
        else result.chunk_semantic_score if result.chunk_semantic_score is not None else None
    )
    fallback_semantic_score = semantic_base_score if semantic_base_score is not None else result.similarity
    return (rank_score, fallback_semantic_score, -result.chunk_id)
