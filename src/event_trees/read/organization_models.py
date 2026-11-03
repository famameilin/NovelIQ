"""事件组织只读值与读取错误"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class RunRequiresRebuildError(ValueError):
    """旧契约运行不接受读取层转换，必须修正正式链后从原文重建"""

    def __init__(self) -> None:
        super().__init__("该运行为旧契约，需要从原文重建")


@dataclass(frozen=True)
class EventView:
    """事件正文、章节范围及真实来源"""

    event_id: str
    producer_agent_id: str
    local_key: str
    reason: str | None
    title: str
    problem: str
    summary: str
    event_type: str
    status: str
    progress: str | None
    first_text_position: int | None
    evidence: list[dict[str, Any]]
    source_agent_id: str | None
    annotation_record_id: str | None
    from_chapter_id: int
    to_chapter_id: int
    chapter_id: int | None
    chapter_order: int | None
    participants: list[dict[str, Any]]
    is_foreshadowing_root: bool
    payoff_likelihood: str | None
    char_start: int
    char_end: int
    is_event_line: bool = False

    @property
    def payload_path(self) -> str:
        return f"event/{self.event_id}"

    @property
    def strength(self) -> str | None:
        return self.payoff_likelihood


@dataclass(frozen=True)
class LinkView:
    """语义/因果链路的读取形状（两端都引用完整事件或事件）"""

    relation_id: str
    source_kind: str
    source_id: str
    target_kind: str
    target_id: str
    relation_type: str
    reason: str
    evidence: list[dict[str, Any]]
    producer_agent_id: str
    source_operation_id: str | None


@dataclass(frozen=True)
class OutcomeView:
    """事件结果读取形状"""

    outcome_id: str
    title: str
    description: str
    first_text_position: int
    evidence: list[dict[str, Any]]
    producer_agent_id: str


@dataclass(frozen=True)
class ForeshadowingView:
    """引用来源事件和可选目标事件的伏笔动作"""

    action_id: str
    action_type: str
    endpoint_kind: str
    source_event_id: str
    target_event_id: str | None
    chapter_id: int | None
    chapter_order: int | None
    source_operation_id: str
    evidence: list[dict[str, Any]]
    operation_order: int = 0
    evidence_scope: str = "paragraph"
