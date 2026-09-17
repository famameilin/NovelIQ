"""章节标注写者面的程序执行合同（CodeAct）

2026-09-15 落地：写者对外只暴露 execute_code(code)，程序在受限 AST 解释器里逐条
调用既有工具。内层每条操作复用生产 tool_batch 的单条事务边界与校验规则（成功保留、
单条业务错误只回滚该条、后续独立操作继续、依赖失败返回依赖错误），本模块不复制
任何业务校验，也不放松实体参与者三态、tone 枚举或关系端点校验。

组成：
- RestrictedProgramRuntime：受限 AST 解释器基座（语法边界、硬限、逐 op 记录、压缩
  回执）；"一次调用发生什么"由子类 _dispatch 决定——块面与章面程序面上复用同一份
  解释语义，三面谁也不复制别人的校验；
- ProgramRuntime：章尝试内单例（跨回合复用），持有变量环境、逐 op 记录与压缩回执；
- build_program_tools：程序面工具面（四个检索工具包一层紧凑投影，其余原样）；
- render_program_api：把程序面工具动态渲染成模型可见的 API 目录（不手抄，防漂移）；
- build_program_tool：唯一对外的 execute_code 工具（args_schema 只有 code）。

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
from typing import Any

from langchain_core.tools import StructuredTool

from .errors import AnnotationStageRejection
from .graph import _execute_call
from .tools import AnnotationToolLedger, tool_record_key

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
            "n",
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
            "n",
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
            "tree_id",
            "root_node_id",
            "chapter_id",
            "chapter_order",
            "description",
            "participants",
            "is_foreshadow_setup",
            "foreshadowing_status",
            "payoff_likelihood",
        ),
        default_fields=(
            "tree_id",
            "root_node_id",
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
        fields=("result_kind", "case_number", "type", "created_chapter", "description", "keys", "pending"),
        default_fields=("result_kind", "case_number", "type", "created_chapter", "description", "keys", "pending"),
        default_limit=10,
        max_limit=50,
    ),
}


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


def program_api_text(tools: list[Any]) -> str:
    """2026-09-15 用于把程序面工具渲染成模型可见的 API 目录（工具自身即单一事实源）"""
    blocks: list[str] = []
    for tool in tools:
        name = str(tool.name)
        lines = [f"{name}: {getattr(tool, 'description', '') or ''}", "参数JSON Schema: " + _schema_text(tool)]
        rule = _SEARCH_PROJECTIONS.get(name)
        if rule is not None:
            lines.append(
                f"程序面可选参数: fields=[...]（可选字段：{'、'.join(rule.fields)}；省略时用"
                f"{'、'.join(rule.default_fields)}）; limit=N（1..{rule.max_limit}，默认 {rule.default_limit}）"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _schema_text(tool: Any) -> str:
    """2026-09-15 用于渲染工具参数 schema（无 args_schema 时退化为空对象）

    只剥 title 噪声键，description 与枚举目录原样保留——参数说明（tone/关系类型等
    闭合词表）就在 schema 描述里，是模型自纠的唯一来源。
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
# 2026-09-17 末句由"不必覆盖整章、按阶段分多个增量程序"改为"尽量写完本轮该写的
# 全部内容"：分阶段的措辞被模型当成模板执行，实测每章固定 3-4 个写入回合
# （逐领域一个回合），而 main 时代同一本书每章只花 1 个写入回合。
_PROGRAM_BASE_CONTRACT = (
    "执行 Python 程序调用下列工具。工具只接受具名参数；支持变量赋值、列表/字典/元组、下标、"
    "for 列表循环、if 和 ==/!=/in。无 import、属性访问、函数定义或任何其他 Python API。\n"
    "Python 常量为 True/False/None（也接受 true/false/null），不要写成变量名。"
    "变量在本章后续程序里保留（实体 el、事件键、工具返回的字典都可用变量承接）；工具返回字典。\n"
    "业务失败只回滚该条，后面的调用继续执行；语法/运行错误会停止程序，已成功的调用保留。\n"
    f"单个程序最多 {_PROGRAM_MAX_CODE_CHARS} 字符、{_PROGRAM_MAX_OPS} 条工具调用。\n"
    "回执只回报本次成功条数（applied）、新增句柄引用（refs）、各域进度（progress）与失败清单"
    "（failed，带 op 序号/源码行/record/field/code/expected）；成功记录的明细用检索工具回查。"
    "一次程序尽量写完本轮该写的全部内容：同一个程序里连续调用多个工具、写多条记录都可以，"
    "本回合判定的内容本回合写完；只有后一步必须看到前一步回执时才留到下一轮。"
)
PROGRAM_CONTRACT_TEXT = _PROGRAM_BASE_CONTRACT + "finish_chapter 在本程序全部语句执行完后结算。\n\n"
# 2026-09-16 块代理面：块内没有收尾工具——块会话以"模型不再提交程序"收束，
# 局部标注是内存对象、构造即校验，因此合同句只说明收束方式
BLOCK_CONTRACT_TEXT = (
    _PROGRAM_BASE_CONTRACT + "本块标注完毕时不再提交程序即可收束会话（没有收尾工具）。\n\n"
)


