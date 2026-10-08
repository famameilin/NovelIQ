"""模型池选举的独立消息契约"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionRequest:
    """只标识待选举工作，不携带正文、角色或业务输入"""

    run_id: str
    work_id: str


@dataclass(frozen=True)
class SelectionResult:
    """队列按结果组装执行信封，容量仍由模型池维护"""

    run_id: str
    work_id: str
    model_id: str
    attempt_number: int
    reservation_id: str
