"""
模型客户端协议接口定义。

创建时间: 2026-03-24
创建者: Codex
任务: decouple-unified-client-phase1
说明:
- 为 workflow 层提供最小能力接口，减少对具体客户端实现的类型耦合
- 仅约束 workflow 实际使用的方法与属性

修改时间: 2026-03-29
修改者: TraeAI
任务: simplify-phase1-prompt
修改内容: 移除 prev_chunk_text 和 next_chunk_text 参数

修改时间: 2026-04-09
修改者: TraeAI
任务: refactor/annotate-async
修改内容: annotate_chunk 改为返回 Awaitable[MultiPhaseAnnotationResult]
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from src.api.models.events import StreamEvent
from src.models.disambiguation_types import NameCountCandidate
from src.models.local.annotation import MultiPhaseAnnotationResult
from src.models.local.disambiguation import DisambiguationPromptContext, ExtendedDisambigResult


@runtime_checkable
class AnnotationLike(Protocol):
    """标注能力协议（workflow 侧最小接口）。"""

    _config: Any
    _novel_id: str | None
    _token_usage_callback: Any

    def set_session(self, session: Any) -> None: ...

    def set_runtime_context(self, novel_id: str | None, token_usage_callback: Any) -> None: ...

    async def annotate_chunk(
        self,
        text: str,
        prev_summary: str | None = None,
        alias_map: dict[str, str] | None = None,
        chunk_id: int | None = None,
        global_context: str | None = None,
        active_entities: str | None = None,
        evidence_bundle: Any | None = None,
        cloud_client: AnnotationLike | None = None,
        run_id: str | None = None,
        disambig_context: str | None = None,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> MultiPhaseAnnotationResult: ...


@runtime_checkable
class DisambiguationLike(Protocol):
    """消歧能力协议（workflow 侧最小接口）。"""

    _config: Any
    _novel_id: str | None
    _token_usage_callback: Any

    def set_session(self, session: Any) -> None: ...

    def set_runtime_context(self, novel_id: str | None, token_usage_callback: Any) -> None: ...

    async def disambiguate_characters(
        self,
        candidates: list[NameCountCandidate],
        context_sentences: dict[str, str] | None = None,
        existing_names: list[str] | None = None,
        prompt_context: DisambiguationPromptContext | None = None,
    ) -> ExtendedDisambigResult: ...

    def is_cloud_api(self) -> bool: ...

    async def generate_summary(self, messages: list[dict[str, str]], max_tokens: int = 150) -> str: ...
