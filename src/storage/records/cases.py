"案例持久化输入；领域实体、办理状态及内存确认仍归 case_pool"

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CaseSave:
    "一次已冻结案例贡献的普通存储映射，不包含事务或运行时对象"

    run_id: str
    author: str
    snapshot_json: str

    def snapshot(self) -> dict[str, Any]:
        "解码产生独立容器，防止保存期间被业务修改"
        return json.loads(self.snapshot_json)
