"""event_trees 保存使用的冻结贡献；JSON 快照隔离并发可变状态"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.fact_graph.evidence import EvidenceParagraph


@dataclass(frozen=True, slots=True)
class EventContribution:
    run_id: str
    agent_id: str
    chapter_order: int
    paragraphs: tuple[EvidenceParagraph, ...]
    snapshot_json: str
    entities_json: str

    def snapshot(self) -> dict[str, Any]:
        """每次解码产生独立容器，调用方不能修改已冻结贡献"""
        return json.loads(self.snapshot_json)

    def entities(self) -> dict[str, Any]:
        return json.loads(self.entities_json)

    def actions(self) -> dict[str, dict[str, Any]]:
        return self.snapshot().get("actions", {})
