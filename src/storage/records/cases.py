"案例持久化输入；领域实体、办理状态及内存确认仍归 case_pool"

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CaseSave:
    "一次已冻结案例贡献的普通存储映射，不包含事务或运行时对象"

    run_id: str
    author: str | None
    snapshot_json: str

    def snapshot(self) -> dict[str, Any]:
        "解码产生独立容器，防止保存期间被业务修改"
        return json.loads(self.snapshot_json)


def root_event_case_description(event_id: str) -> str:
    "自动根案例的稳定文字描述包含完整事件身份"
    return f"请处理事件 {event_id} 的建树与核查事项"
