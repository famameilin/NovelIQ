"""章内标注单元的稳定身份与必需角色

队列票据由派发侧构造、由标注 Agent 消费，因此与队列机制同包；
票据是内存身份，真实执行由审计记录器带归属登记。
角色值域与章节完成判定由本包的无副作用 policy 维护。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.utils.identity import stable_digest
from src.work.policy import LANES, Role


def required_roles(chapter_text: str, threshold: int) -> tuple[Role, ...]:
    return ("annotation",) if len(chapter_text) <= threshold else LANES


def annotation_work_id(run_id: str, chapter_id: int, role: Role) -> str:
    """章×角色的稳定票据身份：队列去重键与正式产物 record_id 的同一来源"""
    return stable_digest("annotation_agent", run_id, chapter_id, role)


@dataclass(frozen=True)
class WorkReceipt:
    """队列票据：稳定派发单元身份与实际输入；选举运行信息仅在派发时附入 payload"""

    work_id: str
    run_id: str
    work_kind: str
    payload: dict[str, Any]
