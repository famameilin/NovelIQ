"""
Level3 mention extraction 共享类型。

将规则版与 LLM 版 mention extraction 的数据合同抽到独立模块，避免下游绑定某一种抽取实现。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PersonMention:
    """
    描述性人物 mention 的统一结构；新增字段均为可选，保持旧 query builder 的消费合同兼容。
    """

    raw_text: str
    mention_type: str
    sentence_text: str
    cues: dict[str, str | list[str]]
    confidence: float | None = None
    span_start: int | None = None
    span_end: int | None = None
    normalized_query_terms: tuple[str, ...] = ()
    source: str = "rule"


@dataclass(frozen=True, slots=True)
class MentionExtractionRequest:
    """
    provider 传给 mention extraction service 的最小上下文，LLM 只负责发现 mention，不做身份裁决。
    """

    text: str
    names_in_chunk: tuple[str, ...] = ()
    context_text: str | None = None
    run_id: str | None = None
    current_chunk: int | None = None
