"""
任务生命周期响应模型

说明: 自 src/api/models/responses.py 拆出任务状态枚举、任务创建/继续/状态查询、
任务列表与批量删除等任务生命周期响应模型，字段与语义保持不变。
"""

from datetime import datetime

from pydantic import BaseModel, Field

from src.storage.task_status import TaskStatus

__all__ = ["TaskStatus"]



class UploadResponse(BaseModel):
    novel_id: str
    filename: str
    status: str = "uploaded"
    message: str = "文件上传成功"


class CreateTaskResponse(BaseModel):
    """
    任务已启动响应（创建/继续/重分析同一形状，message 由端点显式给出）

    说明: 对应 POST /api/novels/{novel_id}/tasks、.../{task_id}/resume、/reanalyze
    """

    novel_id: str
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    message: str


ResumeTaskResponse = CreateTaskResponse
ReanalyzeResponse = CreateTaskResponse


class StatusResponse(BaseModel):
    """
    说明: 添加 sub_stage, current, total, message, llm_outputs 字段，
          使 HTTP 轮询也能返回详细进度信息，与 WebSocket 行为一致
    """

    novel_id: str
    task_id: str
    status: TaskStatus
    progress: float = Field(ge=0, le=100)
    stage: str | None = None
    sub_stage: str | None = None
    current: int | None = None
    total: int | None = None
    message: str | None = None
    llm_outputs: list[str] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class TaskInfoResponse(BaseModel):
    """
    任务信息响应模型
    """

    task_id: str
    novel_id: str
    status: str
    created_at: datetime | None = None


class TaskListResponse(BaseModel):
    novel_id: str
    tasks: list[TaskInfoResponse]


class BatchDeleteNovelsRequest(BaseModel):
    """
    批量删除小说请求模型
    """

    novel_ids: list[str] = Field(..., description="要删除的小说ID列表")


class BatchDeleteTasksRequest(BaseModel):
    """
    批量删除任务请求模型
    """

    task_ids: list[str] = Field(..., description="要删除的任务ID列表")


class BatchDeleteTasksResponse(BaseModel):
    """
    批量删除响应（小说与任务同一形状，failed_ids 元素键随资源不同）

    failed_ids 元素形如 {"novel_id": "xxx", "reason": "错误原因"} 或 {"task_id": ...}
    """

    success: bool
    message: str
    deleted_count: int
    failed_count: int
    deleted_ids: list[str]
    failed_ids: list[dict[str, str]]  # [{"task_id": "xxx", "reason": "错误原因"}]


BatchDeleteNovelsResponse = BatchDeleteTasksResponse
