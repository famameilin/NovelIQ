"""
结构化输出模式定义

说明: 为项目级结构化输出适配层提供统一 mode 字面量，避免各模块重复拼字符串
"""

from __future__ import annotations

from typing import Literal

StructuredOutputMode = Literal["json_schema", "json_object"]

JSON_SCHEMA_MODE: StructuredOutputMode = "json_schema"
JSON_OBJECT_MODE: StructuredOutputMode = "json_object"

STRUCTURED_OUTPUT_MODES: set[str] = {
    JSON_SCHEMA_MODE,
    JSON_OBJECT_MODE,
}
