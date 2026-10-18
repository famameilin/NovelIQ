"""
程序面运行时：受限 AST 解释器基座与写者面程序运行时
"""

from __future__ import annotations

import ast
import json
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any

from pydantic import TypeAdapter, ValidationError

from src.agents.annotation import program_contract
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.program_contract import ProgramFault
from src.agents.annotation.tools import tool_record_key

# 限额常量经 program 模块属性读取（而非值拷贝）：保持护栏可按属性注入生效。
from . import program_contract as _program
from .catalog import call_parameters, render_list_signature
from .receipt_projection import read_references
from .search_projection import _failed_view

# 重复失败批守卫（两级）：失败条数达到 _REPEAT_FAILED_BATCH_MIN_OPS 且连续两次程序的
# 失败清单逐条相同时注入聚合提示，第三次相同判本程序失败。
_REPEAT_FAILED_BATCH_MIN_OPS = 5
_REPEAT_FAILED_BATCH_FATAL_AT = 3
_DIALOGUE_INDEX_ADAPTER = TypeAdapter(int)

# 放行常见语法：通配符、表达式、基础函数。
# 基础函数只读纯函数，与 range 同属解释器内置：不进工具目录，也不允许被赋值覆盖。
BUILTIN_FUNCTION_NAMES = frozenset(
    {"len", "str", "int", "float", "bool", "min", "max", "abs", "sum", "sorted", "enumerate"}
)


def _unknown_function_message(name: str) -> str:
    """未开放函数的回执点名可用范围；print 另有检索回显替代写法

    预检与运行时两条路径共用本条回执。
    """
    if name == "print":
        return (
            "未开放函数：print；检索结果自动回显在 reads，请删除 print，"
            "直接用变量 = search_events(query=...) 或 search_graph(query=...) 读取"
        )
    builtins = "、".join(sorted(BUILTIN_FUNCTION_NAMES))
    return f"未开放函数：{name}；可调用的函数只有目录列出的工具、基础函数（{builtins}）与 range，没有其他内置函数"


