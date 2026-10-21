"单实例启动时恢复待执行任务并终结遗留任务状态"

from __future__ import annotations

from typing import TYPE_CHECKING

from src.storage import get_storage

if TYPE_CHECKING:
    from src.workflows.service import AnalysisService


def recover_orphaned_runs() -> tuple[int, int]:
    """收口上次进程遗留的运行中任务

    Returns:
        tuple[int, int]: (failed_count, cancelled_count)
    """
    session = get_storage()
    repo = session.runs
    failed_count = repo.mark_running_as_failed()
    cancelled_count = repo.mark_cancelling_as_cancelled()
    return (failed_count, cancelled_count)


async def resume_pending_tasks(service: AnalysisService) -> tuple[int, int]:
    """把 DB 中可恢复的 pending 任务重新接回执行器

    Returns:
        tuple[int, int]: (scheduled_count, cancelled_count)
    """
    return await service.recover_pending_tasks()


async def notify_recovered_runs(runs: list[dict]) -> None:
    """发布启动时实际收口的运行事实，不修补历史消息"""
    from src.event_bus import EVENT_BUS, Message

    for run in runs:
        cancelled = run["status"] == "cancelling"
        await EVENT_BUS.deliver(Message(topic="analysis.notification", source="startup", target="notifications",
            run_id=run["run_id"], payload={"task_id": run["task_id"],
                "type": "task_cancelled" if cancelled else "task_error",
                "data": {"status": "cancelled" if cancelled else "failed",
                         "error": None if cancelled else "上次进程退出，执行未完成"}}))
