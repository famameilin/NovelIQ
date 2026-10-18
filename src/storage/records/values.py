"按名称读取的普通查询结果，不持有数据库资源"

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


class NamedRecord:
    "保存已完成查询的具名值；字段访问不触发查询或隐式保存"

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_values", deepcopy(dict(values)))

    def __getattr__(self, name: str) -> Any:
        try:
            return object.__getattribute__(self, "_values")[name]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, name: str) -> Any:
        if not isinstance(name, str):
            raise TypeError("查询记录必须按字段名访问")
        return self._values[name]

    def keys(self):
        return self._values.keys()

    def items(self):
        return self._values.items()

    def __deepcopy__(self, memo):
        return type(self)(deepcopy(self._values, memo))

    def as_dict(self) -> dict[str, Any]:
        "返回与原记录隔离的普通字典"
        return deepcopy(self._values)

    def __repr__(self) -> str:
        return f"NamedRecord({self._values!r})"
