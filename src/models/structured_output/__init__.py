"""
项目级结构化输出适配层入口。

说明: 对业务模块暴露稳定 DTO 与 call_structured_output，隐藏 provider 结构化输出差异。
"""

from .adapter import (
    StructuredOutputError,
    StructuredOutputRequest,
    StructuredOutputResult,
    build_response_format,
    call_structured_output,
)
from .modes import StructuredOutputMode

__all__ = [
    "StructuredOutputError",
    "StructuredOutputMode",
    "StructuredOutputRequest",
    "StructuredOutputResult",
    "build_response_format",
    "call_structured_output",
]
