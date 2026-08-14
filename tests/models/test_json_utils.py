"""
本地模型 JSON 解析工具测试

覆盖 src/models/local/parser/json_utils.py：
- fix_json：think 块剔除、markdown 包裹剥离、混合内容提取、尾随逗号修复
- try_parse_json：标准 json → json5 → streamingjson → fix_json 四级容错链

2026-08-12 创建，补齐该模块 9% 的低覆盖率。
"""

from __future__ import annotations

from src.models.local.parser.json_utils import fix_json, try_parse_json

# ============================================================================
# fix_json
# ============================================================================


def test_fix_json_plain_object() -> None:
    assert fix_json('{"a": 1}') == '{"a": 1}'


def test_fix_json_markdown_wrapped_valid() -> None:
    # 包裹内的 JSON 本身合法时走"混合内容提取"分支
    assert fix_json('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_fix_json_markdown_wrapped_with_trailing_comma() -> None:
    # 包裹内 JSON 非法（尾随逗号）时走"剥离代码块 + 尾逗号修复"分支
    assert fix_json('```json\n{"a": 1,}\n```') == '{"a": 1}'


def test_fix_json_removes_think_block() -> None:
    content = '<think>{"secret": 999}</think>{"a": 2}'
    assert fix_json(content) == '{"a": 2}'


def test_fix_json_extracts_object_from_mixed_text() -> None:
    assert fix_json('解析结果是：{"a": 1} 完成') == '{"a": 1}'


def test_fix_json_removes_trailing_comma_in_array() -> None:
    assert fix_json('{"list": [1, 2,],}') == '{"list": [1, 2]}'


def test_fix_json_no_json_returns_none() -> None:
    assert fix_json("这是一段完全没有 JSON 的普通文本。") is None


def test_fix_json_incomplete_object_returns_none() -> None:
    assert fix_json('{"a": 1') is None


# ============================================================================
# try_parse_json（四级容错链）
# ============================================================================


def test_try_parse_json_standard_dict() -> None:
    assert try_parse_json('{"a": 1}') == {"a": 1}


def test_try_parse_json_non_dict_returns_none() -> None:
    assert try_parse_json("[1, 2, 3]") is None


def test_try_parse_json_trailing_comma_via_json5() -> None:
    assert try_parse_json('{"a": 1,}') == {"a": 1}


def test_try_parse_json_incomplete_via_streamingjson() -> None:
    assert try_parse_json('{"a": 1') == {"a": 1}


def test_try_parse_json_markdown_wrapped_via_fix_json() -> None:
    assert try_parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_try_parse_json_mixed_content_via_fix_json() -> None:
    assert try_parse_json('以下是结果：{"a": 1} 完毕') == {"a": 1}


def test_try_parse_json_think_block_via_fix_json() -> None:
    assert try_parse_json('<think>思考内容不是答案</think>{"a": 1}') == {"a": 1}


def test_try_parse_json_garbage_returns_none() -> None:
    assert try_parse_json("完全无法解析的内容 abcdefg") is None
