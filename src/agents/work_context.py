"""审计记录共享工作身份，模型成功与业务提交结果分别保存"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentWorkContext:
    work_id: str
    attempt_epoch: int
    cutoff_hash: str
    provider_id: str


current_agent_work: ContextVar[AgentWorkContext | None] = ContextVar("current_agent_work", default=None)


@contextmanager
def agent_work_context(context: AgentWorkContext) -> Iterator[None]:
    token = current_agent_work.set(context)
    try:
        yield
    finally:
        current_agent_work.reset(token)
