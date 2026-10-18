"""结构化提交程序的体积护栏与受控故障

程序体积上限与受控拒绝类型由 agent 程序面持有，所有适配器从同一处取用。

护栏是常量不是设置项：越限一律结构化拒绝并可续跑（已成功的调用保留）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

PROGRAM_MAX_CODE_CHARS = 100000
PROGRAM_MAX_OPS = 300
PROGRAM_MAX_LOOP_ITEMS = 500
PROGRAM_MAX_STEPS = 30000
PROGRAM_DEADLINE_S = 600.0

# 未进入执行就失败的错误码（程序一个字都没跑）：语义上是"拒绝本次提交"，与
# 执行期中断（已成功的调用保留）分开表达
PRE_RUN_FAULT_CODES = frozenset({"empty_program", "program_too_large", "syntax_error", "candidate_index_out_of_range"})


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


class ProgramRuntimeSurface(Protocol):
    """结构化提交需要的程序面能力面

    运行时实现（受限解释器）在标注 agent 侧；事件树只声明它要用到的这一小组
    能力，不反向 import agent 运行时。
    """

    ledger: Any
    ops: list[dict[str, Any]]
    observer: Any
    _program_id: str

    async def _execute_program(self, action: Callable[[], Awaitable[None]]) -> str: ...

    async def _dispatch(self, name: str, args: dict[str, Any], *, line: int | None) -> Any: ...

    def _guard(self) -> None: ...

    def _next_op_index(self, *, line: int | None) -> int: ...

    def _next_call_index(self) -> int: ...

    def _log_op(
        self,
        name: str,
        *,
        op_index: int,
        line: int | None,
        status: str,
        receipt: Any,
    ) -> None: ...


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
