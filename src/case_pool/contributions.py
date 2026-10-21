"案例登记与提交的冻结保存请求"

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CaseContribution:
    run_id: str
    author: str
    snapshot_json: str

    def snapshot(self) -> dict[str, Any]:
        """每次解码产生独立容器，调用方不能修改已冻结贡献"""
        return json.loads(self.snapshot_json)
