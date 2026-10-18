"""案例关联是业务成功后的独立步骤，不改变工具原有的校验与事务"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from pydantic import Field, create_model

current_case_call_id: ContextVar[str] = ContextVar("case_call_id", default="")


def attach_case_link(result: Any, caseid: Any, associate: Callable[..., dict[str, Any]], tool_name: str) -> Any:
    if caseid is None:
        return result
    try:
        body = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError):
        body = {"result": result}
    if not isinstance(body, dict):
        body = {"result": body}
    try:
        link = associate(caseid=caseid, tool_name=tool_name, receipt=body)
    except Exception as exc:
        link = {"status": "warning", "code": "case_association_failed", "caseid": caseid, "message": str(exc)}
    body = {**body, "case_link": link}
    if link["status"] == "warning":
        body["warnings"] = [*body.get("warnings", []), link]
    return json.dumps(body, ensure_ascii=False)


def bind_caseid(
    tool: Any,
    associate: Callable[..., dict[str, Any]],
    prepare: Callable[[Any], None] | None = None,
) -> Any:
    """caseid 接受任意输入，错误只能在关联阶段变成 warning；prepare 先按 caseid 绑定来源"""
    tool.args_schema = create_model(
        f"{tool.name}CaseArgs",
        __base__=tool.args_schema,
        caseid=(Any, Field(default=None, description="显式关联所办案例的真实 ID；写入必填")),
    )
    original_func, original_coroutine = tool.func, tool.coroutine

    def invoke(*, caseid: Any = None, **kwargs: Any) -> Any:
        if prepare is not None:
            prepare(caseid)
        return attach_case_link(original_func(**kwargs), caseid, associate, tool.name)

    async def ainvoke(*, caseid: Any = None, **kwargs: Any) -> Any:
        if prepare is not None:
            prepare(caseid)
        return attach_case_link(await original_coroutine(**kwargs), caseid, associate, tool.name)

    if original_func is not None:
        tool.func = invoke
    if original_coroutine is not None:
        tool.coroutine = ainvoke
    return tool
