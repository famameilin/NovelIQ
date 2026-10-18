"完整数据操作的连接和事务所有权仅存在于 Storage 内部"

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from src.storage.detached import detached
from src.storage.errors import StorageError, StorageWriteError, translate_errors

T = TypeVar("T")


class OperationRunner:
    "包内执行器；公开合同不能接收回调、连接或事务对象"

    def __init__(self, session_factory=None):
        self._session_factory = session_factory

    def run(self, operation: Callable[..., T], *, read_only: bool = False) -> T:
        "在完整操作结束时提交；失败先回滚再关闭，不让业务操纵事务"
        from src.storage.db import get_session_factory

        with translate_errors():
            factory = self._session_factory or get_session_factory()
            session = factory()
        failure = None
        try:
            with translate_errors():
                if read_only:
                    from sqlalchemy import text
                    from sqlalchemy.orm import Session

                    if isinstance(session, Session) and session.get_bind().dialect.name == "postgresql":
                        session.execute(text("SET TRANSACTION READ ONLY"))
                result = operation(session)
                if not read_only:
                    session.flush()
                result = detached(result)
                if read_only:
                    session.rollback()
                else:
                    session.commit()
                return result
        except BaseException as exc:
            failure = exc
            rollback_error = None
            try:
                with translate_errors():
                    session.rollback()
            except BaseException as rollback_failure:
                rollback_error = rollback_failure
            if not isinstance(exc, Exception):
                raise
            if rollback_error is None and (read_only or not isinstance(exc, (StorageError, OSError, TimeoutError))):
                raise
            failure = StorageWriteError(
                str(exc),
                rollback_failed=rollback_error is not None,
                transport_error=isinstance(exc, (OSError, TimeoutError)),
            )
            raise failure from exc
        finally:
            try:
                with translate_errors():
                    session.close()
            except Exception as close_error:
                if failure is None:
                    raise
                failure.add_note(f"Storage 释放连接时再次失败: {close_error}")
