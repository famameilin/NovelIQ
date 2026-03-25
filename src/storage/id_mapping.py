"""
创建时间: 2026-03-19
创建者: TraeAI
任务: ID系统统一优化 - 创建ID映射工具模块
说明: 提供统一的ID生成和转换工具，建立task_id和run_id之间的映射关系

设计原则:
- task_id (8位): 用于API层、外部交互
- run_id (36位): 用于数据库主键、内部数据关联
- 映射关系: task_id = run_id[:8]

修改记录:
- 2026-03-19 TraeAI 初始创建
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Union, Any

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
    """
    生成完整的run_id (36位UUID)

    Returns:
        36位UUID字符串，格式: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

    Example:
        >>> generate_run_id()
        '0211f894-1a72-4444-a772-2ddc64334cd2'
    """
    return str(uuid.uuid4())


def generate_task_id() -> str:
    """
    生成task_id (8位短UUID)

    Returns:
        8位短UUID字符串

    Example:
        >>> generate_task_id()
        '3a25baca'
    """
    return str(uuid.uuid4())[:8]


def run_id_to_task_id(run_id: str) -> str:
    """
    从run_id提取task_id

    Args:
        run_id: 36位完整UUID

    Returns:
        8位task_id (run_id的前8位)

    Raises:
        ValueError: 如果run_id格式不正确

    Example:
        >>> run_id_to_task_id('0211f894-1a72-4444-a772-2ddc64334cd2')
        '0211f894'
    """
    if not run_id or len(run_id) < 8:
        raise ValueError(f"Invalid run_id: {run_id}. Expected at least 8 characters.")
    return run_id[:8]


def task_id_to_run_id_pattern(task_id: str) -> str:
    """
    将task_id转换为SQL LIKE查询模式

    Args:
        task_id: 8位task_id

    Returns:
        用于SQL LIKE查询的模式字符串

    Raises:
        ValueError: 如果task_id格式不正确

    Example:
        >>> task_id_to_run_id_pattern('3a25baca')
        '3a25baca%'
    """
    if not task_id or len(task_id) != 8:
        raise ValueError(f"Invalid task_id: {task_id}. Expected exactly 8 characters.")
    return f"{task_id}%"


def task_id_to_run_id(task_id: str, conn: "Union[Connection, Session]") -> str:
    """
    将task_id转换为run_id

    通过查询数据库的analysis_runs表，根据task_id找到对应的run_id

    Args:
        task_id: 8位task_id
        conn: 数据库连接 (SQLAlchemy Connection 或 Session)

    Returns:
        对应的36位run_id

    Raises:
        TaskIDNotFoundError: 如果找不到对应的run_id
        ValueError: 如果task_id格式不正确

    Example:
        >>> task_id_to_run_id('3a25baca', conn)
        '3a25baca-1a72-4444-a772-2ddc64334cd2'

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-resume-feature - 断点续传功能修复
    修改内容: 使用 limit(1) 避免多记录时抛出异常
    """
    if not task_id or len(task_id) != 8:
        raise ValueError(f"Invalid task_id: {task_id}. Expected exactly 8 characters.")

    # 延迟导入避免循环依赖
    from sqlalchemy import select
    from src.storage.models.core import AnalysisRun

    pattern = task_id_to_run_id_pattern(task_id)
    stmt = select(AnalysisRun.run_id).where(AnalysisRun.run_id.like(pattern)).order_by(AnalysisRun.created_at.asc()).limit(1)
    result = conn.execute(stmt).scalar_one_or_none()

    if result is None:
        raise TaskIDNotFoundError(f"No run_id found for task_id: {task_id}")

    return result


def convert_response_run_ids_to_task_ids(data: dict | list | Any) -> dict | list | Any:
    """
    递归地将响应数据中的run_id字段转换为task_id

    Args:
        data: 包含run_id字段的字典、列表或任何类型

    Returns:
        转换后的数据，所有run_id字段被替换为task_id

    Example:
        >>> data = {"run_id": "0211f894-1a72-4444-a772-2ddc64334cd2", "name": "test"}
        >>> convert_response_run_ids_to_task_ids(data)
        {"task_id": "0211f894", "name": "test"}
    """
    if isinstance(data, dict):
        result: dict = {}
        for key, value in data.items():
            if key == "run_id" and isinstance(value, str) and len(value) == 36:
                # 将run_id键名改为task_id，值转换为8位
                result["task_id"] = run_id_to_task_id(value)
            elif isinstance(value, (dict, list)):
                # 递归处理嵌套结构
                result[key] = convert_response_run_ids_to_task_ids(value)
            else:
                result[key] = value
        return result
    elif isinstance(data, list):
        return [convert_response_run_ids_to_task_ids(item) for item in data]
    else:
        return data
