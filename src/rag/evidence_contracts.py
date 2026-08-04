"""
Evidence 消费者意图驱动合同

收口 EvidenceRequest / 请求指纹，避免 workflow/provider 继续通过弱语义参数耦合

历史取证统一使用 keyword、semantic、read 三种模式；当前 chunk 的历史边界由服务根据请求派生
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EvidenceConsumer = Literal[
    "annotation_agent",
    "diagnosis_agent",
]
EvidenceObjective = Literal["identity", "emotion", "relation", "foreshadowing"]
EvidenceRetrievalMethod = Literal["keyword", "semantic", "read"]


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


def _normalize_keyword_list(values: list[str]) -> list[str]:
    """
    统一清洗关键词输入并保持首次出现顺序
    """
    normalized: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


@dataclass(frozen=True, slots=True)
class EvidenceRequest:
    """
    evidence 层唯一正式输入合同；历史边界和读取授权由 NarrativeEvidenceService 统一执行
    """

    consumer: EvidenceConsumer
    objective: EvidenceObjective
    mode: EvidenceRetrievalMethod | None = None
    query_text: str = ""
    keywords: list[str] = field(default_factory=list)
    read_chunk_id: int | None = None
    requested_names: list[str] = field(default_factory=list)
    seed_entities: list[str] = field(default_factory=list)
    background_entities: list[str] = field(default_factory=list)
    current_chunk: int | None = None
    max_chunk_id: int | None = None
    exclude_chunk_ids: list[int] = field(default_factory=list)
    need_level1: bool = False
    need_level2: bool = False
    top_k: int = 5
    reference_slots: list[str] = field(default_factory=list)
    request_observation: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """
        frozen dataclass 在入口统一清洗请求字段，使边界、缓存和审计消费稳定值
        """
        object.__setattr__(self, "query_text", self.query_text.strip())
        object.__setattr__(self, "keywords", _normalize_keyword_list(self.keywords))
        object.__setattr__(self, "requested_names", _normalize_name_list(self.requested_names))
        object.__setattr__(self, "seed_entities", _normalize_name_list(self.seed_entities))
        object.__setattr__(self, "background_entities", _normalize_name_list(self.background_entities))
        object.__setattr__(self, "exclude_chunk_ids", _normalize_int_list(self.exclude_chunk_ids))
        object.__setattr__(self, "reference_slots", _normalize_name_list(self.reference_slots))
        object.__setattr__(self, "request_observation", dict(self.request_observation))
        object.__setattr__(self, "top_k", max(0, int(self.top_k)))

    def historical_max_chunk_id(self) -> int | None:
        """
        根据当前 chunk 派生历史检索上限
        """
        if self.current_chunk is not None:
            return self.current_chunk - 1
        return self.max_chunk_id

    def historical_exclude_chunk_ids(self) -> list[int]:
        """
        合并调用方排除集合与当前 chunk，形成服务统一使用的排除条件
        """
        excluded = list(self.exclude_chunk_ids)
        if self.current_chunk is not None and self.current_chunk not in excluded:
            excluded.append(self.current_chunk)
        return _normalize_int_list(excluded)


def build_evidence_request_fingerprint(request: EvidenceRequest) -> tuple[object, ...]:
    """
    构造会影响证据结果、历史边界和读取授权的稳定缓存指纹
    """
    return (
        request.consumer,
        request.objective,
        request.mode,
        request.query_text,
        tuple(request.keywords),
        request.read_chunk_id,
        tuple(request.requested_names),
        tuple(request.seed_entities),
        tuple(request.reference_slots),
        request.current_chunk,
        request.historical_max_chunk_id(),
        tuple(request.historical_exclude_chunk_ids()),
        request.need_level1,
        request.need_level2,
        request.top_k,
    )