def render_list_signature(name: str, function: Any) -> str:
    """2026-09-16 用于渲染构造器签名（取自函数对象本身，不手抄参数名与默认值）"""
    signature = inspect.signature(function)
    parts: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.default is inspect.Parameter.empty:
            parts.append(parameter.name)
        else:
            parts.append(f"{parameter.name}={parameter.default!r}")
    return f"{name}(" + ", ".join(parts) + ")"


def constructor_api_text(entries: list[tuple[str, Any, str]]) -> str:
    """2026-09-16 用于把程序面构造器渲染成模型可见的 API 目录

    entries = (显示名, 可调用, 一句话说明) 列表；签名由 render_list_signature 从
    函数对象读取，说明写在这里——构造器是块面/章面的新增面，不挂在 langchain 工具上，
    这条渲染路径就是它唯一的可见面，签名漂移在渲染层就暴露。
    """
    blocks: list[str] = []
    for name, function, summary in entries:
        blocks.append(f"{render_list_signature(name, function)}\n{summary}")
    return "\n\n".join(blocks)


def build_program_tool(runtime: RestrictedProgramRuntime, *, extra_api: str = "") -> Any:
    """2026-09-15 用于构造唯一对外的 execute_code 工具（args_schema 只有 code）

    2026-09-16 extra_api：块面/章面把各自的构造器目录（constructor_api_text）
    并进同一份 description——模型可见面始终是"一条工具 + 一份 API 目录"。
    """
    description = runtime.contract_text + extra_api + program_api_text(runtime.tool_list)
    return StructuredTool.from_function(
        coroutine=runtime.execute,
        name=PROGRAM_TOOL_NAME,
        description=description,
    )


