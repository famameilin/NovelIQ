"案例写入上下文只校验承诺，不关联业务结果"

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import Field, create_model


def bind_caseid(tool: Any, prepare: Callable[[Any], None] | None = None) -> Any:
    "写入前核验案例承诺，工具结果保持业务原形"
    tool.args_schema = create_model(
        f"{tool.name}CaseArgs",
        __base__=tool.args_schema,
        caseid=(Any, Field(default=None, description="本次办理案例的真实 ID；案例写入前核验承诺")),
    )
    original_func, original_coroutine = tool.func, tool.coroutine

    def invoke(*, caseid: Any = None, **kwargs: Any) -> Any:
        if prepare is not None:
            prepare(caseid)
        return original_func(**kwargs)

    async def ainvoke(*, caseid: Any = None, **kwargs: Any) -> Any:
        if prepare is not None:
            prepare(caseid)
        return await original_coroutine(**kwargs)

    if original_func is not None:
        tool.func = invoke
    if original_coroutine is not None:
        tool.coroutine = ainvoke
    return tool
