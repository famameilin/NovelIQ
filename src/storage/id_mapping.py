"独立 task 短 ID 与 UUIDv7 运行身份的精确映射"

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.storage.ids import new_id, new_task_id

if TYPE_CHECKING:
    from src.storage.service import Storage


class IDMappingError(Exception):
    "ID映射相关的异常基类"

    pass


class TaskIDNotFoundError(IDMappingError):
    "当task_id找不到对应的run_id时抛出"

    pass


def generate_run_id() -> str:
    "生成完整 run_id（36 位 UUID）"
    return new_id()


def generate_task_id() -> str:
    "生成独立的 8 位 task 短 ID，不截取 UUIDv7 时间前缀"
    return new_task_id()


def run_id_to_task_id(run_id: str, storage: Storage | None = None) -> str:
    "读取正式保存的任务映射，UUIDv7 的前 8 位不能用作任务身份"
    from src.storage.service import get_storage

    run = (storage or get_storage()).runs.get_run(run_id)
    if run is None:
        raise TaskIDNotFoundError(f"No task_id found for run_id: {run_id}")
    return str(run["task_id"])


def task_id_to_run_id(task_id: str, storage: Storage | None = None) -> str:
    "按 task 短 ID 精确读取正式运行，不接受连接或查询表达式"
    if not task_id or len(task_id) != 8:
        raise ValueError(f"Invalid task_id: {task_id}. Expected exactly 8 characters.")

    from src.storage.service import get_storage

    result = (storage or get_storage()).runs.get_run_by_task_id(task_id)
    if result is None:
        raise TaskIDNotFoundError(f"No run_id found for task_id: {task_id}")

    return str(result["run_id"])


def convert_response_run_ids_to_task_ids(data: dict | list | Any) -> dict | list | Any:
    "递归将响应中的 run_id 字段替换为 task_id"
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
