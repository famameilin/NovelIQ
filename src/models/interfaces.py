"""
模型客户端协议接口定义。

创建时间: 2026-03-24
创建者: Codex
任务: decouple-unified-client-phase1
说明:
- 为 workflow 层提供最小能力接口，减少对具体客户端实现的类型耦合
- 仅约束 workflow 实际使用的方法与属性
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable

from src.models.local.annotation import MultiPhaseAnnotationResult
from src.models.local.disambiguation import ExtendedDisambigResult


@runtime_checkable
class AnnotationLike(Protocol):
    """标注能力协议（workflow 侧最小接口）。"""

    _config: Any
    _novel_id: str | None
    _token_usage_callback: Any

    def set_session(self, session: Any) -> None:
        ...

    def set_runtime_context(self, novel_id: str | None, token_usage_callback: Any) -> None:
        ...

    def annotate_chunk(
        self,
        text: str,
        prev_summary: str | None = None,
        alias_map: Dict[str, str] | None = None,
        chunk_id: int | None = None,
        global_context: str | None = None,
        prev_chunk_text: str | None = None,
        active_entities: str | None = None,
        rag_evidence: str | None = None,
        known_aliases: str | None = None,
        next_chunk_text: str | None = None,
        cloud_client: "AnnotationLike | None" = None,
        run_id: str | None = None,
        character_appearances: List[dict] | None = None,
    ) -> MultiPhaseAnnotationResult:
        ...


@runtime_checkable
class DisambiguationLike(Protocol):
    """消歧能力协议（workflow 侧最小接口）。"""

    _config: Any
    _novel_id: str | None
    _token_usage_callback: Any

    def set_session(self, session: Any) -> None:
        ...

    def set_runtime_context(self, novel_id: str | None, token_usage_callback: Any) -> None:
        ...

    def disambiguate_characters(
        self,
        candidates: List[str] | List[Dict[str, int]],
        context_sentences: Dict[str, str] | None = None,
        existing_names: List[str] | None = None,
        rag_hint: str | None = None,
    ) -> ExtendedDisambigResult:
        ...

    def is_cloud_api(self) -> bool:
        ...
