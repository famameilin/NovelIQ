"公开输入只允许普通数据，禁止把数据库资源或可执行对象带入 Storage"

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine, Result, Row, RowMapping
from sqlalchemy.orm import Query, Session
from sqlalchemy.sql import ClauseElement

from src.storage.detached import detached
from src.storage.records.sentinels import UNSET
from src.storage.records.values import NamedRecord


def plain(value):
    "校验后复制输入，后台操作不引用调用方的可变容器"
    if value is UNSET:
        return value
    if (
        isinstance(value, (Session, Connection, Engine, Row, RowMapping, Result, Query, ClauseElement))
        or inspect(value, raiseerr=False) is not None
    ):
        raise TypeError("Storage 输入必须是普通记录，不能携带 ORM、SQL 或数据库资源")
    if value is None or isinstance(
        value, (str, bool, int, float, bytes, date, datetime, Decimal, UUID, bytearray, memoryview)
    ):
        return detached(value)
    if isinstance(value, NamedRecord):
        return NamedRecord({key: plain(item) for key, item in value.items()})
    if isinstance(value, dict):
        return {plain(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return type(value)(plain(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        return type(value)(**{field.name: plain(getattr(value, field.name)) for field in fields(value) if field.init})
    if isinstance(value, SimpleNamespace):
        return SimpleNamespace(**{key: plain(item) for key, item in vars(value).items()})
    if type(value).__module__.startswith("numpy") and hasattr(value, "tolist"):
        return plain(value.tolist())
    raise TypeError(f"Storage 不接受可执行对象或未声明的输入类型: {type(value).__name__}")


def plain_inputs(cls):
    "给显式声明的公开方法加数据边界校验，不增加动态查询能力"

    def wrap(method):
        @wraps(method)
        def guarded(self, *args, **kwargs):
            return method(self, *(plain(item) for item in args), **{key: plain(item) for key, item in kwargs.items()})

        return guarded

    for name, method in list(vars(cls).items()):
        if name.startswith("_") or not callable(method):
            continue
        setattr(cls, name, wrap(method))
    return cls
