"""fact_graph 保存使用的冻结贡献；JSON 快照隔离并发可变状态"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.fact_graph.evidence import EvidenceParagraph


@dataclass(frozen=True, slots=True)
class FactContribution:
    run_id: str
    work_id: str
    invocation_id: str
    chapter_id: int
    paragraphs: tuple[EvidenceParagraph, ...]
    snapshot_json: str
    observations_json: str

    def snapshot(self) -> dict[str, Any]:
        """每次解码产生独立容器，调用方不能修改已冻结贡献"""
        return json.loads(self.snapshot_json)

    def observations(self) -> list[dict[str, Any]]:
        return json.loads(self.observations_json)
