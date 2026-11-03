"""由真实函数签名生成工具参数校验和模型可见 schema"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_type_hints

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

# 常见校验失败类型只报字段事实，不把 pydantic 的英文样板与整段入参回显给模型
_ARGUMENT_TYPE_TEXT: dict[str, str] = {
    "missing": "缺少必填字段",
    "extra_forbidden": "不接受该参数",
    "string_type": "必须是字符串",
    "int_type": "必须是整数",
    "float_type": "必须是数字",
    "bool_type": "必须是布尔值",
    "list_type": "必须是数组",
    "dict_type": "必须是对象",
    "literal_error": "取值不在允许范围",
    "enum": "取值不在允许范围",
    "greater_than_equal": "数值低于下限",
    "less_than_equal": "数值高于上限",
    "int_parsing": "必须是整数",
    "float_parsing": "必须是数字",
    "bool_parsing": "必须是布尔值",
    "json_invalid": "不是合法 JSON",
    "string_too_short": "文本过短",
    "string_too_long": "文本过长",
    "too_short": "条数不足",
    "too_long": "条数超出上限",
}


def describe_argument_error(exc: BaseException) -> str | None:
    """把参数校验失败翻成字段级中文说明；只处理 pydantic 校验失败，其余返回 None"""
    if not isinstance(exc, ValidationError):
        return None
    parts: list[str] = []
    for error in exc.errors()[:5]:
        message = str(error.get("msg") or "")
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        message = _ARGUMENT_TYPE_TEXT.get(str(error.get("type")), message)
        field = ".".join(str(item) for item in error.get("loc", ()) if item != "__root__")
        parts.append(f"{field}：{message}" if field else message)
    return "；".join(parts) or None


@dataclass
class Tool:
    """具备独立参数校验的同步或异步业务入口"""

    name: str
    description: str
    args_schema: type[BaseModel]
    func: Callable[..., Any] | None = None
    coroutine: Callable[..., Any] | None = None

    @classmethod
    def from_function(
        cls,
        func: Callable[..., Any] | None = None,
        *,
        coroutine: Callable[..., Any] | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> Tool:
        """从同一份函数定义生成校验模型与工具说明"""
        target = coroutine or func
        if target is None:
            raise ValueError("工具缺少执行函数")
        hints = get_type_hints(target, include_extras=True)
        fields: dict[str, Any] = {}
        for key, parameter in inspect.signature(target).parameters.items():
            if parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
                raise TypeError(f"工具参数不接受可变签名: {key}")
            default = ... if parameter.default is inspect.Parameter.empty else parameter.default
            fields[key] = (hints.get(key, Any), default)
        tool_name = name or target.__name__
        schema = create_model(
            tool_name,
            __config__=ConfigDict(extra="ignore", arbitrary_types_allowed=True),
            **fields,
        )
        return cls(
            name=tool_name,
            description=description if description is not None else (inspect.getdoc(target) or ""),
            args_schema=schema,
            func=func,
            coroutine=coroutine,
        )

    def _arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        validated = self.args_schema.model_validate(arguments)
        # 仅传实际提供的字段，保留未提供与显式 None 的区别及嵌套领域对象
        return {key: getattr(validated, key) for key in arguments if key in validated.model_fields_set}

    def invoke(self, arguments: dict[str, Any]) -> Any:
        """校验后调用同步工具"""
        values = self._arguments(arguments)
        if self.func is None:
            raise TypeError(f"工具 {self.name} 只有异步入口")
        return self.func(**values)

    async def ainvoke(self, arguments: dict[str, Any]) -> Any:
        """校验后执行工具，保持同步函数的线程调用边界"""
        values = self._arguments(arguments)
        if self.coroutine is not None:
            return await self.coroutine(**values)
        if self.func is None:
            raise TypeError(f"工具 {self.name} 缺少执行入口")
        return await asyncio.to_thread(self.func, **values)

    def provider_schema(self) -> dict[str, Any]:
        """生成与实际校验同源的 OpenAI 函数工具定义"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema.model_json_schema(),
            },
        }


def tool(function: Callable[..., Any]) -> Tool:
    """注册真实函数并保留其完整类型注解"""
    if inspect.iscoroutinefunction(function):
        return Tool.from_function(coroutine=function)
    return Tool.from_function(function)


async def invoke_tool(tool_map: dict[str, Any], call: dict[str, Any]) -> str:
    "校验参数并执行已装配的工具"
    name = str(call.get("name"))
    candidate = tool_map.get(name)
    if candidate is None:
        raise ValueError(f"未知 annotation 工具: {name}")
    return str(await candidate.ainvoke(dict(call.get("args") or {})))
