"""case_pool 保存使用的冻结贡献；JSON 快照隔离并发可变状态"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CaseContribution:
    run_id: str
    work_id: str
    invocation_id: str
    snapshot_json: str

    def snapshot(self) -> dict[str, Any]:
        """每次解码产生独立容器，调用方不能修改已冻结贡献"""
        return json.loads(self.snapshot_json)
