"单实例启动时恢复待执行任务并终结遗留任务状态"

from __future__ import annotations

from typing import TYPE_CHECKING

from src.storage import get_storage

if TYPE_CHECKING:
    from src.work.task_manager import TaskManager
    from src.workflows.service import AnalysisService
    from src.workflows.tasks import TaskService


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


async def resume_pending_tasks(task_service: TaskService, task_manager: TaskManager) -> tuple[int, int]:
    """把 DB 中可恢复的 pending 任务重新接回执行器

    Returns:
        tuple[int, int]: (scheduled_count, cancelled_count)
    """
    from src.workflows.service import AnalysisService

    service: AnalysisService = AnalysisService(task_service, task_manager)
    return await service.recover_pending_tasks()
