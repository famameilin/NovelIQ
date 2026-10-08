"""API 模型包

说明: 结果读侧模型在 responses/ 与同级的 graph/tabs/event_forest/event_timeline；
      本包聚合任务/小说请求与响应 DTO（tasks.py）、设置模型
"""

from src.api.models.tasks import (
    BatchDeleteNovelsRequest,
    BatchDeleteNovelsResponse,
    BatchDeleteTasksRequest,
    BatchDeleteTasksResponse,
    CreateTaskResponse,
    ReanalyzeResponse,
    ResumeTaskResponse,
    StatusResponse,
    TaskInfoResponse,
    TaskListResponse,
    TaskStatus,
    UploadResponse,
)

__all__ = [
    "BatchDeleteNovelsRequest",
    "BatchDeleteNovelsResponse",
    "BatchDeleteTasksRequest",
    "BatchDeleteTasksResponse",
    "CreateTaskResponse",
    "ReanalyzeResponse",
    "ResumeTaskResponse",
    "StatusResponse",
    "TaskInfoResponse",
    "TaskListResponse",
    "TaskStatus",
    "UploadResponse",
]
