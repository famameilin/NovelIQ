"""
程序面检索投影层：检索回执的紧凑投影（fields/limit 不进底层工具 schema）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .errors import AnnotationStageRejection


@dataclass(frozen=True)
class _SearchProjection:
    """用于声明程序面检索回执的紧凑投影（省略 fields 时用 default_fields）"""

    # 主集合在回执里的键；空字符串表示回执本身就是数组（search_text）
    collections: tuple[str, ...]
    fields: tuple[str, ...]
    default_fields: tuple[str, ...]
    default_limit: int
    max_limit: int


# 程序面检索投影：默认只回关键字段与前若干项，模型可用 fields=/limit= 显式要求
_SEARCH_PROJECTIONS: dict[str, _SearchProjection] = {
    "search_text": _SearchProjection(
        collections=("",),
        fields=("content", "truncated", "keyword_score", "semantic_score", "chapter_id", "paragraph_ids", "capability"),
        default_fields=("content", "truncated", "keyword_score", "chapter_id", "paragraph_ids", "capability"),
        default_limit=3,
        max_limit=20,
    ),
}

# 检索工具在程序面比工具 schema 多两个参数（fields/limit 由投影层消费，不进工具
# schema）：目录里的签名要把它们写出来，类型标签按投影规则手写。
_PROJECTION_PARAMETERS: tuple[str, ...] = ("fields", "limit")
_PROJECTION_PARAMETER_LABELS: dict[str, str] = {"fields": "文本列表", "limit": "整数"}


def _projection_options(
    tool_name: str,
    rule: _SearchProjection,
    *,
    raw_fields: Any,
    raw_limit: Any,
) -> tuple[tuple[str, ...], int]:
    """用于校验程序面 fields/limit 参数（未声明字段名结构化拒绝并列出可选字段）"""
    expected = "、".join(rule.fields)
    if raw_fields is None:
        fields = rule.default_fields
    else:
        if not isinstance(raw_fields, (list, tuple)) or not raw_fields:
            raise AnnotationStageRejection(
                f"{tool_name}.fields 需要字段名数组",
                record=f"search/{tool_name}",
                field="fields",
                code="invalid_value",
                expected=f"可选字段：{expected}",
            )
        requested = tuple(str(item) for item in raw_fields)
        unknown = [item for item in requested if item not in rule.fields]
        if unknown:
            raise AnnotationStageRejection(
                f"{tool_name}.fields 含未声明字段：{'、'.join(unknown)}",
                record=f"search/{tool_name}",
                field="fields",
                code="unknown_field",
                expected=f"可选字段：{expected}",
            )
        fields = requested
    if raw_limit is None:
        limit = rule.default_limit
    else:
        if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
            raise AnnotationStageRejection(
                f"{tool_name}.limit 需要整数",
                record=f"search/{tool_name}",
                field="limit",
                code="invalid_value",
                expected=f"1..{rule.max_limit}（默认 {rule.default_limit}）",
            )
        if raw_limit < 1 or raw_limit > rule.max_limit:
            raise AnnotationStageRejection(
                f"{tool_name}.limit 越界：{raw_limit}",
                record=f"search/{tool_name}",
                field="limit",
                code="out_of_range",
                expected=f"1..{rule.max_limit}（默认 {rule.default_limit}）",
            )
        limit = raw_limit
    return fields, limit


def _project_item(item: Any, fields: tuple[str, ...]) -> Any:
    """用于按字段白名单投影单条检索结果（非字典项原样返回）"""
    if not isinstance(item, dict):
        return item
    return {key: item[key] for key in fields if key in item}


def _project_payload(tool_name: str, payload: Any, *, fields: tuple[str, ...], limit: int) -> Any:
    """用于把检索回执压成"明确要求的字段 + 前若干项"（只动程序面）"""
    rule = _SEARCH_PROJECTIONS[tool_name]
    if "" in rule.collections:
        if not isinstance(payload, list):
            return payload
        return [_project_item(item, fields) for item in payload[:limit]]
    if not isinstance(payload, dict):
        return payload
    projected = dict(payload)
    for collection in rule.collections:
        items = projected.get(collection)
        if isinstance(items, list):
            projected[collection] = [_project_item(item, fields) for item in items[:limit]]
    return projected


def _failed_view(op: dict[str, Any]) -> dict[str, Any]:
    """用于把逐 op 记录渲染成模型可见的失败清单（按 op 序号与源码行定位）

    message 取结构化拒绝的原文（如端点类型不符时说明实际登记类型），是自纠的关键，
    与原生路径的拒绝回执口径一致；成功记录不进本清单。
    """
    body: dict[str, Any] = {"op": op["op_index"], "line": op["source_line"], "tool": op["tool_name"]}
    for key, source in (
        ("record", "record"),
        ("field", "field"),
        ("actual", "actual"),
        ("code", "error_code"),
        ("expected", "expected"),
        ("message", "message"),
    ):
        value = op.get(source)
        if value is not None:
            body[key] = value
    return body


def _call_rejection(name: str, exc: Exception, *, signature_hint: str) -> dict[str, Any]:
    """用于把构造器调用失败渲染成记录级拒绝回执（块面与章面共用）

    结构化拒绝（AnnotationStageRejection）带 record/field/code/expected 原样透传；
    其余失败（多为参数名写错）给签名提示，让模型下一轮就能改对。
    """
    if isinstance(exc, AnnotationStageRejection):
        return exc.receipt()
    return {
        "status": "rejected",
        "record": name,
        "code": "invalid_call",
        "expected": signature_hint,
        "message": f"{type(exc).__name__}: {exc}",
    }


class _ProgramSearchTool:
    """用于给程序面检索工具加一层投影（fields/limit 不传给底层工具 schema）"""

    def __init__(self, tool: Any) -> None:
        self._tool = tool
        self.name = str(tool.name)
        self.description = str(getattr(tool, "description", "") or "")
        self.args_schema = tool.args_schema
        self.rule = _SEARCH_PROJECTIONS[self.name]

    async def ainvoke(self, args: dict[str, Any]) -> str:
        """用于消费 fields/limit 后调用底层工具并投影回执（校验失败抛结构化拒绝）"""
        options = dict(args)
        raw_fields = options.pop("fields", None)
        raw_limit = options.pop("limit", None)
        fields, limit = _projection_options(self.name, self.rule, raw_fields=raw_fields, raw_limit=raw_limit)
        result = await self._tool.ainvoke(options)
        text = str(result)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        return json.dumps(_project_payload(self.name, payload, fields=fields, limit=limit), ensure_ascii=False)


def build_program_tools(tools: list[Any]) -> list[Any]:
    """用于构建程序面工具面（四个检索工具包紧凑投影，其余工具原样）"""
    program_tools: list[Any] = []
    for tool in tools:
        if str(tool.name) in _SEARCH_PROJECTIONS:
            program_tools.append(_ProgramSearchTool(tool))
        else:
            program_tools.append(tool)
    return program_tools