class RestrictedProgramRuntime:
    """受限 AST 解释器基座：程序面共用同一份"程序怎么跑"

    分工：本基类只管解释器语义（节点白名单、变量环境、步数/墙钟/条数硬限、逐 op
    记录与压缩回执）；"一次调用发生什么"由子类实现 _dispatch——正式与连续性工具面
    （ProgramRuntime）在它之上做构造器的写入生效。
    这样两边共用同一份语法边界与回执口径，谁也不复制业务校验。
    """

    # 工具目录从当前信封的实际工具表生成
    contract_text: str = ""
    ledger: AnnotationToolLedger

    def __init__(
        self,
        tool_list: list[Any],
        namespace: dict[str, Any],
        *,
        observer: Any = None,
        stream: Any = None,
        dialogue_total: Callable[[], int] | None = None,
    ) -> None:
        """以同一工具表生成目录并分发调用，不保留构造器编译路径"""
        self.tool_list = list(tool_list)
        self.tools: dict[str, Any] = dict(namespace)
        self.observer = observer
        self.stream = stream
        self.dialogue_total = dialogue_total
        self.env: dict[str, Any] = {}
        # 章内逐 op 记录（审计与统计口径：program_id/op_index/source_line/tool_name/
        # status/record/error_code/direct_fallback）
        self.ops: list[dict[str, Any]] = []
        # 本程序内检索读结果的回显（每次 execute 重置；见 _program._READ_TOOL_NAMES）
        self.reads: list[dict[str, Any]] = []
        self._read_references: list[dict[str, Any]] = []
        self._reads_omitted = 0
        self._program_seq = 0
        self._call_index_seq = 0
        self._program_id = ""
        self._ops_in_program = 0
        self._steps = 0
        self._deadline = 0.0
        # 重复失败批守卫状态（跨程序、章内持续）
        self._last_failed_sig: tuple[tuple[str, str, str, str], ...] | None = None
        self._failed_repeat_count = 0

    # ------------------------------------------------------------------
    # 程序入口

    async def execute(self, code: str) -> str:
        """执行一段 Python 程序并返回压缩回执（模型面唯一入口）

        程序内已经成功的调用不回滚（程序错误只中断后续语句），失败逐条进 failed；
        收尾类意图由子类在 _after_program 里结算（写者面即 finish）。
        """

        async def run() -> None:
            nodes = self._parse(code)
            self._preflight_syntax(nodes)
            await self._preflight_dialogue_indices(nodes)
            await self._statements(nodes)

        return await self._execute_program(run)

    def _dialogue_candidate_total(self) -> int | None:
        """对话候选总数：标注面取账本候选；诊断案例面按会话提供，未提供时不做预检"""
        ledger = getattr(self, "ledger", None)
        if ledger is not None:
            return len(ledger.dialogue_candidates)
        if self.dialogue_total is not None:
            return int(self.dialogue_total())
        return None

    async def _preflight_dialogue_indices(self, nodes: list[ast.stmt]) -> None:
        """在任何写入前检查可确定的候选序号，读写工具返回值仍由真实执行逐项校验

        用临时变量环境复用纯表达式求值，绝不执行工具；只检查可确定的分支与有界循环，
        不确定分支赋出的变量失效，避免拿上一轮或另一分支的旧值误判当前程序
        """
        names = {"write_dialogue", "dialogue"} & self.tools.keys()
        if not any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names
            for statement in nodes
            for node in ast.walk(statement)
        ):
            return
        total = self._dialogue_candidate_total()
        if total is None:
            return
        unknown = object()
        original_env, original_steps = self.env, self._steps
        # 下标赋值会修改容器；预检必须隔离已有变量，不能提前改变真实程序环境
        self.env = deepcopy(original_env)
        invalid: dict[int, int | None] = {}

        def invalidate(node: ast.AST) -> None:
            for target in ast.walk(node):
                if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
                    self.env.pop(target.id, None)
                if isinstance(target, ast.Subscript) and isinstance(target.ctx, ast.Store):
                    root = target.value
                    while isinstance(root, ast.Subscript):
                        root = root.value
                    if isinstance(root, ast.Name):
                        self.env.pop(root.id, None)

        async def assign_known(target: ast.AST, value: Any) -> None:
            try:
                await self._assign(target, value)
            except ProgramFault:
                # 预检只拒绝候选号越界，其它赋值错误留在原执行点报出
                invalidate(target)

        async def pure_value(node: ast.AST) -> Any:
            if any(
                isinstance(child, ast.Call) and not (isinstance(child.func, ast.Name) and child.func.id == "range")
                for child in ast.walk(node)
            ):
                return unknown
            try:
                return await self._value(node)
            except ProgramFault as fault:
                if fault.code in {"too_many_steps", "deadline_exceeded"}:
                    raise
                return unknown

        async def check_calls(expression: ast.AST) -> None:
            for call in ast.walk(expression):
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id not in names:
                    continue
                for keyword in call.keywords:
                    if keyword.arg != "candidate_index":
                        continue
                    value = await pure_value(keyword.value)
                    if value is unknown or isinstance(value, bool):
                        continue
                    if call.func.id == "write_dialogue":
                        try:
                            value = _DIALOGUE_INDEX_ADAPTER.validate_python(value)
                        except ValidationError:
                            continue
                    if isinstance(value, int) and not 1 <= value <= total:
                        invalid.setdefault(value, call.lineno)

        async def visit(statements: list[ast.stmt]) -> None:
            for statement in statements:
                self._guard()
                if isinstance(statement, (ast.Assign, ast.Expr)):
                    await check_calls(statement.value)
                    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                        value = await pure_value(statement.value)
                        if value is unknown:
                            invalidate(statement)
                        else:
                            await assign_known(statement.targets[0], value)
                elif isinstance(statement, ast.If):
                    await check_calls(statement.test)
                    value = await pure_value(statement.test)
                    if value is unknown:
                        invalidate(statement)
                    else:
                        await visit(statement.body if value else statement.orelse)
                elif isinstance(statement, ast.For):
                    await check_calls(statement.iter)
                    values = await pure_value(statement.iter)
                    if not isinstance(values, (list, tuple)) or len(values) > program_contract.PROGRAM_MAX_LOOP_ITEMS:
                        invalidate(statement)
                        continue
                    for value in values:
                        self._guard()
                        await assign_known(statement.target, value)
                        await visit(statement.body)
                    await visit(statement.orelse)

        try:
            await visit(nodes)
        finally:
            self.env, self._steps = original_env, original_steps
        if invalid:
            records = "、".join(f"dialogue/{index}(candidate_index={index})" for index in invalid)
            available = f"1..{total}" if total else "无可用候选"
            raise ProgramFault(
                f"DialogueCandidates total={total}，candidate_index 范围={available}；越界记录：{records}",
                code="candidate_index_out_of_range",
                line=next(iter(invalid.values())),
            )

    async def _execute_program(self, action: Callable[[], Awaitable[None]]) -> str:
        """程序文本与结构化提交共用限额、回执和逐条写入边界"""
        self._program_seq += 1
        self._program_id = f"p{self._program_seq}"
        self._ops_in_program = 0
        self._steps = 0
        self.reads = []
        self._read_references = []
        self._reads_omitted = 0
        self._deadline = time.monotonic() + program_contract.PROGRAM_DEADLINE_S
        self._reset_program_state()
        error: dict[str, Any] | None = None
        status = "applied"
        try:
            await action()
        except ProgramFault as fault:
            error = fault.payload()
            status = "rejected" if fault.code in program_contract.PRE_RUN_FAULT_CODES else "runtime_error"
        # 重复失败批守卫：判败时不结算收尾意图（与运行错误同口径——收尾之后的语句
        # 没跑完，冻结即不可逆地丢内容）。守卫用结算前的 ops 快照判定；回执计数在
        # 收尾结算后取全量（finish 结算也记 op）。
        repeat = 0
        if error is None:
            pre_failed = [op for op in self.ops if op["program_id"] == self._program_id and op["status"] != "success"]
            repeat = self._register_failed_batch(pre_failed)
            if repeat >= _REPEAT_FAILED_BATCH_FATAL_AT:
                error = {
                    "type": "repeat_failed_batch",
                    "message": (
                        f"本程序与上一次完全相同的失败清单已连续出现 {repeat} 次；"
                        "原样重发不会通过，必须先修改 failed 各条的取值再提交"
                    ),
                }
                status = "runtime_error"
            else:
                await self._after_program()
        else:
            self._reset_failed_batch()
        program_ops = [op for op in self.ops if op["program_id"] == self._program_id]
        applied = sum(1 for op in program_ops if op["status"] == "success")
        failed = [op for op in program_ops if op["status"] != "success"]
        if failed and status == "applied":
            status = "partial"
        note = (
            "本程序失败清单与上一次完全相同：原样重发不会通过，先修第一条的原因再提交"
            if repeat == _REPEAT_FAILED_BATCH_FATAL_AT - 1 and error is None
            else None
        )
        return json.dumps(
            self._receipt(status=status, applied=applied, failed=failed, error=error, note=note),
            ensure_ascii=False,
        )

    def _register_failed_batch(self, failed: list[dict[str, Any]]) -> int:
        """用于给重复失败批守卫计数，返回"连续第几次提交同一失败批"（不足阈值重置为 0）

        签名取逐条 (tool_name, error_code, field, message)——盲发批的逐条错误完全一致；
        消息含实体名等动态部分，同一批原样重发即逐字相同。
        """
        if len(failed) < _REPEAT_FAILED_BATCH_MIN_OPS:
            self._reset_failed_batch()
            return 0
        signature = tuple(
            sorted(
                (
                    str(op.get("tool_name") or ""),
                    str(op.get("error_code") or ""),
                    str(op.get("field") or ""),
                    str(op.get("message") or ""),
                )
                for op in failed
            )
        )
        if signature == self._last_failed_sig:
            self._failed_repeat_count += 1
        else:
            self._failed_repeat_count = 1
            self._last_failed_sig = signature
        return self._failed_repeat_count

    def _reset_failed_batch(self) -> None:
        """用于在连续性被打断（程序本身出错、失败批变小）时清空守卫计数"""
        self._last_failed_sig = None
        self._failed_repeat_count = 0

    def _reset_program_state(self) -> None:
        """子类钩子：一个程序开始时重置本面独有的状态（默认无状态）"""

    async def _after_program(self) -> None:
        """子类钩子：程序无错跑完后的收尾结算（默认无动作）"""

    async def _dispatch(self, name: str, args: dict[str, Any], *, line: int | None) -> Any:
        """子类钩子：执行一次具名调用（默认拒绝，子类必须覆盖）"""
        # 回执只报事实（哪个名字没开放）：可用名字在 execute_code 的说明里，属提示词面
        raise ProgramFault(
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
            raise ProgramFault("程序为空：请提交要执行的 Python 程序", code="empty_program")
        if len(code) > program_contract.PROGRAM_MAX_CODE_CHARS:
            raise ProgramFault(
                f"程序超过 {program_contract.PROGRAM_MAX_CODE_CHARS} 字符（当前 {len(code)}）",
                code="program_too_large",
            )
        try:
            body = ast.parse(code).body
        except SyntaxError as exc:
            raise ProgramFault(f"语法错误：{exc.msg}", code="syntax_error", line=exc.lineno) from None
        if not body:
            raise ProgramFault("程序为空：请提交要执行的 Python 程序", code="empty_program")
        return body

    def _preflight_syntax(self, nodes: list[ast.stmt]) -> None:
        """整段检查语法白名单；不求值、不调用工具，避免前半段写入后才发现禁用语法

        放行常见语法：条件表达式、and/or/not、算术与序比较、is/is not、
        链式比较、* 与 ** 解包、基础函数（BUILTIN_FUNCTION_NAMES）。
        """
        statements = (ast.Assign, ast.Expr, ast.For, ast.If, ast.Pass)
        expressions = (
            ast.Constant,
            ast.Name,
            ast.List,
            ast.Tuple,
            ast.Dict,
            ast.Subscript,
            ast.UnaryOp,
            ast.BinOp,
            ast.Compare,
            ast.Call,
            ast.IfExp,
            ast.BoolOp,
            ast.Starred,
        )
        markers = (
            ast.Load,
            ast.Store,
            ast.USub,
            ast.Not,
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.Div,
            ast.FloorDiv,
            ast.Mod,
            ast.Eq,
            ast.NotEq,
            ast.In,
            ast.NotIn,
            ast.Is,
            ast.IsNot,
            ast.Lt,
            ast.LtE,
            ast.Gt,
            ast.GtE,
            ast.And,
            ast.Or,
            ast.keyword,
        )
        for statement in nodes:
            for node in ast.walk(statement):
                self._guard()
                line = getattr(node, "lineno", None)
                if isinstance(node, ast.stmt) and not isinstance(node, statements):
                    raise ProgramFault(
                        f"未支持的 Python 语句：{type(node).__name__}", code="unsupported_statement", line=line
                    )
                if not isinstance(node, (*statements, *expressions, *markers)):
                    raise ProgramFault(
                        f"未支持的 Python 表达式：{type(node).__name__}", code="unsupported_expression", line=line
                    )
                if isinstance(node, ast.Assign) and len(node.targets) != 1:
                    raise ProgramFault("只支持单目标赋值或等长解包", code="bad_assignment", line=line)
                if isinstance(node, (ast.Assign, ast.For)):
                    target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                    if any(isinstance(part, (ast.Call, ast.Starred)) for part in ast.walk(target)):
                        raise ProgramFault("赋值目标不能调用函数或使用星号解包", code="bad_assignment", line=line)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    if (
                        node.id in self.tools
                        or node.id == "range"
                        or node.id in BUILTIN_FUNCTION_NAMES
                        or node.id.startswith("_")
                    ):
                        raise ProgramFault(f"不允许使用保留变量名：{node.id}", code="name_reserved", line=line)
                if isinstance(node, ast.Call):
                    if not isinstance(node.func, ast.Name):
                        raise ProgramFault(
                            "不支持属性调用：对象方法不在开放面；取键与写回用下标（x['键']），"
                            "拼接用 +，功能项用目录列出的工具",
                            code="unsupported_expression",
                            line=line,
                        )
                    name = node.func.id
                    if name not in self.tools and name != "range" and name not in BUILTIN_FUNCTION_NAMES:
                        raise ProgramFault(_unknown_function_message(name), code="unknown_tool", line=line)
                    if name == "range":
                        invalid = not 1 <= len(node.args) <= 3 or bool(node.keywords)
                        message = "range 只接受1至3个整数位置参数"
                    elif name in BUILTIN_FUNCTION_NAMES:
                        invalid = bool(node.keywords)
                        message = f"{name} 只接受位置参数"
                    else:
                        invalid = bool(node.args)
                        message = "工具只接受具名参数（可用 ** 展开字典）"
                    if invalid:
                        raise ProgramFault(message, code="bad_call", line=line)

    def _receipt(
        self,
        *,
        status: str,
        applied: int,
        failed: list[dict[str, Any]],
        error: dict[str, Any] | None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """用于组装压缩回执（成功明文不回显，只给进度/读结果/失败清单）

        键序：失败与读结果排在进度之前。
        回执带 written 生效键清单：written 按提交顺序去重回显，模型照抄即可。
        """
        body: dict[str, Any] = {
            "status": status,
            "applied": applied,
            "progress": self._progress(),
        }
        written: list[str] = []
        program_ops = [op for op in self.ops if op.get("program_id") == self._program_id]
        for op in program_ops:
            record = op.get("record")
            if op.get("status") == "success" and record and record not in written:
                written.append(str(record))
        if written:
            body["written"] = written
        if failed:
            body["failed"] = [_failed_view(op) for op in failed]
        if note is not None:
            body["note"] = note
        if error is not None:
            body["error"] = error
        if self.reads:
            body["reads"] = list(self.reads)
        if self._reads_omitted:
            body["reads_omitted"] = self._reads_omitted
        if self._read_references:
            body["references"] = list(self._read_references)
        variables = {
            name: read_references(value)[0]
            for name, value in self.env.items()
            if isinstance(value, dict) and value.get("source_ref")
        }
        if variables:
            body["variables"] = variables
        return body

    # ------------------------------------------------------------------
    # 语句与表达式求值（白名单：非白名单节点结构化拒绝，不裸抛）

    async def _statements(self, nodes: list[Any]) -> None:
        """用于逐语句执行程序体（赋值/表达式/for/if 四类）"""
        for node in nodes:
            self._guard()
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                await self._assign(node.targets[0], await self._value(node.value))
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
                raise ProgramFault(
                    f"未支持的 Python 语句：{type(node).__name__}（只支持赋值、函数调用、for、if）",
                    code="unsupported_statement",
                    line=getattr(node, "lineno", None),
                )

    async def _for_loop(self, node: ast.For) -> None:
        """用于执行有上限的 for（迭代项必须是有界列表/元组/字典按键，不支持 while）"""
        values = await self._value(node.iter)
        if isinstance(values, dict):
            # 字典按键遍历与 Python 语义一致，插入序稳定且有界
            values = list(values)
        if not isinstance(values, (list, tuple)):
            raise ProgramFault(
                "for 只能遍历列表、元组或字典（可用变量或字面量）",
                code="unsupported_expression",
                line=node.lineno,
            )
        if len(values) > program_contract.PROGRAM_MAX_LOOP_ITEMS:
            raise ProgramFault(
                f"for 的迭代项超过 {program_contract.PROGRAM_MAX_LOOP_ITEMS} 条（当前 {len(values)}）",
                code="loop_too_long",
                line=node.lineno,
            )
        for item in values:
            self._guard()
            await self._assign(node.target, item)
            await self._statements(node.body)
        await self._statements(node.orelse)

    async def _assign(self, node: Any, value: Any) -> None:
        """变量、等长解包及字典下标赋值；容器不允许环或无限增长"""
        if isinstance(node, ast.Name):
            if node.id in self.tools or node.id == "range" or node.id in BUILTIN_FUNCTION_NAMES:
                raise ProgramFault(
                    f"不允许覆盖工具名或基础函数名：{node.id}；请把变量改为 {node.id}_result，工具名须保留以便后续调用",
                    code="name_reserved",
                    line=getattr(node, "lineno", None),
                )
            if node.id.startswith("_"):
                raise ProgramFault(
                    f"不允许使用 _ 前缀变量名：{node.id}",
                    code="name_reserved",
                    line=getattr(node, "lineno", None),
                )
            self.env[node.id] = value
            return
        if isinstance(node, (ast.Tuple, ast.List)):
            items = value if isinstance(value, (list, tuple)) else None
            if items is None or len(items) != len(node.elts):
                raise ProgramFault(
                    "赋值解包两端长度必须相等",
                    code="bad_assignment",
                    line=getattr(node, "lineno", None),
                )
            for target, item in zip(node.elts, items, strict=True):
                await self._assign(target, item)
            return
        if isinstance(node, ast.Subscript):
            container = await self._value(node.value)
            key = await self._value(node.slice)
            if not isinstance(container, dict) or type(key) not in (str, int, float, bool, type(None)):
                raise ProgramFault("下标赋值只接受字典与标量键", code="bad_assignment", line=node.lineno)
            if key not in container and len(container) >= program_contract.PROGRAM_MAX_LOOP_ITEMS:
                raise ProgramFault("字典条目超过容器上限", code="collection_too_long", line=node.lineno)
            pending, visited = [value], set()
            while pending:
                self._guard()
                item = pending.pop()
                if item is container:
                    raise ProgramFault("字典赋值不能形成循环引用", code="bad_assignment", line=node.lineno)
                if isinstance(item, (dict, list, tuple)) and id(item) not in visited:
                    visited.add(id(item))
                    pending.extend(item.values() if isinstance(item, dict) else item)
            container[key] = value
            return
        raise ProgramFault(
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
            raise ProgramFault(f"不支持的常量：{type(node.value).__name__}", code="unsupported_expression", line=line)
        if isinstance(node, ast.Name):
            return self._resolve_name(node.id, line=line)
        if isinstance(node, ast.List):
            return await self._container_values(node.elts, as_tuple=False, line=line)
        if isinstance(node, ast.Tuple):
            return await self._container_values(node.elts, as_tuple=True, line=line)
        if isinstance(node, ast.Dict):
            result: dict[Any, Any] = {}
            for key_node, value_node in zip(node.keys, node.values, strict=True):
                if key_node is None:
                    # 放行 ** 解包：键为 None 即 {**mapping}
                    spread = await self._value(value_node)
                    if not isinstance(spread, dict):
                        raise ProgramFault("** 展开只接受字典", code="runtime_error", line=line)
                    result.update(spread)
                else:
                    result[await self._value(key_node)] = await self._value(value_node)
            return result
        if isinstance(node, ast.Subscript):
            value = await self._value(node.value)
            index = await self._value(node.slice)
            try:
                return value[index]
            except (KeyError, IndexError, TypeError) as exc:
                keys = "、".join(str(key) for key in value)[:300] if isinstance(value, dict) else ""
                hint = f"；实际可用键：{keys}" if keys else ""
                raise ProgramFault(f"下标不可用：{exc}{hint}", code="runtime_error", line=line) from None
        if isinstance(node, ast.BinOp):
            left, right = await self._value(node.left), await self._value(node.right)
            if isinstance(node.op, ast.Add):
                if isinstance(left, list) and isinstance(right, list):
                    if len(left) + len(right) > program_contract.PROGRAM_MAX_LOOP_ITEMS:
                        raise ProgramFault("列表拼接超过容器上限", code="collection_too_long", line=line)
                    return left + right
                if isinstance(left, list) or isinstance(right, list):
                    raise ProgramFault("+ 不能把列表与非列表相加", code="runtime_error", line=line)
            return self._number_op(left, node.op, right, line=line)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                operand = await self._value(node.operand)
                if not isinstance(operand, (int, float)) or isinstance(operand, bool):
                    raise ProgramFault("一元负号只接受数字", code="runtime_error", line=line)
                return -operand
            if isinstance(node.op, ast.Not):
                return not bool(await self._value(node.operand))
        if isinstance(node, ast.BoolOp):
            # and/or 短路求值，按 Python 语义返回决定结果的那个值（不强制转布尔）
            is_and = isinstance(node.op, ast.And)
            last: Any = None
            for item in node.values:
                last = await self._value(item)
                if is_and and not last:
                    return last
                if not is_and and last:
                    return last
            return last
        if isinstance(node, ast.IfExp):
            branch = node.body if bool(await self._value(node.test)) else node.orelse
            return await self._value(branch)
        if isinstance(node, ast.Starred):
            raise ProgramFault(
                "星号解包只能用在列表/元组/字典字面量或工具的 ** 参数里",
                code="unsupported_expression",
                line=line,
            )
        if isinstance(node, ast.Compare):
            return await self._compare(node, line=line)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return await self._call(node, line=line)
        raise ProgramFault(
            f"未支持的 Python 表达式：{type(node).__name__}",
            code="unsupported_expression",
            line=line,
        )

    async def _container_values(self, elts: list[Any], *, as_tuple: bool, line: int | None) -> Any:
        """列表/元组字面量求值；* 展开只接受列表或元组，展开结果受容器上限约束"""
        result: list[Any] = []
        for item in elts:
            if isinstance(item, ast.Starred):
                spread = await self._value(item.value)
                if not isinstance(spread, (list, tuple)):
                    raise ProgramFault("* 展开只接受列表或元组", code="runtime_error", line=line)
                result.extend(spread)
                if len(result) > program_contract.PROGRAM_MAX_LOOP_ITEMS:
                    raise ProgramFault("* 展开超过容器上限", code="collection_too_long", line=line)
            else:
                result.append(await self._value(item))
        return tuple(result) if as_tuple else result

    def _number_op(self, left: Any, operator: Any, right: Any, *, line: int | None) -> Any:
        """算术只接受数字；+ 的数字分支也走这里（列表拼接在上游处理）"""
        names = {
            ast.Add: "+",
            ast.Sub: "-",
            ast.Mult: "*",
            ast.Div: "/",
            ast.FloorDiv: "//",
            ast.Mod: "%",
        }
        if type(left) not in (int, float) or type(right) not in (int, float):
            symbol = names.get(type(operator), "算术")
            raise ProgramFault(f"算术 {symbol} 只支持数字", code="runtime_error", line=line)
        try:
            if isinstance(operator, ast.Add):
                return left + right
            if isinstance(operator, ast.Sub):
                return left - right
            if isinstance(operator, ast.Mult):
                return left * right
            if isinstance(operator, ast.Div):
                return left / right
            if isinstance(operator, ast.FloorDiv):
                return left // right
            if isinstance(operator, ast.Mod):
                return left % right
        except ZeroDivisionError:
            raise ProgramFault("除以零", code="runtime_error", line=line) from None
        raise ProgramFault(f"未支持的算术运算：{type(operator).__name__}", code="unsupported_expression", line=line)

    async def _compare(self, node: ast.Compare, *, line: int | None) -> bool:
        """比较运算：==/!=/in/not in/</<=/>/>=/is/is not，支持链式（a < b < c）

        放行序比较、is/is not 与链式比较；中间操作数只求值一次。
        """
        left = await self._value(node.left)
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            right = await self._value(comparator)
            if isinstance(operator, ast.Eq):
                ok = left == right
            elif isinstance(operator, ast.NotEq):
                ok = left != right
            elif isinstance(operator, (ast.In, ast.NotIn)):
                if not isinstance(right, (list, tuple, dict, str)):
                    raise ProgramFault("in 的右侧需要列表/元组/字典/字符串", code="runtime_error", line=line)
                ok = left in right
                if isinstance(operator, ast.NotIn):
                    ok = not ok
            elif isinstance(operator, ast.Is):
                ok = left is right
            elif isinstance(operator, ast.IsNot):
                ok = left is not right
            elif isinstance(operator, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                ok = self._order_compare(left, operator, right, line=line)
            else:
                raise ProgramFault(
                    f"未支持的比较运算：{type(operator).__name__}",
                    code="unsupported_expression",
                    line=line,
                )
            if not ok:
                return False
            left = right
        return True

    def _order_compare(self, left: Any, operator: Any, right: Any, *, line: int | None) -> bool:
        """序比较只接受同为数字或同为字符串（与算术同口径，排除 bool）"""
        both_numbers = type(left) in (int, float) and type(right) in (int, float)
        both_strings = isinstance(left, str) and isinstance(right, str)
        if not (both_numbers or both_strings):
            raise ProgramFault("序比较只支持同为数字或同为字符串", code="runtime_error", line=line)
        if isinstance(operator, ast.Lt):
            return left < right
        if isinstance(operator, ast.LtE):
            return left <= right
        if isinstance(operator, ast.Gt):
            return left > right
        return left >= right

    def _resolve_name(self, name: str, *, line: int | None) -> Any:
        """用于变量查值：常量别名（true/false/null）先命中，再查变量环境"""
        key = name.strip().casefold()
        if key in _program._PROGRAM_NAME_CONSTANTS:
            return _program._PROGRAM_NAME_CONSTANTS[key]
        if name in self.env:
            return self.env[name]
        known = "、".join(sorted(self.env)[:12])
        hint = f"；已定义变量：{known}" if known else ""
        raise ProgramFault(
            f"未定义的名称：{name}（常量请写 True/False/None，也接受 true/false/null）{hint}",
            code="undefined_name",
            line=line,
        )

    def _call_hint(self, name: str) -> str:
        """用于在调用写法错时把该名字的真实用法回给模型（构造器签名或工具参数名）

        参数名与目录同源（call_parameters）：拒绝里给的签名与模型读到的签名逐字一致。
        """
        try:
            return render_list_signature(name, call_parameters(name, self.tools.get(name)))
        except (TypeError, ValueError):
            return f"{name}(...)"

    async def _call(self, node: ast.Call, *, line: int | None) -> Any:
        """用于执行一次具名调用（名字属于工具、基础函数或 range；工具只收具名参数）"""
        function = node.func
        if not isinstance(function, ast.Name):
            raise ProgramFault(
                "只支持直接调用工具函数（不支持属性访问或嵌套调用）",
                code="unsupported_expression",
                line=line,
            )
        name = function.id
        if name == "range":
            arguments = [await self._value(arg) for arg in node.args]
            if node.keywords or not 1 <= len(arguments) <= 3 or any(type(arg) is not int for arg in arguments):
                raise ProgramFault("range 只接受1至3个整数位置参数", code="bad_call", line=line)
            try:
                values = range(*arguments)
                if len(values) > program_contract.PROGRAM_MAX_LOOP_ITEMS:
                    raise OverflowError
            except OverflowError:
                raise ProgramFault("range 项数超过循环上限", code="loop_too_long", line=line) from None
            except ValueError:
                raise ProgramFault("range 的步长不能为0", code="bad_call", line=line) from None
            return list(values)
        if name in BUILTIN_FUNCTION_NAMES:
            if node.keywords:
                raise ProgramFault(f"{name} 只接受位置参数", code="bad_call", line=line)
            arguments = [await self._value(arg) for arg in node.args]
            return self._builtin(name, arguments, line=line)
        if name not in self.tools:
            raise ProgramFault(
                _unknown_function_message(name),
                code="unknown_tool",
                line=line,
            )
        if node.args:
            hint = (
                f'{name}(query="关键词", limit=5)'
                if name in {"search_events", "search_graph"}
                else self._call_hint(name)
            )
            raise ProgramFault(
                f"工具只接受具名参数（可用 ** 展开字典）；{name} 的正确写法：{hint}",
                code="bad_call",
                line=line,
            )
        args: dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                # 放行 ** 展开：展开后仍是具名参数
                expanded = await self._value(keyword.value)
                if not isinstance(expanded, dict) or any(not isinstance(key, str) for key in expanded):
                    raise ProgramFault("** 展开只接受以字符串为键的字典", code="bad_call", line=line)
                args.update(expanded)
            else:
                args[str(keyword.arg)] = await self._value(keyword.value)
        return await self._dispatch(name, args, line=line)

    def _builtin(self, name: str, values: list[Any], *, line: int | None) -> Any:
        """基础函数的只读纯函数实现（只接受位置参数）"""
        if name == "len":
            if not isinstance(values, list) or len(values) != 1:
                raise ProgramFault("len 需要 1 个参数", code="bad_call", line=line)
            target = values[0]
            if not isinstance(target, (list, tuple, dict, str)):
                raise ProgramFault("len 只接受列表/元组/字典/字符串", code="runtime_error", line=line)
            return len(target)
        if name == "str":
            if not isinstance(values, list) or len(values) != 1:
                raise ProgramFault("str 需要 1 个参数", code="bad_call", line=line)
            return str(values[0])
        if name in {"int", "float"}:
            if len(values) != 1:
                raise ProgramFault(f"{name} 需要 1 个参数", code="bad_call", line=line)
            target = values[0]
            if isinstance(target, str):
                try:
                    return int(target) if name == "int" else float(target)
                except ValueError:
                    raise ProgramFault(f"{name} 不能转换该字符串", code="runtime_error", line=line) from None
            if isinstance(target, (int, float)):
                return int(target) if name == "int" else float(target)
            raise ProgramFault(f"{name} 只接受数字或数字字符串", code="runtime_error", line=line)
        if name == "bool":
            if len(values) != 1:
                raise ProgramFault("bool 需要 1 个参数", code="bad_call", line=line)
            return bool(values[0])
        if name in {"min", "max"}:
            if len(values) == 1 and isinstance(values[0], (list, tuple)):
                items = list(values[0])
            elif len(values) >= 2:
                items = list(values)
            else:
                raise ProgramFault(f"{name} 需要多个参数或一个列表", code="bad_call", line=line)
            try:
                return min(items) if name == "min" else max(items)
            except ValueError:
                raise ProgramFault(f"{name} 不能用于空序列", code="runtime_error", line=line) from None
            except TypeError:
                raise ProgramFault(f"{name} 的元素类型不一致，无法比较", code="runtime_error", line=line) from None
        if name == "abs":
            if len(values) != 1 or type(values[0]) not in (int, float):
                raise ProgramFault("abs 只接受 1 个数字", code="runtime_error", line=line)
            return abs(values[0])
        if name == "sum":
            if len(values) != 1 or not isinstance(values[0], (list, tuple)):
                raise ProgramFault("sum 只接受一个列表或元组", code="bad_call", line=line)
            try:
                return sum(values[0])
            except TypeError:
                raise ProgramFault("sum 的元素必须是数字", code="runtime_error", line=line) from None
        if name == "sorted":
            if len(values) != 1 or not isinstance(values[0], (list, tuple)):
                raise ProgramFault("sorted 只接受一个列表或元组", code="bad_call", line=line)
            try:
                return sorted(values[0])
            except TypeError:
                raise ProgramFault("sorted 的元素类型不一致，无法排序", code="runtime_error", line=line) from None
        if name == "enumerate":
            if not 1 <= len(values) <= 2 or not isinstance(values[0], (list, tuple)):
                raise ProgramFault("enumerate 接受一个列表/元组与可选起始值", code="bad_call", line=line)
            start = values[1] if len(values) == 2 else 0
            if len(values) == 2 and type(start) is not int:
                raise ProgramFault("enumerate 的起始值必须是整数", code="bad_call", line=line)
            if len(values[0]) > program_contract.PROGRAM_MAX_LOOP_ITEMS:
                raise ProgramFault("enumerate 超过容器上限", code="collection_too_long", line=line)
            return list(enumerate(values[0], start))
        raise ProgramFault(f"未开放函数：{name}", code="unknown_tool", line=line)

    def _next_op_index(self, *, line: int | None) -> int:
        """用于分配程序内 op 序号并强制单程序操作条数硬限（越限可续跑）"""
        if self._ops_in_program >= program_contract.PROGRAM_MAX_OPS:
            raise ProgramFault(
                f"单个程序的内层操作超过 {program_contract.PROGRAM_MAX_OPS} 条",
                code="too_many_ops",
                line=line,
            )
        self._ops_in_program += 1
        return self._ops_in_program

    def _next_call_index(self) -> int:
        """用于分配内层 op 的审计 call_index（_program._INNER_CALL_INDEX_BASE + 章内递增序号）"""
        index = _program._INNER_CALL_INDEX_BASE + self._call_index_seq
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
                "receipt": {key: body[key] for key in ("record", "ref", "warnings", "case_link") if key in body},
                "record": body.get("record") or tool_record_key(name, dict(call_args or {})),
                "error_code": body.get("code"),
                "field": body.get("field"),
                "actual": body.get("actual"),
                "expected": body.get("expected"),
                "message": body.get("message") or body.get("error") or error,
                "direct_fallback": direct_fallback,
            }
        )
        if status == "success" and name in _program._READ_TOOL_NAMES:
            self._note_read(name, op_index=op_index, line=line, receipt=receipt)

    def _note_read(self, name: str, *, op_index: int, line: int | None, receipt: Any) -> None:
        """用于把一次成功的检索读结果挂进回执 reads（内容不截断，只留最近若干条）

        这里把 payload 原样回显（投影已在 _ProgramSearchTool 做过），回显一律给全量；
        条数上限保留。
        """
        item: dict[str, Any] = {"op": op_index, "tool": name}
        if line is not None:
            item["line"] = line
        item["result"] = receipt if isinstance(receipt, str) else json.dumps(receipt, ensure_ascii=False)
        for reference in read_references(receipt):
            if not any(existing["source_ref"] == reference["source_ref"] for existing in self._read_references):
                self._read_references.append({"op": op_index, **reference})
        self.reads.append(item)
        if len(self.reads) > _program._READ_ECHO_MAX_ITEMS:
            dropped = len(self.reads) - _program._READ_ECHO_MAX_ITEMS
            del self.reads[:dropped]
            self._reads_omitted += dropped

    def _guard(self) -> None:
        """用于在每条语句/表达式前检查步数与墙钟硬限"""
        self._steps += 1
        if self._steps > program_contract.PROGRAM_MAX_STEPS:
            raise ProgramFault(
                f"单次程序执行步数超过 {program_contract.PROGRAM_MAX_STEPS}（疑似循环过大）",
                code="too_many_steps",
            )
        if time.monotonic() > self._deadline:
            raise ProgramFault(
                f"单次程序执行超过 {int(program_contract.PROGRAM_DEADLINE_S)} 秒硬限",
                code="deadline_exceeded",
            )
