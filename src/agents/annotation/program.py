"""
程序面（CodeAct）execute_code 工具：受限解释器、目录渲染与投影层
"""

# ruff: noqa: E402 —— 文件末尾的 re-export 导入为有意的延迟导入（大文件拆分聚合面）。

# 创建时间：2026-10-02　创建者：Trae
# 任务：program.py 大文件拆分——检索投影层迁出至 search_projection.py，API 目录渲染 +
# 合同文案迁出至 catalog.py，两个 runtime 迁出至 program_runtime.py；本模块保留限额常量/
# _ProgramFault/build_program_tool/render_list_signature 并对迁出符号 re-export
# （既有导入方零改动）。
# 说明：纯结构搬移，不改任何运行逻辑与签名；program_runtime 仍经 tool_batch._execute_call
# 复用生产单条事务边界。

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

# 2026-09-15 安全边界（护栏是常量不是设置项）：单程序字符数/内层操作数/循环项数/
# AST 求值步数/墙钟各自硬限，越限一律结构化拒绝并可续跑（已成功的调用保留）
_PROGRAM_MAX_CODE_CHARS = 100000
_PROGRAM_MAX_OPS = 300
_PROGRAM_MAX_LOOP_ITEMS = 500
_PROGRAM_MAX_STEPS = 30000
_PROGRAM_DEADLINE_S = 600.0

# 程序面工具名（唯一对外的绑定面）：写者只见这一条工具
PROGRAM_TOOL_NAME = "execute_code"

# 内层 op 的审计 call_index 命名空间：模型面的调用号从 0 起，内层从 1000 起递增，
# 两套编号在同一回合内不重叠（agent_tool_calls 无 (turn_id, call_index) 唯一约束，
# 此约定只为让既有按 call_index 排序的排查口径保持可读）
_INNER_CALL_INDEX_BASE = 1000

# 2026-09-15 常量别名：模型把 JSON 的 true/false/null 写进 Python 程序是常态
# （实验 run codeact-20260914 ch5 第五轮 KeyError: 'true' 白烧一轮），别名表在
# 变量查找之前命中，True/False/None 本身是 Python 常量节点、天然可用
_PROGRAM_NAME_CONSTANTS: dict[str, Any] = {"true": True, "false": False, "null": None, "none": None}

# 未进入执行就失败的错误码（程序一个字都没跑）：语义上是"拒绝本次提交"，与
# 执行期中断（已成功的调用保留）分开表达
_PRE_RUN_FAULT_CODES = frozenset({"empty_program", "program_too_large", "syntax_error", "candidate_index_out_of_range"})

# 2026-09-17 程序面回执回显只读检索结果：程序里的检索调用此前只把 payload 交给程序
# 变量，模型看不到值（实验实测同一句 search_pool 连发 7 次、块会话整轮 burn 在"回查"
# 上）。reads 只装检索类工具，写入类仍只回句柄（成功明文不回显）。
_READ_TOOL_NAMES = frozenset(
    {
        "search_graph",
        "search_events",
        "search_cases",
        "search_text",
        "read_text",
        "read_chapter_text",
    }
)
_READ_ECHO_MAX_CHARS = 1600
_READ_ECHO_MAX_ITEMS = 8


class _ProgramFault(Exception):
    """2026-09-15 用于把程序面内部失败（非法节点/越限/运行错误）收敛成结构化 error"""

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


def render_list_signature(name: str, parameters: list[tuple[str, str]]) -> str:
    """2026-09-16 用于渲染调用签名（参数清单从函数签名或 args_schema 读出，不手抄）

    2026-09-18 参数清单先在调用方算好（构造器读函数、工具读 schema），本函数只做排版：
    构造器与工具在目录里是同一种签名的写法。
    2026-09-20 参数那一截自带类型标签（见 _type_label），本函数只负责拼。
    """
    return f"{name}(" + ", ".join(text for _, text in parameters) + ")"


def build_program_tool(
    runtime: RestrictedProgramRuntime,
    *,
    extra_api: str = "",
    tool_descriptions: dict[str, str] | None = None,
    call_entries: list[tuple[str, list[tuple[str, str]], str]] | None = None,
) -> Any:
    """2026-09-15 用于构造唯一对外的 execute_code 工具（args_schema 只有 code）

    2026-09-16 extra_api：块面/章面把各自的构造器目录并进同一份 description——模型可见面
    始终是"一条工具 + 一份 API 目录"。
    2026-09-18 tool_descriptions：本面的工具说明覆盖（见 tool_call_entries）。
    2026-09-18 call_entries：本面的构造器条目（constructor_call_entries 的产物）——构造器与
    工具在目录里同形，所以这里一次渲染成一份目录，没有"构造器块 + 工具块"的分别。
    """
    description = (
        runtime.contract_text
        + extra_api
        + call_api_text(
            [
                *(call_entries or []),
                *tool_call_entries(runtime.tool_list, descriptions=tool_descriptions),
            ]
        )
    )
    return StructuredTool.from_function(
        coroutine=runtime.execute,
        name=PROGRAM_TOOL_NAME,
        description=description,
    )


from .catalog import (
    SUBAGENT_CONTRACT_TEXT as SUBAGENT_CONTRACT_TEXT,
)
from .catalog import (
    _dedent_catalog_text as _dedent_catalog_text,
)
from .catalog import (
    call_api_text as call_api_text,
)
from .catalog import (
    call_parameters as call_parameters,
)
from .catalog import (
    constructor_call_entries as constructor_call_entries,
)
from .catalog import (
    tool_call_entries as tool_call_entries,
)
from .program_runtime import (
    RestrictedProgramRuntime as RestrictedProgramRuntime,
)
from .search_projection import (  # noqa: E402
    _call_rejection as _call_rejection,
)
from .search_projection import (
    build_program_tools as build_program_tools,
)

__all__ = [
    "PROGRAM_TOOL_NAME",
    "RestrictedProgramRuntime",
    "build_program_tool",
    "build_program_tools",
    "call_api_text",
    "call_parameters",
    "render_list_signature",
    "tool_call_entries",
]