class RestrictedProgramRuntime:
    """2026-09-16 受限 AST 解释器基座：写者面、块面与章面共用同一份"程序怎么跑"

    分工：本基类只管解释器语义（节点白名单、变量环境、步数/墙钟/条数硬限、逐 op
    记录与压缩回执）；"一次调用发生什么"由子类实现 _dispatch。写者面把它交给生产
    单条事务边界（ProgramRuntime，见下），块面与章面各自交给自己的构造器与编译路径。
    这样三面共用同一份语法边界与回执口径，谁也不复制业务校验。
    """

    # 模型可见的合同文案（块面无收尾工具，合同句不同）
    contract_text: str = PROGRAM_CONTRACT_TEXT

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
        self.env: dict[str, Any] = {}
        # 章内逐 op 记录（审计与统计口径：program_id/op_index/source_line/tool_name/
        # status/record/error_code/direct_fallback）
        self.ops: list[dict[str, Any]] = []
        # 章内累积句柄引用（el→n、事件 el→node_id/tree_id、案例→case_number）
        self.refs: dict[str, Any] = {}
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
        收尾类意图由子类在 _after_program 里结算（写者面即 finish_chapter）。
        """
        self._program_seq += 1
        self._program_id = f"p{self._program_seq}"
        self._ops_in_program = 0
        self._steps = 0
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
        # 模型按回执里的 error/failed 补完失败的尾部后重新提交 finish_chapter() 即可
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
        raise _ProgramFault(
            f"未开放函数：{name}（只能用下方 API 目录里的工具）",
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
        """用于组装压缩回执（成功明文不回显，只给句柄/进度/失败清单）"""
        body: dict[str, Any] = {
            "status": status,
            "applied": applied,
            "refs": dict(self.refs),
            "progress": self._progress(),
        }
        if failed:
            body["failed"] = [_failed_view(op) for op in failed]
        if error is not None:
            body["error"] = error
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
                f"未开放函数：{name}（只能用下方 API 目录里的工具）",
                code="unknown_tool",
                line=line,
            )
        if node.args or any(keyword.arg is None for keyword in node.keywords):
            raise _ProgramFault(
                "工具只接受具名参数（如 write_entity(name=\"张三\", ...)），不支持 *args/**kwargs",
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
    """2026-09-15 用于在受限 AST 解释器里执行模型提交的程序并逐条复用生产工具边界

    生命周期：每个章尝试建一次、跨回合复用（变量、句柄引用与逐 op 记录随之保留）；
    程序内不复制业务校验——每条内层操作都走 graph._execute_call，与原生 tool_batch
    共用同一份"快照 → 调用 → 按条回滚 → 审计 → 事件"实现。
    """

    def __init__(
        self,
        tools: list[Any],
        ledger: AnnotationToolLedger,
        *,
        observer: Any = None,
        stream: Any = None,
        compile_only: frozenset[str] = frozenset(),
    ) -> None:
        """用于绑定程序面工具、账本与审计/事件出口

        2026-09-16 compile_only：只作为编译目标、不进模型可见面的工具名（章面收窄
        用它把正式写入工具从 execute_code 的 API 目录里摘掉；_run_op 仍能调用它们）。
        """
        tool_list = build_program_tools(tools)
        execution_tools = {str(tool.name): tool for tool in tool_list}
        visible = [tool for tool in tool_list if str(tool.name) not in compile_only]
        super().__init__(
            visible,
            {str(tool.name): tool for tool in visible},
            observer=observer,
            stream=stream,
            execution_tools=execution_tools,
        )
        self.ledger = ledger
        self._finish_requested = False
        self._finish_line: int | None = None

    def _reset_program_state(self) -> None:
        """用于在一个程序开始时清掉上一次的收尾意图"""
        self._finish_requested = False
        self._finish_line = None

    def _progress(self) -> dict[str, int]:
        """用于回执 progress（与 finish_chapter 回执同源的域计数）"""
        return self.ledger._written_counts()

    async def _after_program(self) -> None:
        """用于在程序末尾结算 finish_chapter 收尾意图（与原生批次同一条判定路径）"""
        if self._finish_requested:
            await self._settle_finish()

    async def _dispatch(self, name: str, args: dict[str, Any], *, line: int | None) -> Any:
        """用于把一次程序内调用交给生产单条事务边界（收尾声明只登记不结算）"""
        if name == "finish_chapter":
            if args:
                raise _ProgramFault("finish_chapter 无参数", code="bad_call", line=line)
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
        self._collect_refs(name, entry.get("receipt"))
        return entry.get("receipt") or {}

    def _collect_refs(self, name: str, receipt: Any) -> None:
        """用于收集本次程序新增/变更的句柄引用（实体 el→n、事件 el→node/tree、案例→编号）"""
        if not isinstance(receipt, dict):
            return
        if name == "write_entity" and receipt.get("el") is not None:
            self.refs[str(receipt["el"])] = {"n": receipt.get("n")}
            return
        if name == "write_event":
            record = str(receipt.get("record") or "")
            raw_content = receipt.get("content")
            content: dict[str, Any] = raw_content if isinstance(raw_content, dict) else {}
            node_id = content.get("node_id")
            if not record or node_id is None:
                return
            key = record[: -len("/root")] if record.endswith("/root") else record
            handle: dict[str, Any] = {"node_id": node_id}
            if content.get("tree_id") is not None:
                handle["tree_id"] = content["tree_id"]
            self.refs[key] = handle
            return
        if name == "push_case" and receipt.get("target_key") is not None:
            self.refs[str(receipt["target_key"])] = {"case_number": receipt.get("case_number")}

    async def _settle_finish(self) -> None:
        """用于在程序末尾结算 finish_chapter 收尾意图（与原生批次同一条判定路径）"""
        op_index = self._ops_in_program + 1
        entry = await _execute_call(
            {"name": "finish_chapter", "args": {}, "id": f"{self._program_id}-finish"},
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
                "record": "finish_chapter",
                "direct_fallback": False,
            },
        )
        self._log_op(
            "finish_chapter",
            op_index=op_index,
            line=self._finish_line,
            status=str(entry.get("status") or "error"),
            receipt=entry.get("receipt"),
        )


__all__ = [
    "BLOCK_CONTRACT_TEXT",
    "PROGRAM_CONTRACT_TEXT",
    "PROGRAM_TOOL_NAME",
    "ProgramRuntime",
    "RestrictedProgramRuntime",
    "build_program_tool",
    "build_program_tools",
    "constructor_api_text",
    "program_api_text",
    "render_list_signature",
]
