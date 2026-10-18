"将数据库返回值递归转换为独立的普通数据记录"

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine, MappingResult, Result, Row, RowMapping, ScalarResult
from sqlalchemy.orm import Session
from sqlalchemy.sql import ClauseElement

from src.storage.records import models as records
from src.storage.records.values import NamedRecord


def detached(value: Any) -> Any:
    "ORM、Row 及其嵌套成员不得离开 Storage 的返回边界"
    if isinstance(value, (Session, Connection, Engine, ClauseElement)):
        raise TypeError("数据库资源或 SQL 表达式不能作为公开数据返回")
    if isinstance(value, (Result, ScalarResult, MappingResult)):
        return detached(value.all())
    state = inspect(value, raiseerr=False)
    if state is not None and hasattr(state, "mapper"):
        if isinstance(value, type):
            raise TypeError("映射类不能作为公开数据返回")
        record_type = getattr(records, type(value).__name__ + "Record")
        return record_type(**{prop.key: detached(getattr(value, prop.key)) for prop in state.mapper.column_attrs})
    if isinstance(value, (Row, RowMapping)):
        mapping = value._mapping if isinstance(value, Row) else value
        return NamedRecord({str(key): detached(item) for key, item in mapping.items()})
    if isinstance(value, NamedRecord):
        return NamedRecord({key: detached(item) for key, item in value.items()})
    if isinstance(value, dict):
        return {key: detached(item) for key, item in value.items()}
    if isinstance(value, list):
        return [detached(item) for item in value]
    if isinstance(value, tuple):
        return tuple(detached(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(detached(item) for item in value)
    if isinstance(value, set):
        return {detached(item) for item in value}
    if is_dataclass(value) and not isinstance(value, type):
        return type(value)(
            **{field.name: detached(getattr(value, field.name)) for field in fields(value) if field.init}
        )
    if isinstance(value, SimpleNamespace):
        return SimpleNamespace(**{key: detached(item) for key, item in vars(value).items()})
    if value is None or isinstance(value, (str, bool, int, float, bytes, date, datetime, Decimal)):
        return deepcopy(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if type(value).__module__.startswith("numpy") and hasattr(value, "tolist"):
        return detached(value.tolist())
    raise TypeError(f"Storage 返回了未声明的记录类型: {type(value).__name__}")
