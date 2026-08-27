"""ID 映射：task_id（8 位，外部）与 run_id（36 位 UUID，内部）的互转，task_id = run_id[:8]。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.orm import Session


class IDMappingError(Exception):
    """ID映射相关的异常基类"""

    pass


class TaskIDNotFoundError(IDMappingError):
    """当task_id找不到对应的run_id时抛出"""

    pass


def generate_run_id() -> str:
    """生成完整 run_id（36 位 UUID）。"""
    return str(uuid.uuid4())


def generate_task_id() -> str:
    """生成 task_id（8 位短 UUID，取 UUID 前 8 位）。"""
    return str(uuid.uuid4())[:8]


def run_id_to_task_id(run_id: str) -> str:
    """从 run_id 提取 task_id（前 8 位）。"""
    if not run_id or len(run_id) < 8:
        raise ValueError(f"Invalid run_id: {run_id}. Expected at least 8 characters.")
    return run_id[:8]


def task_id_to_run_id_pattern(task_id: str) -> str:
    """将 task_id 转为 SQL LIKE 模式（追加 %）。"""
    if not task_id or len(task_id) != 8:
        raise ValueError(f"Invalid task_id: {task_id}. Expected exactly 8 characters.")
    return f"{task_id}%"


def task_id_to_run_id(task_id: str, conn: Connection | Session) -> str:
    """按 task_id 查询 analysis_runs 取得对应 run_id（最早一条）。"""
    if not task_id or len(task_id) != 8:
        raise ValueError(f"Invalid task_id: {task_id}. Expected exactly 8 characters.")

    # 延迟导入避免循环依赖
    from sqlalchemy import select

    from src.storage.models.core import AnalysisRun

    pattern = task_id_to_run_id_pattern(task_id)
    stmt = (
        select(AnalysisRun.run_id)
        .where(AnalysisRun.run_id.like(pattern))
        .order_by(AnalysisRun.created_at.asc())
        .limit(1)
    )
    result = conn.execute(stmt).scalar_one_or_none()

    if result is None:
        raise TaskIDNotFoundError(f"No run_id found for task_id: {task_id}")

    return result


def convert_response_run_ids_to_task_ids(data: dict | list | Any) -> dict | list | Any:
    """递归将响应中的 run_id 字段替换为 task_id。"""
    if isinstance(data, dict):
        result: dict = {}
        for key, value in data.items():
            if key == "run_id" and isinstance(value, str) and len(value) == 36:
                # 将run_id键名改为task_id，值转换为8位
                result["task_id"] = run_id_to_task_id(value)
            elif isinstance(value, dict | list):
                # 递归处理嵌套结构
                result[key] = convert_response_run_ids_to_task_ids(value)
            else:
                result[key] = value
        return result
    elif isinstance(data, list):
        return [convert_response_run_ids_to_task_ids(item) for item in data]
    else:
        return data
