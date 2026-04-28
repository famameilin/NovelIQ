"""
Evidence / Level3 消费者意图驱动合同

收口 EvidenceRequest / Level3QueryPlan / 请求指纹，避免 workflow/provider 继续通过弱语义参数耦合

将 EvidenceRequest 定义为整个 evidence 层的统一输入合同；
          新增 consumer/requested_names/background_entities/need_level*，
          显式区分“当前要处理的名字”“可用于检索的锚点”和“仅作为背景存在的名字”
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from src.rag.mention_query import MentionEvidenceQuery

EvidenceConsumer = Literal[
    "annotation_phase1",
    "annotation_phase2",
    "annotation_phase3",
    "annotation_phase4",
    "incremental_disambiguation",
    "final_disambiguation",
]
EvidenceObjective = Literal["identity", "emotion", "relation", "foreshadowing"]
Level3QueryMode = Literal["direct", "high_order", "hybrid"]


def _normalize_name_list(values: list[str]) -> list[str]:
    """
    统一清洗显式名字输入；consumer 传进来的请求名单必须稳定去重，
          避免 workflow 因重复/空字符串把 request 语义悄悄放大
    """

    normalized: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _normalize_int_list(values: list[int]) -> list[int]:
    """
    exclude_chunk_ids 也需要稳定去重，保证 request 指纹不会因为重复 cutoff 噪音而失真
    """

    normalized: list[int] = []
    for value in values:
        if value not in normalized:
            normalized.append(value)
    return normalized


def _build_evidence_cache_content_variant(request: EvidenceRequest) -> str:
    """
    cache key 仍尽量忽略纯标签差异，但若某个 consumer 会真的改变 bundle 内容，
          就必须显式打出 content variant；当前仅 annotation_phase1 的 identity+Level3
          会额外合并 emotion overlay，不能再与普通 identity request 共用同一 cache 键
    """

    if request.consumer == "annotation_phase1" and request.objective == "identity" and request.need_level3:
        return "annotation_phase1_identity_with_emotion_overlay"
    return "default"


@dataclass(frozen=True, slots=True)
class EvidenceRequest:
    """
    evidence 层唯一正式输入合同；消费者必须显式声明目标、名字边界、
          层级需求、预算和是否允许 LLM query expansion
    """

    consumer: EvidenceConsumer
    objective: EvidenceObjective
    query_text: str
    requested_names: list[str]
    seed_entities: list[str]
    background_entities: list[str]
    current_chunk: int | None
    max_chunk_id: int | None
    exclude_chunk_ids: list[int]
    need_level1: bool
    need_level2: bool
    need_level3: bool
    allow_llm_query_expansion: bool
    top_k: int
    max_queries: int
    model_rerank_query_max_chars: int

    def __post_init__(self) -> None:
        """
        frozen dataclass 仍在入口统一做 strip/dedupe；
              这样后续 fingerprint、cache 与日志观察字段都能直接消费稳定值
        """

        object.__setattr__(self, "query_text", self.query_text.strip())
        object.__setattr__(self, "requested_names", _normalize_name_list(self.requested_names))
        object.__setattr__(self, "seed_entities", _normalize_name_list(self.seed_entities))
        object.__setattr__(self, "background_entities", _normalize_name_list(self.background_entities))
        object.__setattr__(self, "exclude_chunk_ids", _normalize_int_list(self.exclude_chunk_ids))


@dataclass(frozen=True, slots=True)
class Level3QueryPlan:
    """
    将 query planning 与 retrieval execution 解耦；plan 只描述如何检索，不负责真正执行
    """

    mode: Level3QueryMode
    base_query_text: str
    mention_queries: list[MentionEvidenceQuery]
    candidate_pool_k: int
    top_k: int
    dropped_queries: list[dict[str, str]] = field(default_factory=list)


def build_evidence_request_fingerprint(request: EvidenceRequest) -> tuple[object, ...]:
    """
    指纹服务于 evidence 复用，因此只保留会影响实际取证结果的字段；
              consumer/background_entities 不改变 bundle 内容时，不应阻止 cache reuse

    若某个 consumer 会额外改变 bundle 内容，则要把该 content variant
              纳入 fingerprint，避免 annotation_phase1 的 emotion overlay 污染其他 identity consumer
    """
    return (
        _build_evidence_cache_content_variant(request),
        request.objective,
        request.query_text,
        tuple(request.requested_names),
        tuple(request.seed_entities),
        request.current_chunk,
        request.max_chunk_id,
        tuple(request.exclude_chunk_ids),
        request.need_level1,
        request.need_level2,
        request.need_level3,
        request.allow_llm_query_expansion,
        request.top_k,
        request.max_queries,
        request.model_rerank_query_max_chars,
    )
