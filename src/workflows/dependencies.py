"""workflows 侧的运行时装配

说明: 队列运行时（TaskManager）与任务读写/编排/应用服务在本层装配，api 只取服务实例，
      不直接认识 work 队列的运行态类型。「run 收口」回调由 api 在装配时登记——缓存归读侧
      所有，执行层只负责上报。
"""

from __future__ import annotations

from collections.abc import Callable

from src.storage import get_storage_factory
from src.work.task_manager import TaskManager
from src.workflows.application import TaskApplicationService
from src.workflows.service import AnalysisService
from src.workflows.tasks import TaskService

_run_completed_callback: Callable[[str], None] | None = None

_task_manager: TaskManager | None = None
_task_service: TaskService | None = None
_analysis_service: AnalysisService | None = None
_task_application_service: TaskApplicationService | None = None


def configure(run_completed_callback: Callable[[str], None] | None = None) -> None:
    """登记 run 收口回调（api 装配时调用；回调属读侧，装配前登记）"""
    global _run_completed_callback
    _run_completed_callback = run_completed_callback


def get_task_manager() -> TaskManager:
    """队列运行态单例（进程内内存态：任务缓存与在飞协程）"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager(run_completed_callback=_run_completed_callback)
        _task_manager.set_db_session_factory(lambda: get_storage_factory()())
    return _task_manager


def get_task_service() -> TaskService:
    """任务与运行读写单例"""
    global _task_service
    if _task_service is None:
        _task_service = TaskService()
    return _task_service


def get_analysis_service() -> AnalysisService:
    """分析编排单例（建任务、跑阶段、恢复、重分析）"""
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = AnalysisService(get_task_service(), get_task_manager())
    return _analysis_service


def get_task_application_service() -> TaskApplicationService:
    """任务应用服务单例（取消/删除/恢复的状态机入口）"""
    global _task_application_service
    if _task_application_service is None:
        _task_application_service = TaskApplicationService(get_task_service(), get_task_manager())
    return _task_application_service
