"""case_pool 保存使用的冻结贡献；JSON 快照隔离并发可变状态

作者身份：Agent 形状是真实执行号，程序形状是程序 work 身份（两者都是单一字符串，
按 work_items 是否登记该身份区分形状，不双存第二份作者列）。
"""

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
