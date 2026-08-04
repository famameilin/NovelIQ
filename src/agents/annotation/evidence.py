"""
标注 Agent 证据审计账本

记录历史自然段证据和三层证据工具调用，供 finish 引用校验与模型交互审计
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.rag.evidence_types import EvidenceItem


@dataclass(slots=True)
class HistoricalEvidenceEntry:
    """历史原文证据条目"""

    evidence_id: str
    evidence_type: str
    source: str
    text: str
    chunk_id: int | None
    paragraph_index: int | None
    global_start_char: int | None
    global_end_char: int | None
    score: float | None
    objectives: list[str] = field(default_factory=list)
    retrieval_methods: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    match_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """
        2026-08-02 用于把历史自然段证据转换为可持久化审计结构
        """
        return asdict(self)


@dataclass(slots=True)
class EvidenceToolCallRecord:
    """三层证据工具调用记录"""

    tool_name: str
    objective: str
    request: dict[str, Any]
    status: str
    evidence_ids: list[str] = field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """
        2026-08-02 用于把证据工具调用转换为可持久化审计结构
        """
        return asdict(self)


@dataclass(slots=True)
class AnnotationEvidenceLedger:
    """单个标注 Agent 会话的历史证据与工具调用账本"""

    entries: dict[str, HistoricalEvidenceEntry] = field(default_factory=dict)
    tool_calls: list[EvidenceToolCallRecord] = field(default_factory=list)

    def register_evidence_items(
        self,
        items: list[EvidenceItem],
        *,
        objective: str,
    ) -> list[str]:
        """
        2026-08-03 用于登记并合并统一历史取证证据及其来源信息
        """
        registered_ids: list[str] = []
        for item in items:
            if not item.evidence_id:
                continue
            evidence_id = item.evidence_id
            metadata = item.metadata
            existing = self.entries.get(evidence_id)
            if existing is None:
                existing = HistoricalEvidenceEntry(
                    evidence_id=evidence_id,
                    evidence_type=item.evidence_type,
                    source=item.source,
                    text=item.content,
                    chunk_id=item.chunk_id,
                    paragraph_index=_optional_int(metadata.get("paragraph_index")),
                    global_start_char=_optional_int(metadata.get("global_start_char")),
                    global_end_char=_optional_int(metadata.get("global_end_char")),
                    score=item.score,
                    objectives=[],
                    retrieval_methods=[],
                    sources=[],
                    matched_keywords=[],
                    match_count=None,
                )
                self.entries[evidence_id] = existing
            if objective not in existing.objectives:
                existing.objectives.append(objective)
            if item.retrieval_method and item.retrieval_method not in existing.retrieval_methods:
                existing.retrieval_methods.append(item.retrieval_method)
            if item.source and item.source not in existing.sources:
                existing.sources.append(item.source)
            for keyword in _optional_string_list(metadata.get("matched_keywords")):
                if keyword not in existing.matched_keywords:
                    existing.matched_keywords.append(keyword)
            raw_match_count = metadata.get("match_count")
            if raw_match_count is not None:
                match_count = int(raw_match_count)
                existing.match_count = max(existing.match_count or 0, match_count)
            registered_ids.append(evidence_id)
        return registered_ids

    def record_tool_call(
        self,
        *,
        tool_name: str,
        objective: str,
        request: dict[str, Any],
        status: str,
        evidence_ids: list[str] | None = None,
        error: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        """
        2026-08-02 用于按调用顺序登记三层证据工具的请求结果和失败信息
        """
        self.tool_calls.append(
            EvidenceToolCallRecord(
                tool_name=tool_name,
                objective=objective,
                request=dict(request),
                status=status,
                evidence_ids=list(evidence_ids or []),
                error=error,
                duration_ms=max(0, int(duration_ms)),
            )
        )

    def unknown_evidence_ids(self, evidence_ids: list[str]) -> list[str]:
        """
        2026-08-02 用于找出 finish 引用但本轮未检索到的历史证据 ID
        """
        return sorted({evidence_id for evidence_id in evidence_ids if evidence_id not in self.entries})

    def citation_objective_mismatches(
        self,
        citations: list[tuple[str, str]],
    ) -> list[str]:
        """
        2026-08-02 用于找出引用用途与检索目标不一致的历史证据
        """
        mismatches: list[str] = []
        for evidence_id, purpose in citations:
            entry = self.entries.get(evidence_id)
            if entry is None or purpose == "other":
                continue
            if purpose not in entry.objectives:
                mismatches.append(f"{evidence_id}:{purpose}")
        return sorted(set(mismatches))

    def has_chunk_reference(self, chunk_id: int, *, objective: str) -> bool:
        """
        2026-08-02 用于判断历史 chunk 是否已被同一检索目标的本轮证据定位
        """
        return any(
            entry.chunk_id == chunk_id and objective in entry.objectives
            for entry in self.entries.values()
        )

    def to_dict(self) -> dict[str, Any]:
        """
        2026-08-02 用于生成模型交互记录中的完整证据审计载荷
        """
        return {
            "historical_evidence": [
                self.entries[evidence_id].to_dict()
                for evidence_id in sorted(self.entries)
            ],
            "tool_calls": [record.to_dict() for record in self.tool_calls],
        }


def _optional_int(value: Any) -> int | None:
    """
    2026-08-02 用于把证据元数据中的可选数值稳定转换为整数
    """
    if value is None:
        return None
    return int(value)


def _optional_string_list(value: Any) -> list[str]:
    """
    2026-08-03 用于把证据元数据中的可选关键词列表转换为稳定字符串列表
    """
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
