"""章节标注的 CodeAct 程序面合同（唯一面：章内 subagent）

2026-09-15 落地：模型对外只暴露 execute_code(code)，程序在受限 AST 解释器里逐条
调用既有工具。内层每条操作复用生产单条事务边界与校验规则（成功保留、单条业务错误
只回滚该条、后续独立操作继续），本模块不复制任何业务校验，也不放松实体参与者三态、
tone 枚举或关系端点校验。

组成：
- RestrictedProgramRuntime：受限 AST 解释器基座（语法边界、硬限、逐 op 记录、压缩
  回执）；"一次调用发生什么"由子类 _dispatch 决定——subagent 面（subagent_program）
  在它之上做八类构造器的写入生效；
- build_program_tools：程序面工具面（四个检索工具包一层紧凑投影，其余原样）；
- build_program_tool：唯一对外的 execute_code 工具（args_schema 只有 code）；
- call_api_text：模型可见目录的唯一渲染路径——构造器与工具同一种形态
  （签名取自函数对象或 args_schema、取值目录取自闭集常量与枚举类 docstring，都不手抄）。

审计：内层每条 op 各写一行 agent_tool_calls（tool_name=内层工具名，args 与回执全量），
call_index 用 _INNER_CALL_INDEX_BASE(1000) + 章内递增序号，与外层 execute_code 的
调用号隔离；program_id/op_index/source_line/record/error_code/direct_fallback 进该行
request_args 的 "_program" 字段，质量统计按 (tool_name, error_code) 分桶。
"""

from __future__ import annotations

import ast
import inspect
import json
import time
from dataclasses import dataclass
from enum import StrEnum
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin

from langchain_core.tools import StructuredTool

from .errors import AnnotationStageRejection
from .graph import _execute_call
from .schema import (
    CLIFFHANGER_DESCRIPTION,
    ENTITY_REF_FIELD_HINT,
    EVENT_ROLE_FIELD_HINT,
    PERSON_ROLE_FIELD_HINT,
    PIVOT_MOMENT_DESCRIPTION,
    Confidence,
    EntityRefType,
    RelationChangeKindArg,
    Tone,
    relation_catalog_text,
)
from .subagent_ir import PARTICIPANT_ROLES, PENDING_KINDS, RUNTIME_ROLES
from .tools import _STAGE_FIELD_EXPECTATIONS, FINISH_TOOL_NAME, tool_record_key

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
_PRE_RUN_FAULT_CODES = frozenset({"empty_program", "program_too_large", "syntax_error"})

# 2026-09-17 程序面回执回显只读检索结果：程序里的检索调用此前只把 payload 交给程序
# 变量，模型看不到值（实验实测同一句 search_pool 连发 7 次、块会话整轮 burn 在"回查"
# 上）。reads 只装检索类工具，写入类仍只回句柄（成功明文不回显）。
_READ_TOOL_NAMES = frozenset({"search_text", "search_graph", "search_event", "search_pool"})
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


@dataclass(frozen=True)
class _SearchProjection:
    """2026-09-15 用于声明程序面检索回执的紧凑投影（省略 fields 时用 default_fields）"""

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
        fields=("content", "truncated", "keyword_score", "semantic_score"),
        default_fields=("content", "truncated"),
        default_limit=3,
        max_limit=20,
    ),
    "search_graph": _SearchProjection(
        collections=("matches", "neighbors", "relations"),
        fields=(
            "id",
            "name",
            "entity_type",
            "tags",
            "state",
            "alias_linked",
            "from_name",
            "to_name",
            "relation_type",
            "is_active",
            "attributes",
        ),
        default_fields=(
            "id",
            "name",
            "entity_type",
            "tags",
            "state",
            "alias_linked",
            "from_name",
            "to_name",
            "relation_type",
            "is_active",
        ),
        default_limit=20,
        max_limit=50,
    ),
    "search_event": _SearchProjection(
        collections=("trees",),
        fields=(
            "id",
            "chapter_order",
            "description",
            "participants",
            "is_foreshadow_setup",
            "foreshadowing_status",
            "payoff_likelihood",
        ),
        default_fields=(
            "id",
            "chapter_order",
            "description",
            "participants",
            "is_foreshadow_setup",
            "foreshadowing_status",
            "payoff_likelihood",
        ),
        default_limit=5,
        max_limit=20,
    ),
    "search_pool": _SearchProjection(
        collections=("results",),
        fields=("result_kind", "id", "type", "created_chapter", "description", "keys", "pending"),
        default_fields=("result_kind", "id", "type", "created_chapter", "description", "keys", "pending"),
        default_limit=10,
        max_limit=50,
    ),
}

# 2026-09-18 检索工具在程序面比工具 schema 多两个参数（fields/limit 由投影层消费，不进
# 工具 schema）：目录里的签名要把它们写出来，否则模型读不到"能按需裁字段"这件事。
# 2026-09-20 两个投影参数不在 schema 里，类型标签按投影规则手写（其余参数一律从注解派生）。
_PROJECTION_PARAMETERS: tuple[str, ...] = ("fields", "limit")
_PROJECTION_PARAMETER_LABELS: dict[str, str] = {"fields": "文本列表", "limit": "整数"}


def _projection_options(
    tool_name: str,
    rule: _SearchProjection,
    *,
    raw_fields: Any,
    raw_limit: Any,
) -> tuple[tuple[str, ...], int]:
    """2026-09-15 用于校验程序面 fields/limit 参数（未声明字段名结构化拒绝并列出可选字段）"""
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
    """2026-09-15 用于按字段白名单投影单条检索结果（非字典项原样返回）"""
    if not isinstance(item, dict):
        return item
    return {key: item[key] for key in fields if key in item}


def _project_payload(tool_name: str, payload: Any, *, fields: tuple[str, ...], limit: int) -> Any:
    """2026-09-15 用于把检索回执压成"明确要求的字段 + 前若干项"（只动程序面）"""
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
    """2026-09-15 用于把逐 op 记录渲染成模型可见的失败清单（按 op 序号与源码行定位）

    message 取结构化拒绝的原文（如端点类型不符时说明实际登记类型），是自纠的关键，
    与原生路径的拒绝回执口径一致；成功记录不进本清单。
    """
    body: dict[str, Any] = {"op": op["op_index"], "line": op["source_line"], "tool": op["tool_name"]}
    for key, source in (
        ("record", "record"),
        ("field", "field"),
        ("code", "error_code"),
        ("expected", "expected"),
        ("message", "message"),
    ):
        value = op.get(source)
        if value is not None:
            body[key] = value
    return body


