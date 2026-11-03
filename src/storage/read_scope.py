"同一次只读请求内复用已完成的读侧投影"

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_read_projections: ContextVar[dict[tuple[Any, ...], Any] | None] = ContextVar("read_projections", default=None)


@contextmanager
def read_projection_scope() -> Iterator[None]:
    "投影仅在当前作用域复用，退出后释放，不跨请求保存"
    token = _read_projections.set({})
    try:
        yield
    finally:
        _read_projections.reset(token)
