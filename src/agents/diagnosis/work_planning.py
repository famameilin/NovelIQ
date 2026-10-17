"""诊断工作的稳定派发范围，不生成任何故事语义

2026-10-15 用户裁定：切分只保留工作边界，不依赖任何数字（既有 token 预算/计量
机器整删，WorkSpec 不再携带阶段字段）；同一 run 的派发身份由契约版本隔离历史行。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from src.utils.identity import stable_digest

# 2026-10-15 用户裁定「不要预算，要切分」+「建一个事件进一个池」：payload 收敛为
# {source_hash, event_ids}，work_id 依赖 payload，契约版本必须推进以防历史
# diagnosis_works 行碰撞。
CONTRACT_VERSION = "event-tree-declarations-v2"
WorkRole = Literal["event", "report"]
# 事件工作先身份后结构两段完成各自义务，收尾报告工作一个会话完成叙事与报告
WorkPhase = Literal["identity", "structure", "report"]


def input_digest(payload: Any) -> str:
    """只对真实业务输入生成摘要，容量租约与模型尝试不属于输入"""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WorkSpec:
    """派发前冻结范围；同一事项不能靠换模型或角色取得新工作身份"""

    run_id: str
    role: WorkRole
    responsible_ids: tuple[str, ...]
    input_payload: dict[str, Any]
    dependencies: tuple[str, ...] = ()
    work_id: str = field(init=False)
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        payload = {"contract_version": CONTRACT_VERSION, "role": self.role,
                   "responsible_ids": list(self.responsible_ids), "input": self.input_payload}
        digest = input_digest(payload)
        object.__setattr__(self, "input_hash", digest)
        object.__setattr__(self, "work_id", stable_digest("diagnosis_work", self.run_id, digest))
