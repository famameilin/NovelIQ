"供业务判断的数据库故障类别，不暴露驱动异常属性"

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, cast


class StorageError(RuntimeError):
    "数据操作失败，错误类别本身不证明提交结果"

    def __init__(self, message: str, *, connection_invalidated: bool = False) -> None:
        super().__init__(message)
        self.connection_invalidated = connection_invalidated


class StorageConstraintError(StorageError):
    "仅表述已有可分类约束，是否局部处理由业务决定"

    def __init__(
        self, message: str, *, kind: Literal["foreign_key", "unique", "check"], connection_invalidated: bool = False
    ) -> None:
        super().__init__(message, connection_invalidated=connection_invalidated)
        self.kind = kind


class StorageConnectionError(StorageError):
    "数据库连接故障；不能据此跳过独立保存核验"


@contextmanager
def translate_errors() -> Iterator[None]:
    "只翻译数据库实现异常，业务错误及既有传输重投类别原样传播"
    from sqlalchemy.exc import DBAPIError, SQLAlchemyError

    try:
        yield
    except DBAPIError as exc:
        invalidated = bool(exc.connection_invalidated)
        kind = {"23503": "foreign_key", "23505": "unique", "23514": "check"}.get(str(getattr(exc.orig, "sqlstate", "")))
        if kind is not None:
            raise StorageConstraintError(
                str(exc), kind=cast(Literal["foreign_key", "unique", "check"], kind), connection_invalidated=invalidated
            ) from exc
        if invalidated:
            raise StorageConnectionError(str(exc), connection_invalidated=True) from exc
        raise StorageError(str(exc)) from exc
    except SQLAlchemyError as exc:
        raise StorageError(str(exc)) from exc


class StorageWriteError(StorageError):
    "写入失败不代表未落盘；业务只能独立核验结果，不能接管回滚"

    def __init__(self, message: str, *, rollback_failed: bool, transport_error: bool):
        super().__init__(message)
        self.rollback_failed = rollback_failed
        self.transport_error = transport_error
