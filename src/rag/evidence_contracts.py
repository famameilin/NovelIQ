"""
Evidence 消费者意图驱动合同

收口 EvidenceRequest / 请求指纹，避免 workflow/provider 继续通过弱语义参数耦合

RAG 检索粒度固定为一个自然段：EvidenceRequest 只描述“要什么”，
Level3 执行层统一走 run 级段落检索，不再存在 query planner / mention / rerank 规格
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EvidenceConsumer = Literal[
    "annotation_agent",
    "diagnosis_agent",
]
EvidenceObjective = Literal["identity", "emotion", "relation", "foreshadowing"]


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


@dataclass(frozen=True, slots=True)
class EvidenceRequest:
    """
    evidence 层唯一正式输入合同；消费者必须显式声明目标、名字边界、层级需求与预算
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
    top_k: int
    reference_slots: list[str] = field(default_factory=list)
    request_observation: dict[str, int] = field(default_factory=dict)

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
        object.__setattr__(self, "reference_slots", _normalize_name_list(self.reference_slots))
        object.__setattr__(self, "request_observation", dict(self.request_observation))


def build_evidence_request_fingerprint(request: EvidenceRequest) -> tuple[object, ...]:
    """
    指纹服务于 evidence 复用，因此只保留会影响实际取证结果的字段；
    consumer/background_entities 不改变 bundle 内容时，不应阻止 cache reuse
    """
    return (
        request.objective,
        request.query_text,
        tuple(request.requested_names),
        tuple(request.seed_entities),
        tuple(request.reference_slots),
        request.current_chunk,
        request.max_chunk_id,
        tuple(request.exclude_chunk_ids),
        request.need_level1,
        request.need_level2,
        request.need_level3,
        request.top_k,
    )
