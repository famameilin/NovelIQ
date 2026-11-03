"""程序体积、操作数、执行期限与受控故障"""

from __future__ import annotations

import collections
import datetime
import json
import math
import unicodedata
from typing import Any

from src.agents.errors import AgentRetryableError

PROGRAM_MAX_CODE_CHARS = 100000
PROGRAM_MAX_OPS = 300
PROGRAM_DEADLINE_S = 600.0
# print 单条回显上限：超出只显示前若干字符并标注原文字符数
PROGRAM_PRINT_MAX_CHARS = 2000
# range 与序列重复的单项上限：求值前先算长度，避免一次分配打满进程
PROGRAM_MAX_RANGE_ITEMS = 1000000
PROGRAM_MAX_REPEAT_ITEMS = 1000000
# while 迭代上限：期限只在检查点生效，单次循环必须有独立硬限
PROGRAM_MAX_WHILE_ITERATIONS = 10000

# 程序面可导入的模块：静态登记，模型写 import 只绑定这些对象，不触发导入机制
PROGRAM_MODULES: dict[str, Any] = {
    "json": json,
    "unicodedata": unicodedata,
    "math": math,
    "collections": collections,
    "datetime": datetime,
}

# 每个模块只放行可返回内置值的可调用项；裸属性读一律拒绝
PROGRAM_MODULE_ATTRIBUTES: dict[str, frozenset[str]] = {
    "json": frozenset({"dumps", "loads"}),
    "unicodedata": frozenset({"normalize", "name", "category", "east_asian_width", "combining"}),
    "math": frozenset(
        {
            "ceil",
            "floor",
            "fabs",
            "sqrt",
            "log",
            "log10",
            "log2",
            "exp",
            "pow",
            "fsum",
            "gcd",
            "isclose",
            "trunc",
            "isnan",
            "isinf",
            "isfinite",
            "hypot",
            "prod",
            "dist",
        }
    ),
    "collections": frozenset({"Counter", "OrderedDict", "defaultdict"}),
    "datetime": frozenset({"date", "datetime", "timedelta"}),
}

# 未进入执行就失败的错误码（程序一个字都没跑）：语义上是"拒绝本次提交"，与
# 执行期中断（已成功的调用保留）分开表达
PRE_RUN_FAULT_CODES = frozenset({"empty_program", "program_too_large", "syntax_error"})


class ProgramExecutionTimeout(AgentRetryableError):
    """终止当前 invocation，回执保留已执行调用事实"""

    def __init__(self, receipt: str) -> None:
        self.receipt = receipt
        super().__init__(f"程序执行期限耗尽，终止当前 invocation：{receipt}")


class ProgramFault(Exception):
    """用于把程序面内部失败（非法节点/越限/运行错误）收敛成结构化 error"""

    def __init__(self, message: str, *, code: str, line: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.line = line

    def payload(self) -> dict[str, Any]:
        """用于渲染模型可见的 error 结构（type 即错误码，line 供定位）"""
        body: dict[str, Any] = {"type": self.code, "message": str(self)}
        if self.line is not None:
            body["line"] = self.line
        return body




PROGRAM_TOOL_NAME = "execute_code"

_INNER_CALL_INDEX_BASE = 1000

_PROGRAM_NAME_CONSTANTS: dict[str, Any] = {"true": True, "false": False, "null": None, "none": None}

_READ_TOOL_NAMES = frozenset(
    {
        "search_graph",
        "search_events",
        "search_cases",
        "read_event",
        "read_entity",
        "search_text",
        "read_text",
        "read_chapter_text",
    }
)

_READ_ECHO_MAX_ITEMS = 8
