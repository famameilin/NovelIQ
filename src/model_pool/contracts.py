"""模型池选举的独立消息契约"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionRequest:
    """只标识待选举工作，不携带正文、角色或业务输入"""

    run_id: str
    work_id: str
    # 依赖屏障后只重获容量，不能计成失败重派或刷新逻辑执行
    resume_attempt: int | None = None
    # 单条工作指定承载模型；不填时按池内权重选举
    fixed_model_id: str | None = None


@dataclass(frozen=True)
class SelectionResult:
    """队列按结果组装执行信封，容量仍由模型池维护

    model_id 是发给端点的模型名（也用于展示），entry_id 是池内条目身份（用于容量与健康分记账）。
    """

    run_id: str
    work_id: str
    model_id: str
    entry_id: str
    attempt_number: int
    reservation_id: str
