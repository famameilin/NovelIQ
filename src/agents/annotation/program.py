"""把当前程序运行时的实际工具目录装配成 execute_code"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool

from src.agents.annotation.catalog import call_api_text, tool_call_entries
from src.agents.annotation.program_contract import PROGRAM_TOOL_NAME

if TYPE_CHECKING:
    from src.agents.annotation.program_runtime import RestrictedProgramRuntime


def build_program_tool(
    runtime: RestrictedProgramRuntime,
    *,
    extra_api: str = "",
    tool_descriptions: dict[str, str] | None = None,
    call_entries: list[tuple[str, list[tuple[str, str]], str]] | None = None,
) -> Any:
    """用于构造唯一对外的 execute_code 工具（args_schema 只有 code）

    extra_api：块面/章面把各自的构造器目录并进同一份 description——模型可见面
    始终是"一条工具 + 一份 API 目录"。
    tool_descriptions：本面的工具说明覆盖（见 tool_call_entries）。
    call_entries：本面的构造器条目（constructor_call_entries 的产物），与工具条目
    在目录里同形，一次渲染成一份目录。
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