def _call_rejection(name: str, exc: Exception, *, signature_hint: str) -> dict[str, Any]:
    """2026-09-16 用于把构造器调用失败渲染成记录级拒绝回执（块面与章面共用）

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
    """2026-09-15 用于给程序面检索工具加一层投影（fields/limit 不传给底层工具 schema）"""

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
    """2026-09-15 用于构建程序面工具面（四个检索工具包紧凑投影，其余工具原样）"""
    program_tools: list[Any] = []
    for tool in tools:
        if str(tool.name) in _SEARCH_PROJECTIONS:
            program_tools.append(_ProgramSearchTool(tool))
        else:
            program_tools.append(tool)
    return program_tools


def _dedent_catalog_text(text: str) -> str:
    """2026-09-18 用于把工具说明压成左对齐

    工具 docstring 的续行带 8 空格缩进（源码里为了让文档字符串字面量对齐），渲染进目录后
    是半截缩进段——看起来像加了层级，实际没有任何语义，同一份目录里一半条目缩进、一半不缩进。
    首行不动，其余行按最小的非空缩进量去掉公共前缀（条目内的项目符号缩进保留相对关系）。
    """
    lines = str(text or "").splitlines()
    if len(lines) < 2:
        return str(text or "")
    indented = [line for line in lines[1:] if line.strip()]
    if not indented:
        return lines[0]
    common = min(len(line) - len(line.lstrip()) for line in indented)
    if common == 0:
        return "\n".join(lines)
    return "\n".join([lines[0], *(line[common:] if line.strip() else "" for line in lines[1:])])


# 2026-09-20 具名渲染：目录签名里每个参数带类型标签（`evidence: 整数`）。
# 模型面此前只有参数名——evidence 是段首号、端点/参与者是实体引用都只能靠被拒才知道
# （run 54a72932：目录里那 23 条"参数形状不符"与 160 条 evidence 自由文本都出在这里）。
# 标签一律从注解派生，取不到就留空（宁缺勿猜）；取值域与判据仍在脚注的参数说明里。
_SCALAR_TYPE_LABELS: dict[Any, str] = {
    str: "文本",
    int: "整数",
    bool: "True/False",
    float: "小数",
    dict: "对象",
    list: "列表",
}


def _type_label(annotation: Any, *, metadata: tuple[Any, ...] = ()) -> str:
    """用于把参数注解渲染成目录里的类型标签（取不到就返回空串）

    实体引用按注解标记单独命名；枚举报"枚举（N 个取值）"——签名只报这是闭集，取值与
    判据在同一条参数说明里；容器取内层标签（list[str] → 文本列表）；可空只去掉 None
    分支，省略与否由默认值那一截表达。
    """
    if any(isinstance(item, EntityRefType) for item in metadata):
        return "实体引用"
    if annotation is None or annotation is inspect.Parameter.empty:
        return ""
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        return _type_label(args[0], metadata=tuple(args[1:]))
    if origin in (Union, UnionType):
        branches = [item for item in get_args(annotation) if item is not type(None)]
        return _type_label(branches[0]) if len(branches) == 1 else ""
    if origin is dict:
        return "对象"
    if origin in (list, tuple, set):
        inner = get_args(annotation)
        inner_label = _type_label(inner[0]) if inner else ""
        return f"{inner_label}列表" if inner_label else "对象列表"
    if isinstance(annotation, type):
        if issubclass(annotation, StrEnum):
            return f"枚举（{len(list(annotation))} 个取值）"
        return _SCALAR_TYPE_LABELS.get(annotation, "")
    return ""


def _parameter_head(name: str, label: str) -> str:
    """用于渲染参数名与类型标签（类型取不到时只留参数名，与旧目录逐字一致）"""
    return f"{name}: {label}" if label else name


def _function_parameters(function: Any) -> list[tuple[str, str]]:
    """用于从函数签名取参数清单（(参数名, 调用写法)，默认值照原样渲染），构造器用

    注解按 eval_str 求值：本模块与 subagent_program 都在 `from __future__ import
    annotations` 下，不求值拿到的是字符串，渲染出来就是死文案。
    """
    try:
        signature = inspect.signature(function, eval_str=True)
    except (NameError, TypeError, ValueError):
        signature = inspect.signature(function)
    parameters: list[tuple[str, str]] = []
    for parameter in signature.parameters.values():
        head = _parameter_head(parameter.name, _type_label(parameter.annotation))
        if parameter.default is inspect.Parameter.empty:
            parameters.append((parameter.name, head))
        else:
            parameters.append((parameter.name, f"{head} = {parameter.default!r}"))
    return parameters


def _schema_parameters(tool: Any, *, extra: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """用于从 args_schema 取参数清单（必填与默认值由字段自己声明，不手抄）

    必填排在可选之前（Python 调用面的写法）；extra：schema 之外的调用面参数（检索的
    fields/limit 由程序面投影层消费，不在工具 schema 里），一律按可选渲染。
    """
    fields = getattr(getattr(tool, "args_schema", None), "model_fields", None) or {}
    required: list[tuple[str, str]] = []
    optional: list[tuple[str, str]] = []
    for name, field in fields.items():
        head = _parameter_head(
            str(name),
            _type_label(field.annotation, metadata=tuple(getattr(field, "metadata", ()) or ())),
        )
        if field.is_required():
            required.append((str(name), head))
        else:
            default = "None" if field.default is None else repr(field.default)
            optional.append((str(name), f"{head} = {default}"))
    optional.extend(
        (name, _parameter_head(name, _PROJECTION_PARAMETER_LABELS.get(name, "")) + " = None")
        for name in extra
    )
    return [*required, *optional]


def _projection_parameter_note(name: str, parameter: str) -> str:
    """用于按投影规则渲染检索工具 fields/limit 的取值（单一来源：_SEARCH_PROJECTIONS）"""
    rule = _SEARCH_PROJECTIONS[name]
    if parameter == "fields":
        return f"回执里保留的字段（可选：{'、'.join(rule.fields)}；省略时给 {'、'.join(rule.default_fields)}）"
    return f"最多回几条（1..{rule.max_limit}，默认 {rule.default_limit}）"


def call_parameters(name: str, target: Any) -> list[tuple[str, str]]:
    """用于取一个可调用对象的参数清单（带 args_schema 的读 schema，其余读函数签名）

    构造器是裸函数、工具带 args_schema，两者在目录与拒绝提示里都走本函数——同一个名字
    在两处渲染出同一个签名。
    """
    if getattr(target, "args_schema", None) is not None:
        extra = _PROJECTION_PARAMETERS if name in _SEARCH_PROJECTIONS else ()
        return _schema_parameters(target, extra=extra)
    return _function_parameters(target)


def _parameter_notes(name: str, parameters: list[tuple[str, str]]) -> list[str]:
    """用于逐行渲染参数说明（按 名字.参数 → 参数 查表；同名参数语义不同时点名覆盖）

    说明文本里的换行按续行缩进两格渲染：词表（关系类型 12 值、枚举判据）是多行的，
    不缩进会让下一条参数看起来还在上一条的说明里。
    """
    notes: list[str] = []
    for parameter, _ in parameters:
        text = _CALL_PARAMETER_NOTES.get(f"{name}.{parameter}") or _CALL_PARAMETER_NOTES.get(parameter)
        if text is None and name in _SEARCH_PROJECTIONS and parameter in _PROJECTION_PARAMETERS:
            text = _projection_parameter_note(name, parameter)
        if text:
            head, *rest = str(text).splitlines() or [""]
            notes.append(f"- {parameter}：{head}")
            notes.extend(f"  {line}" for line in rest if line.strip())
    return notes


def call_api_text(entries: list[tuple[str, list[tuple[str, str]], str]]) -> str:
    """用于把一批可调用对象渲染成模型可见的 API 目录（本面唯一的渲染路径）

    entries = [(名字, 参数清单, 说明文本)]：参数清单分别从函数签名（构造器）与 args_schema
    （工具）读出，说明文本来自函数对象的 docstring 或本面的覆盖表——两类条目在这一层没有
    形态差别（2026-09-18 之前构造器渲染成"签名 + 参数说明"、工具渲染成"名字 + 参数JSON
    Schema"，同一份目录两种呈现；schema 的 $defs/anyOf 是给校验器读的，模型面要的只是
    "这个参数是什么、取什么值"，由 _CALL_PARAMETER_NOTES 一行讲清）。
    """
    blocks: list[str] = []
    for name, parameters, summary in entries:
        lines = [render_list_signature(name, parameters), _dedent_catalog_text(summary).strip()]
        notes = _parameter_notes(name, parameters)
        if notes:
            lines.append("参数说明：")
            lines.extend(notes)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def constructor_call_entries(entries: list[tuple[str, Any, str]]) -> list[tuple[str, list[tuple[str, str]], str]]:
    """用于把构造器清单（名字, 可调用, 一句话说明）翻成目录条目"""
    return [(name, _function_parameters(function), summary) for name, function, summary in entries]


def tool_call_entries(
    tools: list[Any], *, descriptions: dict[str, str] | None = None
) -> list[tuple[str, list[tuple[str, str]], str]]:
    """用于把工具对象翻成目录条目（说明可被本面覆盖，参数面只取名字与默认值）

    2026-09-18 descriptions：按工具名覆盖目录里的说明。工具对象的 docstring 是生产工具的
    口径，其中"实体引用一律填 run 级 id 或 el 键"这类句子只对原生面成立——程序面的构造器只认
    本 subagent 登记的 id，照抄会把模型教错（关系/对话构造器会逐条 unknown_reference 拒绝）。
    未覆盖的工具一律不写第二份文案，仍以工具对象为单一事实源。
    """
    entries: list[tuple[str, list[tuple[str, str]], str]] = []
    for tool in tools:
        name = str(tool.name)
        raw = (descriptions or {}).get(name) or getattr(tool, "description", "") or ""
        entries.append((name, call_parameters(name, tool), raw))
    return entries


# 2026-09-17 §12.5① 目录里每个参数的取值与约束（模型可见面，构造器与工具共用一张表）。
# 章面收窄后 write_* 的参数说明退出模型可见面，而闭合关系目录只在 write_relation 的
# relation_type 说明里、tone 目录只在 write_dialogue 的 tone 说明里——块面与章面的
# 构造器于是只能靠被拒来猜（实测：verdict 一次 42 条、entity_type/relation_type 各数十条）。
# 本表按参数名给目录，文本一律从闭集常量与枚举类 docstring 派生（同一个来源，不手抄）；
# 查表顺序是 "名字.参数" → "参数"，同名参数语义不同时点名覆盖。
def _catalog_text(catalog: dict[str, str]) -> str:
    """用于把 {取值: 说明} 词表渲染成一行目录（键取全部，说明随行）"""
    return "；".join(f"{key}={value}" for key, value in catalog.items())


def _enum_parameter_note(enum_cls: Any) -> str:
    """用于按枚举类渲染参数说明（判据取类 docstring、取值取成员，两处都不手抄）

    schema 的 $defs 渲染出来就是这两样东西；模型面不再渲染 JSON，判据与取值在这里
    合成一行。
    """
    doc = inspect.getdoc(enum_cls) or ""
    return f"{doc}\n取值：{'、'.join(str(member.value) for member in enum_cls)}"


_CALL_PARAMETER_NOTES: dict[str, str] = {
    **_STAGE_FIELD_EXPECTATIONS,
    "relation_type": "闭合关系类型（方向与两端实体类型约束如下）：\n" + relation_catalog_text(),
    # 2026-09-18 枚举参数的目录文案从枚举类派生（判据=类 docstring，取值=枚举成员）：
    # confidence / payoff_likelihood 是同一词表的两处名字，判据只有一份。
    # _STAGE_FIELD_EXPECTATIONS 里的短文案仍归拒绝回执用，两边不是同一份文本。
    "tone": _enum_parameter_note(Tone),
    "confidence": _enum_parameter_note(Confidence),
    "payoff_likelihood": _enum_parameter_note(Confidence),
    "strength": _enum_parameter_note(Confidence),
    "change_kind": _enum_parameter_note(RelationChangeKindArg),
    # 2026-09-18 每个构造器的共享口径（实体引用写什么、证据怎么写）只在本面口径块里定义一次
    # （subagent_program 的 _SUBAGENT_REFERENCE_SCOPE_TEXT）：原来 evidence 的长说明在
    # entity/relation/event/label/pending 五处各抄一遍，id/from_id/to_id/speaker_id/keys
    # 又各写一遍同一件事。逐参数只留该参数独有的约束。
    # 2026-09-18 id 口径：实体由模型分配本 subagent 引用键，name 只作展示字段
    "id": "你自定的本 subagent 引用键（如 a1/a2…）；登记在本 subagent 才能被引用",
    "name": "实体展示名：照抄正文里的写法（别名、称号分别登记成不同 id；不许归并、不许推身份）",
    "speaker_id": "判不了归属就省略这个参数",
    "keys": "逐条写下要关联的实体 id；跨章/跨树的对象不在本表",
    "label.paragraph_id": "段首可见号（见引用与证据口径）",
    # 2026-09-18 参与者两项闭集在 items 的元素里，没有任何构造器参数叫 role/narrative_role，
    # 通用键取不到它们（模型无从取值只能被拒），故按 "构造器.参数" 点名；词表从 subagent_ir
    # 的闭集常量派生，不手抄。
    "participants.items": '[{"entity_id": 本 subagent 实体 id, "role": 参与角色, "narrative_role": 叙事功能, '
    '"action": 做了什么, "emotion": -2..2 整数}]；character 的三态（narrative_role/action/emotion）'
    "要么一起给、要么都不给；非 character 只给 entity_id 与 role。"
    f"role 取：{'、'.join(PARTICIPANT_ROLES)}（{EVENT_ROLE_FIELD_HINT}）；"
    f"narrative_role 取：{'、'.join(RUNTIME_ROLES)}（{PERSON_ROLE_FIELD_HINT}）",
    "el": "事件节点的层级键：根=树键（如 t1）、子=树键/节点键（如 t1/e2），由你指定；"
    "同一棵树内的先后=你的调用顺序",
    "isforeshadowing": "true=本章正文把该事件写成伏笔埋设（此时 confidence 必填）；只属于根事件",
    "case_id": "search_pool 回执里的案例 id（先用 search_pool 检索拿到 id 再原样填）",
    "detail": "写清你在正文里看到什么、为什么判不了（人类可读，一段话）",
    # 2026-09-18 两条约束此前只在拒绝文案里教（subagent_program 的 type 只属于子事件 /
    # 子事件必须提供 type、not_dialogue 候选只提交 candidate_index/verdict）：写进目录，
    # 措辞与拒绝同源；不提 speaker_id/speaker 是因为两面参数名不同（写者面是 speaker）。
    "type": '"main"（顺延主因链）或 "secondary"（挂在当时主链尾）；'
    "子事件必填、根事件不填（根由 isroot=True 表达）",
    "verdict": "dialogue=真实对话 / inner_monologue=内心独白 / not_dialogue=误判候选"
    "（题字、描写被引号包裹等；此时只提交 candidate_index 与 verdict，不带说话人与语气）",
    # 2026-09-18 subagent 面这四个参数此前零说明（render_list_signature 不渲染类型注解，
    # notes 也无键），而构造器真的读它们 → 模型只能漏填。只写消费面事实。
    "entity.description": "一句话简介（人类可读）；省略=不提交该字段",
    "entity.attributes": "属性对象（键=属性名，值=属性值）；省略=不提交该字段",
    "metric.pivot_moment": PIVOT_MOMENT_DESCRIPTION,
    "metric.cliffhanger": CLIFFHANGER_DESCRIPTION,
    # 同名参数在不同构造器语义不同：下面几条按 "构造器.参数" 覆盖通用文案，
    # 否则模型会读到写工具面的口径（那是另一条路径的键空间）
    "pending.kind": _catalog_text(PENDING_KINDS),
    "pending.evidence": "case_clue 必填：支撑该线索的段落段首号；其他 kind 可省略",
    "dialogue.evidence": "候选所在段落的段首号；not_dialogue 可省略，真实对话与内心独白必须给",
    "event.description": "一句话事件描述（人类可读）",
    "entity.evidence": "该名字出现段落的段首号，一个号即可（不需要逐次出现都标）",
    # 2026-09-18 检索与案例工具的入参此前只以 JSON Schema 呈现（properties 里没有一句人话），
    # 现在与构造器同一种呈现，逐参数在这里给说明。
    "entities": "要查的实体名；回执里命中与邻居都带 run 级 id",
    "query": "关键词（多关键词用空格/标点分隔，任一命中即返回；% 匹配任意长度、_ 匹配单个字符）",
    "keyword": "关键词（多关键词用空格/标点分隔，任一命中即返回；% 匹配任意长度、_ 匹配单个字符）",
    "case_type": '案例类型（如 "entity_alias"/"伏笔疑点"，或 "all"）；省略即按关键词匹配',
    "reason": "说明为什么这样解决（人类可读，一句话）",
    # 2026-09-18 对话两项：candidate_key 是"订正既有记录"的用法（另一种用法是 candidate_index+verdict），
    # description 覆盖记录里的对话原文，is_inner_monologue 是独白标记
    "candidate_key": "订正既有对话记录时给的记录键（候选表里那条候选的 candidate_key）；判本章候选时省略",
    "dialogue.candidate_key": "订正既有对话记录时给的记录键（候选表里那条候选的 candidate_key）；"
    "判本章候选时省略这个参数",
    "dialogue.description": "订正后的对话内容（覆盖记录里存的原文片段，只在原片段确实记错时用）；不订正就省略",
    "dialogue.is_inner_monologue": "订正后的独白标记：True=内心独白 / False=人物之间说出口的话；不订正就省略",
    "foreshadowing_action": 'reinforce=续接 / payoff=回收（回收把伏笔树收束为 likely_paid_off）；'
    "与 root_event_id 同时给、省略即不挂",
    "root_event_id": "伏笔树的根（埋设事件）的键：本面已写出的树键（如 t1），"
    "或 search_event 树根视图里的 id",
    # 2026-09-19 挂边时顺手更新树根的回收可能性/强度：这两个参数改的是树根，不是本节点，
    # 所以只在挂边时接受（本条覆盖全局的 confidence 词表说明）
    "event.payoff_likelihood": "挂边时把树根的回收可能性更新成本章判断的现值：high/medium/low；"
    "不挂边不给（本章新建伏笔树的回收可能性用 isforeshadowing + confidence）",
    "event.strength": "挂边时把树根的强度更新成本章判断的现值：high/medium/low；不挂边不给",
    # 同名参数冲突点名：push_case 的 keys 是案例匹配关键词（人类可读字符串），
    # 与 pending 的 keys（实体 id）不是一回事；push_case 的 type 与 event 的 type 同理。
    "push_case.description": "案例的人类可读说明，不超过 100 字",
    "push_case.keys": "案例的匹配关键词（写实体名这类人类可读字符串，search_pool 按它命中）；可给多个",
    "push_case.type": '案例类型（任意描述字符串，如 "伏笔疑点"）',
    "push_case.record_id": "这条疑点涉及的产出记录键（写入回执里的 record，实体/关系/事件/对话都行，"
    "必须是本章已经写出来的记录）；没有明确的记录就省略",
    "promise_case.result_id": "交代该案例的产出记录键（写入回执里的 record，必须是本章已经写出来的记录）",
    "search_graph.relation_type": "只看某一类关系时填；取值同 relation 的闭合关系类型表",
    "label.emotion": "整段情绪分值：-2..2 整数（负=负面、正=正面，0=中性）",
    # 2026-09-20 实体引用一族：run 54a72932 里写者面 295 次 write_relation 失败有 135 次
    # 是把实体名称当引用填（参数说明当时只字未提写什么），subagent 面 62 次 relation 失败
    # 同因。四面（两端/说话人/参与者）共用同一句禁令，写法从 schema 的常量取，不另抄。
    "from_entity": f"关系起点{ENTITY_REF_FIELD_HINT}",
    "to_entity": f"关系终点{ENTITY_REF_FIELD_HINT}",
    "from_id": "关系起点：本 subagent 已登记实体的 id（entity(id=…) 登记过的那个键）；不是实体名称",
    "to_id": "关系终点：同上（本 subagent 已登记实体的 id，不是实体名称）",
    "entityid": "参与者实体：本 subagent 已登记实体的 id（不是实体名称）",
    "speaker": f"说话人{ENTITY_REF_FIELD_HINT}",
    # 2026-09-20 段落号一族：evidence 一律是段首可见号（整数），不是引文。
    # run 54a72932：写者面 160 次把引文填进 write_relation.evidence（159 次在新增分支，
    # 那里本来不消费它），整笔调用按 schema 校验失败作废；subagent 面 event() 又漏填必填的
    # evidence 10 次。通用键给"是什么"，各面独有的约束按 "名字.参数" 点名。
    "evidence": "段落开头的段首号（整数，如 12）：变更类的记录用它给出该变化所在的段落；新增/建边不用填",
    "relation.evidence": "变更类（强化/削弱/解除/修正/取代/撤回）填：该变化所在段落的段首号（整数）；建边不用",
    "event.evidence": "该事件所在段落的段首号（整数，必填；正文每段开头的 `N：` 里的 N）",
    # 2026-09-20 写者面 write_event.characters：两个角色闭集此前只写在服务端 schema 里，
    # 目录脚注只说"role 参与角色"（取值零说明），run 54a72932 因此 128 次 write_event 失败
    # 里绝大多数是 role 缺席或把称号/事件角色词填进 role。取值从闭集常量派生，不手抄。
    "characters": '[{"entityid": 参与者实体引用, "role": 参与角色, "narrative_role": 叙事功能, '
    '"action": 做了什么, "emotion": -2..2 整数}, …]；'
    "character 的三态（narrative_role/action/emotion）要么一起给、要么都不给，非 character 只给 entityid 与 role。"
    f"role 取：{'、'.join(PARTICIPANT_ROLES)}（{EVENT_ROLE_FIELD_HINT}）；"
    f"narrative_role 取：{'、'.join(RUNTIME_ROLES)}（{PERSON_ROLE_FIELD_HINT}）",
    # 2026-09-20 案例指向的产出记录键：两处都收"写入回执里的 record"原值，不是路径猜测
    # （run 54a72932：13+13 次案例调用把 event/event/t1、structure/event/t1、event:t1 这类
    # 拼出来的键填进来，全被 unknown_record 拒）。
    "record_id": "写入回执里的 record 原值（本章已写出的记录键，照抄回执不要自己拼）",
    "result_id": "写入回执里的 record 原值（本章已写出的记录键，照抄回执不要自己拼）",
}


def _schema_text(tool: Any) -> str:
    """2026-09-15 用于渲染工具参数 schema 的 JSON 全文（离线对照与排查用）

    2026-09-18 模型面不再渲染 JSON Schema（目录里只留人话参数说明，见 call_api_text），
    本函数退回排查工具：把工具的 $defs/anyOf 原样打印出来对账。
    """
    schema = getattr(tool, "args_schema", None)
    model_json_schema = getattr(schema, "model_json_schema", None)
    if model_json_schema is None:
        return "{}"
    return json.dumps(_strip_titles(model_json_schema()), ensure_ascii=False)


def _strip_titles(value: Any) -> Any:
    """2026-09-15 用于递归剥掉 JSON Schema 里的 title 键（pydantic 自动生成的冗余标注）"""
    if isinstance(value, dict):
        return {key: _strip_titles(item) for key, item in value.items() if key != "title"}
    if isinstance(value, list):
        return [_strip_titles(item) for item in value]
    return value


# 2026-09-15 程序合同文案：语法边界 + 回执口径 + 变量持久（与工具面同轮下发）
# 2026-09-17 批量纪律句的措辞几经反复：分阶段（"按阶段分多个增量程序"）被模型当成模板执行，
# 实测每章固定 3-4 个写入回合（逐领域一个回合），而 main 时代同一本书每章只花 1 个写入回合。
# 2026-09-18 重写成逐条：原来的单段散文把五个主题（语法/常量/失败/上限/回执）串成一句，
# 批量纪律与收尾纪律又夹在回执字段定义中间，模型要在几百字里切主题。分三块——运行规则、
# 回执字段是机制，引用与证据口径是取值面，工作方式是行为合同：**四块都在这一份说明里**
# （模型在这个面只有 execute_code 与 finish 两件工具，说明就是它读得到的全部合同）。
SUBAGENT_CONTRACT_TEXT = (
    "执行一段 Python 程序，程序里的每次调用立即生效：成功就写入正式记录，失败只作废那一条。\n"
    "运行规则：\n"
    "- 语法：变量赋值、列表/字典/元组、下标、for 列表循环、if 与 ==/!=/in；调用只写具名参数；"
    "没有 import、属性访问、函数定义或其他 Python API。常量写 True/False/None（也接受 true/false/null）。\n"
    "- 变量：程序里赋的变量在本章后续程序里保留；构造器与检索的返回值都能用变量承接。\n"
    "- 失败：业务失败只作废该条调用、后面的语句继续执行；语法或运行错误停止本程序、已成功的调用保留。\n"
    f"- 上限：单个程序最多 {_PROGRAM_MAX_CODE_CHARS} 字符、{_PROGRAM_MAX_OPS} 条调用。\n"
    "回执字段：\n"
    "- status：本次程序的整体结果。\n"
    "- applied：本程序成功的调用条数。\n"
    "- failed：失败清单，每条给 op（第几条调用）、line（源码行）、record、field、code、expected。\n"
    "- reads：本程序内检索到的数据，原样回显。\n"
    "- progress：本 subagent 各类已写入记录的条数。\n"
    "- error：程序在写完之前就失败时的错误详情（type 与 message）。\n"
    "- 单次调用：写类回 status=written 带 record 与 ref（ref 是该次的产出，如 push_case 的案例编号）；"
    "读类直接给数据；被拒一律 status=rejected 带 record/field/code/expected/message。\n"
    "写类调用的成功明文不回显：已写入的进度看 progress、检索结果看 reads。\n"
    "工作方式：\n"
    "- 一次程序把本章该判的内容写完：同一段程序里连续调用多个构造器、写多条记录都可以。\n"
    "- 判不了的用 pending 登记，不要硬套：正文只说见面、对峙这类没有闭合关系可表达的，宁缺勿滥。\n"
    "- reads 已经是本程序检索到的数据，不要为看同一份结果反复检索；failed 里那一条按 expected 当场改。\n"
    "- 产出写完时调用 finish 收尾：收尾不减损已写入的记录，回执点名还缺什么，缺的当场补。\n\n"
)

# 2026-09-19 写者面（agent 路径）程序合同：与 subagent 面共用同一基座语义，差异在
# 调用对象（正式工具直接调用而非构造器）与收尾（finish 是章级收尾、程序末尾结算）
PROGRAM_CONTRACT_TEXT = (
    "执行一段 Python 程序，程序里的每次调用立即生效：成功就写入正式记录，失败只作废那一条。\n"
    "运行规则：\n"
    "- 语法：变量赋值、列表/字典/元组、下标、for 列表循环、if 与 ==/!=/in；调用只写具名参数；"
    "没有 import、属性访问、函数定义或其他 Python API。常量写 True/False/None（也接受 true/false/null）。\n"
    "- 变量：程序里赋的变量在本章后续程序里保留；调用的返回值都能用变量承接。\n"
    "- 失败：业务失败只作废该条调用、后面的语句继续执行；语法或运行错误停止本程序、已成功的调用保留。\n"
    f"- 上限：单个程序最多 {_PROGRAM_MAX_CODE_CHARS} 字符、{_PROGRAM_MAX_OPS} 条调用。\n"
    "回执字段：\n"
    "- status：本次程序的整体结果。\n"
    "- applied：本程序成功的调用条数。\n"
    "- failed：失败清单，每条给 op（第几条调用）、line（源码行）、record、field、code、expected。\n"
    "- reads：本程序内检索到的数据，原样回显。\n"
    "- progress：本章各类已写入记录的条数。\n"
    "- error：程序在写完之前就失败时的错误详情（type 与 message）。\n"
    "- 单次调用：写类回 status=written 带 record；读类直接给数据；"
    "被拒一律 status=rejected 带 record/field/code/expected/message。\n"
    "写类调用的成功明文不回显：已写入的进度看 progress、检索结果看 reads。\n"
    "工作方式：\n"
    "- 一次程序把本章该判的内容写完：同一段程序里连续写多条记录都可以。\n"
    "- 全部领域通常 1-2 个程序完成：判完即写、一批收章，不要逐领域各发一个程序。\n"
    "- reads 已经是本程序检索到的数据，不要为看同一份结果反复检索；failed 里那一条按 expected 当场改。\n"
    "- 产出写完时调用 finish 收尾：finish 在本程序全部语句执行完后结算，"
    "回执点名还缺什么，缺的当场补。\n\n"
)


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
    description = runtime.contract_text + extra_api + call_api_text(
        [
            *(call_entries or []),
            *tool_call_entries(runtime.tool_list, descriptions=tool_descriptions),
        ]
    )
    return StructuredTool.from_function(
        coroutine=runtime.execute,
        name=PROGRAM_TOOL_NAME,
        description=description,
    )


class RestrictedProgramRuntime:
    """2026-09-16 受限 AST 解释器基座：程序面共用同一份"程序怎么跑"

    分工：本基类只管解释器语义（节点白名单、变量环境、步数/墙钟/条数硬限、逐 op
    记录与压缩回执）；"一次调用发生什么"由子类实现 _dispatch——subagent 面
    （subagent_program.SubagentProgramRuntime）在它之上做构造器的写入生效。
    这样两边共用同一份语法边界与回执口径，谁也不复制业务校验。
    """

    # 模型可见的合同文案：子类必须给自己的那一份（本面只有 subagent 一条路径）
    contract_text: str = ""

    def __init__(
        self,
        tool_list: list[Any],
        namespace: dict[str, Any],
        *,
        observer: Any = None,
        stream: Any = None,
        execution_tools: dict[str, Any] | None = None,
    ) -> None:
        """用于绑定程序面工具面（渲染 API 目录）与分发命名空间（名字 → 可调用）

        2026-09-16 execution_tools：内层正式调用的工具表——章面收窄后模型可见面
        不含那五个正式写入工具，但构造器编译出的调用仍要经它们落地，故两张表分开：
        模型能写什么由 tool_list/namespace 决定，能执行什么由本表决定；省略即同一张。
        """
        self.tool_list = list(tool_list)
        self.tools: dict[str, Any] = dict(namespace)
        self.execution_tools: dict[str, Any] = self.tools if execution_tools is None else dict(execution_tools)
        self.observer = observer
        self.stream = stream
        # 2026-09-17 编译相位标记：代码相位（0 个 agent）的内层调用发生在任何模型回合
        # 之前，没有 turn 行可挂，审计按"非模型调用"处理（产出进编译摘要与日志）
        self._compiling = False
        self.env: dict[str, Any] = {}
        # 章内逐 op 记录（审计与统计口径：program_id/op_index/source_line/tool_name/
        # status/record/error_code/direct_fallback）
        self.ops: list[dict[str, Any]] = []
        # 本程序内检索读结果的回显（每次 execute 重置；见 _READ_TOOL_NAMES）
        self.reads: list[dict[str, Any]] = []
        self._program_seq = 0
        self._call_index_seq = 0
        self._program_id = ""
        self._ops_in_program = 0
        self._steps = 0
        self._deadline = 0.0

    # ------------------------------------------------------------------
    # 程序入口

    async def execute(self, code: str) -> str:
        """执行一段 Python 程序并返回压缩回执（模型面唯一入口）

        程序内已经成功的调用不回滚（程序错误只中断后续语句），失败逐条进 failed；
        收尾类意图由子类在 _after_program 里结算（写者面即 finish）。
        """
        self._program_seq += 1
        self._program_id = f"p{self._program_seq}"
        self._ops_in_program = 0
        self._steps = 0
        self.reads = []
        self._deadline = time.monotonic() + _PROGRAM_DEADLINE_S
        self._reset_program_state()
        error: dict[str, Any] | None = None
        status = "applied"
        try:
            await self._statements(self._parse(code))
        except _ProgramFault as fault:
            error = fault.payload()
            status = "rejected" if fault.code in _PRE_RUN_FAULT_CODES else "runtime_error"
        # 程序被中断时不结算收尾意图：收尾之后的语句没跑完，冻结即不可逆地丢内容；
        # 模型按回执里的 error/failed 补完失败的尾部后重新提交 finish() 即可
        if error is None:
            await self._after_program()
        program_ops = [op for op in self.ops if op["program_id"] == self._program_id]
        applied = sum(1 for op in program_ops if op["status"] == "success")
        failed = [op for op in program_ops if op["status"] != "success"]
        if failed and status == "applied":
            status = "partial"
        return json.dumps(
            self._receipt(status=status, applied=applied, failed=failed, error=error), ensure_ascii=False
        )

    def _reset_program_state(self) -> None:
        """子类钩子：一个程序开始时重置本面独有的状态（默认无状态）"""

    async def _after_program(self) -> None:
        """子类钩子：程序无错跑完后的收尾结算（默认无动作）"""

    async def _dispatch(self, name: str, args: dict[str, Any], *, line: int | None) -> Any:
        """子类钩子：执行一次具名调用（默认拒绝，子类必须覆盖）"""
        # 回执只报事实（哪个名字没开放）：可用名字在 execute_code 的说明里，属提示词面
        raise _ProgramFault(
            f"未开放函数：{name}",
            code="unknown_tool",
            line=line,
        )

    def _progress(self) -> dict[str, int]:
        """子类钩子：回执里的各域进度（默认空）"""
        return {}

    def _parse(self, code: str) -> list[Any]:
        """用于解析程序文本（空程序/超长/语法错误一律结构化拒绝、不进执行）"""
        if not isinstance(code, str) or not code.strip():
            raise _ProgramFault("程序为空：请提交要执行的 Python 程序", code="empty_program")
        if len(code) > _PROGRAM_MAX_CODE_CHARS:
            raise _ProgramFault(
                f"程序超过 {_PROGRAM_MAX_CODE_CHARS} 字符（当前 {len(code)}）",
                code="program_too_large",
            )
        try:
            body = ast.parse(code).body
        except SyntaxError as exc:
            raise _ProgramFault(f"语法错误：{exc.msg}", code="syntax_error", line=exc.lineno) from None
        if not body:
            raise _ProgramFault("程序为空：请提交要执行的 Python 程序", code="empty_program")
        return body

    def _receipt(
        self,
        *,
        status: str,
        applied: int,
        failed: list[dict[str, Any]],
        error: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """用于组装压缩回执（成功明文不回显，只给进度/读结果/失败清单）

        2026-09-17 键序：失败与读结果排在进度之前——失败清单排在后面时模型要先蹚过
        上万字符才看到被拒原因。
        """
        body: dict[str, Any] = {
            "status": status,
            "applied": applied,
            "progress": self._progress(),
        }
        if failed:
            body["failed"] = [_failed_view(op) for op in failed]
        if error is not None:
            body["error"] = error
        if self.reads:
            body["reads"] = list(self.reads)
        return body

    # ------------------------------------------------------------------
    # 语句与表达式求值（白名单：非白名单节点结构化拒绝，不裸抛）

    async def _statements(self, nodes: list[Any]) -> None:
        """用于逐语句执行程序体（赋值/表达式/for/if 四类）"""
        for node in nodes:
            self._guard()
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                self._assign(node.targets[0], await self._value(node.value))
            elif isinstance(node, ast.Expr):
                await self._value(node.value)
            elif isinstance(node, ast.For):
                await self._for_loop(node)
            elif isinstance(node, ast.If):
                body = node.body if bool(await self._value(node.test)) else node.orelse
                await self._statements(body)
            elif isinstance(node, ast.Pass):
                continue
            else:
                raise _ProgramFault(
                    f"未支持的 Python 语句：{type(node).__name__}（只支持赋值、函数调用、for、if）",
                    code="unsupported_statement",
                    line=getattr(node, "lineno", None),
                )

    async def _for_loop(self, node: ast.For) -> None:
        """用于执行有上限的 for（迭代项必须是有界列表/元组，不支持 while）"""
        values = await self._value(node.iter)
        if not isinstance(values, (list, tuple)):
            raise _ProgramFault(
                "for 只能遍历列表或元组（可用变量或字面量）",
                code="unsupported_expression",
                line=node.lineno,
            )
        if len(values) > _PROGRAM_MAX_LOOP_ITEMS:
            raise _ProgramFault(
                f"for 的迭代项超过 {_PROGRAM_MAX_LOOP_ITEMS} 条（当前 {len(values)}）",
                code="loop_too_long",
                line=node.lineno,
            )
        for item in values:
            self._guard()
            self._assign(node.target, item)
            await self._statements(node.body)
        await self._statements(node.orelse)

    def _assign(self, node: Any, value: Any) -> None:
        """用于变量赋值（单名或等长解包；禁止覆盖工具名与 _ 前缀内部名）"""
        if isinstance(node, ast.Name):
            if node.id in self.tools:
                raise _ProgramFault(
                    f"不允许覆盖工具名：{node.id}",
                    code="name_reserved",
                    line=getattr(node, "lineno", None),
                )
            if node.id.startswith("_"):
                raise _ProgramFault(
                    f"不允许使用 _ 前缀变量名：{node.id}",
                    code="name_reserved",
                    line=getattr(node, "lineno", None),
                )
            self.env[node.id] = value
            return
        if isinstance(node, (ast.Tuple, ast.List)):
            items = value if isinstance(value, (list, tuple)) else None
            if items is None or len(items) != len(node.elts):
                raise _ProgramFault(
                    "赋值解包两端长度必须相等",
                    code="bad_assignment",
                    line=getattr(node, "lineno", None),
                )
            for target, item in zip(node.elts, items, strict=True):
                self._assign(target, item)
            return
        raise _ProgramFault(
            "只支持变量赋值与等长解包",
            code="bad_assignment",
            line=getattr(node, "lineno", None),
        )

    async def _value(self, node: Any) -> Any:
        """用于对白名单表达式求值（常量/名称/容器/下标/一元负号/比较/具名工具调用）"""
        self._guard()
        line = getattr(node, "lineno", None)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (str, int, float, bool)) or node.value is None:
                return node.value
            raise _ProgramFault(f"不支持的常量：{type(node.value).__name__}", code="unsupported_expression", line=line)
        if isinstance(node, ast.Name):
            return self._resolve_name(node.id, line=line)
        if isinstance(node, ast.List):
            return [await self._value(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple([await self._value(item) for item in node.elts])
        if isinstance(node, ast.Dict):
            return {
                await self._value(key): await self._value(item)
                for key, item in zip(node.keys, node.values, strict=True)
            }
        if isinstance(node, ast.Subscript):
            value = await self._value(node.value)
            index = await self._value(node.slice)
            try:
                return value[index]
            except (KeyError, IndexError, TypeError) as exc:
                raise _ProgramFault(f"下标不可用：{exc}", code="runtime_error", line=line) from None
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            operand = await self._value(node.operand)
            if not isinstance(operand, (int, float)) or isinstance(operand, bool):
                raise _ProgramFault("一元负号只接受数字", code="runtime_error", line=line)
            return -operand
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            return await self._compare(node, line=line)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return await self._call(node, line=line)
        raise _ProgramFault(
            f"未支持的 Python 表达式：{type(node).__name__}",
            code="unsupported_expression",
            line=line,
        )

    async def _compare(self, node: ast.Compare, *, line: int | None) -> bool:
        """用于比较运算（==/!=/in 三种，不支持 is/链式比较）"""
        left = await self._value(node.left)
        right = await self._value(node.comparators[0])
        operator = node.ops[0]
        if isinstance(operator, ast.Eq):
            return left == right
        if isinstance(operator, ast.NotEq):
            return left != right
        if isinstance(operator, ast.In):
            if not isinstance(right, (list, tuple, dict, str)):
                raise _ProgramFault("in 的右侧需要列表/元组/字典/字符串", code="runtime_error", line=line)
            return left in right
        raise _ProgramFault(
            f"未支持的比较运算：{type(operator).__name__}（只支持 ==/!=/in）",
            code="unsupported_expression",
            line=line,
        )

    def _resolve_name(self, name: str, *, line: int | None) -> Any:
        """用于变量查值：常量别名（true/false/null）先命中，再查变量环境"""
        key = name.strip().casefold()
        if key in _PROGRAM_NAME_CONSTANTS:
            return _PROGRAM_NAME_CONSTANTS[key]
        if name in self.env:
            return self.env[name]
        known = "、".join(sorted(self.env)[:12])
        hint = f"；已定义变量：{known}" if known else ""
        raise _ProgramFault(
            f"未定义的名称：{name}（常量请写 True/False/None，也接受 true/false/null）{hint}",
            code="undefined_name",
            line=line,
        )

    def _call_hint(self, name: str) -> str:
        """用于在调用写法错时把该名字的真实用法回给模型（构造器签名或工具参数名）

        2026-09-17：此前硬写 `write_entity(name="张三", ...)`，而在章面上写工具已退出
        可见面——拒绝文案会给模型点一个它看不到的工具名（§12.5①）。
        2026-09-18 参数名与目录同源（call_parameters）：拒绝里给的签名与模型读到的签名
        逐字一致，不再各自算一遍。
        """
        try:
            return render_list_signature(name, call_parameters(name, self.tools.get(name)))
        except (TypeError, ValueError):
            return f"{name}(...)"

    async def _call(self, node: ast.Call, *, line: int | None) -> Any:
        """用于执行一次具名调用（名字必须属于本面命名空间，参数只接受具名形式）"""
        function = node.func
        if not isinstance(function, ast.Name):
            raise _ProgramFault(
                "只支持直接调用工具函数（不支持属性访问或嵌套调用）",
                code="unsupported_expression",
                line=line,
            )
        name = function.id
        if name not in self.tools:
            raise _ProgramFault(
                f"未开放函数：{name}",
                code="unknown_tool",
                line=line,
            )
        if node.args or any(keyword.arg is None for keyword in node.keywords):
            raise _ProgramFault(
                f"工具只接受具名参数，不支持 *args/**kwargs；{name} 的正确写法：{self._call_hint(name)}",
                code="bad_call",
                line=line,
            )
        args = {str(keyword.arg): await self._value(keyword.value) for keyword in node.keywords}
        return await self._dispatch(name, args, line=line)

    def _next_op_index(self, *, line: int | None) -> int:
        """用于分配程序内 op 序号并强制单程序操作条数硬限（越限可续跑）"""
        if self._ops_in_program >= _PROGRAM_MAX_OPS:
            raise _ProgramFault(
                f"单个程序的内层操作超过 {_PROGRAM_MAX_OPS} 条",
                code="too_many_ops",
                line=line,
            )
        self._ops_in_program += 1
        return self._ops_in_program

    def _next_call_index(self) -> int:
        """用于分配内层 op 的审计 call_index（_INNER_CALL_INDEX_BASE + 章内递增序号）"""
        index = _INNER_CALL_INDEX_BASE + self._call_index_seq
        self._call_index_seq += 1
        return index

    def _log_op(
        self,
        name: str,
        *,
        op_index: int,
        line: int | None,
        status: str,
        receipt: Any,
        call_args: dict[str, Any] | None = None,
        error: str | None = None,
        direct_fallback: bool = False,
    ) -> None:
        """用于登记逐 op 记录（审计口径 + 模型可见失败清单所需的拒绝定位字段）"""
        body: dict[str, Any] = receipt if isinstance(receipt, dict) else {}
        self.ops.append(
            {
                "program_id": self._program_id,
                "op_index": op_index,
                "source_line": line,
                "tool_name": name,
                "status": status,
                "record": body.get("record") or tool_record_key(name, dict(call_args or {})),
                "error_code": body.get("code"),
                "field": body.get("field"),
                "expected": body.get("expected"),
                "message": body.get("message") or body.get("error") or error,
                "direct_fallback": direct_fallback,
            }
        )
        if status == "success" and name in _READ_TOOL_NAMES:
            self._note_read(name, op_index=op_index, line=line, receipt=receipt)

    def _note_read(self, name: str, *, op_index: int, line: int | None, receipt: Any) -> None:
        """用于把一次成功的检索读结果挂进回执 reads（超长截断、只留最近若干条）

        程序里的检索此前只把 payload 交给程序变量，模型看不到值——同一句检索连发多轮、
        整轮推理烧在"回查"上。这里把 payload 原样回显（投影已在 _ProgramSearchTool 做过），
        按条数与字符数双上限截断。
        """
        try:
            text = receipt if isinstance(receipt, str) else json.dumps(receipt, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(receipt)
        item: dict[str, Any] = {"op": op_index, "tool": name}
        if line is not None:
            item["line"] = line
        if len(text) > _READ_ECHO_MAX_CHARS:
            item["result"] = text[:_READ_ECHO_MAX_CHARS]
            item["truncated_chars"] = len(text)
        else:
            item["result"] = text
        self.reads.append(item)
        if len(self.reads) > _READ_ECHO_MAX_ITEMS:
            dropped = len(self.reads) - _READ_ECHO_MAX_ITEMS
            self.reads = self.reads[-_READ_ECHO_MAX_ITEMS:]
            self.reads.insert(0, {"note": f"更早的 {dropped} 条读结果已省略（要重看就再检索一次）"})

    @property
    def audit_observer(self) -> Any:
        """用于取本次内层调用该挂的审计记录器（编译相位没有 turn 行，一律为 None）"""
        return None if self._compiling else self.observer

    def _guard(self) -> None:
        """用于在每条语句/表达式前检查步数与墙钟硬限"""
        self._steps += 1
        if self._steps > _PROGRAM_MAX_STEPS:
            raise _ProgramFault(
                f"单次程序执行步数超过 {_PROGRAM_MAX_STEPS}（疑似循环过大）",
                code="too_many_steps",
            )
        if time.monotonic() > self._deadline:
            raise _ProgramFault(
                f"单次程序执行超过 {int(_PROGRAM_DEADLINE_S)} 秒硬限",
                code="deadline_exceeded",
            )


class ProgramRuntime(RestrictedProgramRuntime):
    """2026-09-15 写者面程序运行时：受限解释器里逐条复用生产单条事务边界

    2026-09-19 随 agent 路径恢复：单块章的模型可见面=[execute_code, finish]，程序内直接
    调用正式工具（检索+写入+finish）；每条内层调用都走 graph._execute_call，与
    subagent 面共用同一份"快照 → 调用 → 按条回滚 → 审计"实现。
    生命周期：每个章尝试建一次、跨回合复用（变量环境与逐 op 记录随之保留）。
    """

    contract_text = PROGRAM_CONTRACT_TEXT

    def __init__(
        self,
        tools: list[Any],
        ledger: Any,
        *,
        observer: Any = None,
        stream: Any = None,
    ) -> None:
        """用于绑定程序面工具、账本与审计/事件出口"""
        tool_list = build_program_tools(tools)
        super().__init__(
            tool_list,
            {str(tool.name): tool for tool in tool_list},
            observer=observer,
            stream=stream,
        )
        self.ledger = ledger
        self._finish_requested = False
        self._finish_line: int | None = None

    def _reset_program_state(self) -> None:
        """用于在一个程序开始时清掉上一次的收尾意图"""
        self._finish_requested = False
        self._finish_line = None

    def _progress(self) -> dict[str, int]:
        """用于回执 progress（与 finish 回执同源的域计数）"""
        return self.ledger._written_counts()

    async def _after_program(self) -> None:
        """用于在程序末尾结算 finish 收尾意图（与批次收尾同一条判定路径）"""
        if self._finish_requested:
            await self._settle_finish()

    async def _dispatch(self, name: str, args: dict[str, Any], *, line: int | None) -> Any:
        """用于把一次程序内调用交给生产单条事务边界（收尾声明只登记不结算）"""
        if name == FINISH_TOOL_NAME:
            if args:
                raise _ProgramFault(f"{FINISH_TOOL_NAME} 无参数", code="bad_call", line=line)
            self._finish_requested = True
            self._finish_line = line
            return {"status": "pending", "note": "收尾已登记：本程序全部语句执行完后结算"}
        return await self._run_op(name=name, args=args, line=line)

    async def _run_op(self, *, name: str, args: dict[str, Any], line: int | None) -> dict[str, Any]:
        """用于把一次工具调用交给生产单条事务边界执行并登记逐 op 记录"""
        op_index = self._next_op_index(line=line)
        entry = await _execute_call(
            {"name": name, "args": args, "id": f"{self._program_id}-op{op_index}"},
            tool_map=self.execution_tools,
            ledger=self.ledger,
            observer=self.observer,
            stream=self.stream,
            call_index=self._next_call_index(),
            # 2026-09-20 写者面也要登记本章已写出的记录键：案例工具（push_case.record_id /
            # promise_case.result_id）按 ledger.written_record_keys 校验，这条路此前没登记
            # （原生批次与 subagent 面都登记了），于是写者面每次引用自己刚写的记录都被
            # unknown_record 拒（run 54a72932：t2/t3 树根引用两次全废）。
            record_keys=self.ledger.written_record_keys,
            program_meta={
                "program_id": self._program_id,
                "op_index": op_index,
                "source_line": line,
                "record": tool_record_key(name, args),
                "direct_fallback": False,
            },
        )
        raw_call = entry.get("call")
        call_args: dict[str, Any] = dict(raw_call.get("args") or {}) if isinstance(raw_call, dict) else {}
        self._log_op(
            name,
            op_index=op_index,
            line=line,
            status=str(entry.get("status") or "error"),
            receipt=entry.get("receipt"),
            call_args=call_args,
        )
        return entry.get("receipt") or {}

    async def _settle_finish(self) -> None:
        """用于在程序末尾结算 finish 收尾意图（就地结算，不再只登记）"""
        op_index = self._ops_in_program + 1
        entry = await _execute_call(
            {"name": FINISH_TOOL_NAME, "args": {}, "id": f"{self._program_id}-finish"},
            tool_map=self.execution_tools,
            ledger=self.ledger,
            observer=self.observer,
            stream=self.stream,
            call_index=self._next_call_index(),
            settle_finish=True,
            program_meta={
                "program_id": self._program_id,
                "op_index": op_index,
                "source_line": self._finish_line,
                "record": FINISH_TOOL_NAME,
                "direct_fallback": False,
            },
        )
        self._log_op(
            FINISH_TOOL_NAME,
            op_index=op_index,
            line=self._finish_line,
            status=str(entry.get("status") or "error"),
            receipt=entry.get("receipt"),
        )


__all__ = [
    "PROGRAM_CONTRACT_TEXT",
    "SUBAGENT_CONTRACT_TEXT",
    "PROGRAM_TOOL_NAME",
    "ProgramRuntime",
    "RestrictedProgramRuntime",
    "build_program_tool",
    "build_program_tools",
    "call_api_text",
    "call_parameters",
    "constructor_call_entries",
    "render_list_signature",
    "tool_call_entries",
]
