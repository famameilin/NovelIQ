"""受限 AST 解释器、变量环境与执行预算"""

from __future__ import annotations

import ast
import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

# 限额通过契约模块属性读取，支持显式注入
from src.agents.program_runtime import contracts as _program
from src.agents.program_runtime import contracts as program_contract
from src.agents.program_runtime.contracts import ProgramExecutionTimeout, ProgramFault
from src.agents.program_runtime.receipts import failed_view, read_references

# 重复失败批守卫（两级）：失败条数达到 _REPEAT_FAILED_BATCH_MIN_OPS 且连续两次程序的
# 失败清单逐条相同时注入聚合提示，第三次相同判本程序失败。
_REPEAT_FAILED_BATCH_MIN_OPS = 5
_REPEAT_FAILED_BATCH_FATAL_AT = 3

# 放行常见语法：通配符、表达式、基础函数。
# 基础函数只读纯函数，与 range 同属解释器内置：不进工具目录，也不允许被赋值覆盖。
BUILTIN_FUNCTION_NAMES = frozenset(
    {
        "len",
        "str",
        "int",
        "float",
        "bool",
        "min",
        "max",
        "abs",
        "sum",
        "sorted",
        "enumerate",
        "isinstance",
        "any",
        "all",
        "round",
        "repr",
        "print",
        "list",
        "dict",
        "set",
        "tuple",
        "zip",
        "reversed",
        "format",
    }
)

_TYPE_NAMES = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
}
_ABSENT = object()


class _ProgramLambda:
    "程序里 lambda 的可调用包装：只接受位置参数"

    def __init__(self, invoke: Any) -> None:
        self._invoke = invoke

    async def __call__(self, *values: Any) -> Any:
        return await self._invoke(*values)


class _ProgramFunction:
    "程序内 def 的包装：无默认值位置参数，变量环境由运行时共享"

    def __init__(self, name: str, parameters: list[str], body: list[Any]) -> None:
        self.name = name
        self.parameters = parameters
        self.body = body


class _ReturnSignal(Exception):
    "函数体 return 的控制流信号，只由函数调用边界与程序入口捕获"

    def __init__(self, value: Any) -> None:
        self.value = value


class _BreakSignal(Exception):
    "break 的控制流信号，只由循环边界捕获"


class _ContinueSignal(Exception):
    "continue 的控制流信号，只由循环边界捕获"


# 内置容器与字符串的常用方法；接收者类型、参数个数与返回值仍由运行时校验
_METHOD_NAMES = frozenset(
    {
        "get",
        "keys",
        "values",
        "items",
        "copy",
        "update",
        "pop",
        "append",
        "extend",
        "insert",
        "remove",
        "sort",
        "reverse",
        "index",
        "count",
        "split",
        "rsplit",
        "strip",
        "lstrip",
        "rstrip",
        "replace",
        "startswith",
        "endswith",
        "find",
        "rfind",
        "join",
        "lower",
        "upper",
        "casefold",
        "isdigit",
        "isalpha",
        "isspace",
        "title",
        "capitalize",
    }
)


def _unknown_function_message(name: str) -> str:
    """未开放函数的回执点名可用范围；预检与运行时两条路径共用本条回执"""
    builtins = "、".join(sorted(BUILTIN_FUNCTION_NAMES))
    return f"未开放函数：{name}；可调用的函数只有目录列出的工具、基础函数（{builtins}）与 range，没有其他内置函数"


def _expression_text(node: ast.expr) -> str:
    "还原被拒表达式的源码写法，供拒绝回执点名"
    return ast.unparse(node)


class RestrictedProgramRuntime:
    """受限 AST 执行与变量环境，业务调用由各领域分发"""

    # 工具目录从当前信封的实际工具表生成
    contract_text: str = ""

    def __init__(
        self,
        tool_list: list[Any],
        namespace: dict[str, Any],
        *,
        observer: Any = None,
        stream: Any = None,
        signature_hint: Callable[[str], str] | None = None,
        record_key: Callable[[str, dict[str, Any]], str | None] | None = None,
    ) -> None:
        """以同一工具表生成目录并分发调用，不保留构造器编译路径"""
        self._signature_hint = signature_hint
        self._record_key = record_key
        self.tool_list = list(tool_list)
        self.tools: dict[str, Any] = dict(namespace)
        self.observer = observer
        self.stream = stream
        self.env: dict[str, Any] = {}
        # 章内逐 op 记录（审计与统计口径：program_id/op_index/source_line/tool_name/
        # status/record/error_code/direct_fallback）
        self.ops: list[dict[str, Any]] = []
        # 本程序内检索读结果的回显（每次 execute 重置；见 _program._READ_TOOL_NAMES）
        self.reads: list[dict[str, Any]] = []
        # print 输出按程序回显，不产生工具调用
        self.printed: list[str] = []
        self._read_references: list[dict[str, Any]] = []
        self._reads_omitted = 0
        self._program_seq = 0
        self._call_index_seq = 0
        self._program_id = ""
        self._ops_in_program = 0
        self._schedule_ticks = 0
        self._next_yield = 256
        self._deadline = 0.0
        # 导入绑定跨程序保留：模块名与 from 导入的函数名都按真实身份登记
        self._module_aliases: dict[str, str] = {}
        self._imported_names: dict[str, tuple[str, str]] = {}
        # 本程序 return 的结果与被捕获的运行期故障（每次 execute 重置）
        self._program_result: Any = _ABSENT
        self._caught: list[dict[str, Any]] = []
        # 重复失败批守卫状态（跨程序、章内持续）
        self._last_failed_sig: tuple[tuple[str, str, str, str], ...] | None = None
        self._failed_repeat_count = 0

    # 程序入口

    async def execute(self, code: str) -> str:
        """执行一段 Python 程序并返回压缩回执（模型面唯一入口）"""

        async def run() -> None:
            nodes = self._parse(code)
            self._preflight_syntax(nodes)
            try:
                await self._statements(nodes)
            except _ReturnSignal as signal:
                # 顶层 return 是程序结果；函数内的 return 已由函数调用边界接走
                self._set_program_result(signal.value, line=None)
            except (_BreakSignal, _ContinueSignal):
                raise ProgramFault("break/continue 只能在循环内使用", code="runtime_error") from None

        return await self._execute_program(run)

    async def _execute_program(self, action: Callable[[], Awaitable[None]]) -> str:
        """程序文本与结构化提交共用限额、回执和逐条写入边界"""
        self._program_seq += 1
        self._program_id = f"p{self._program_seq}"
        self._ops_in_program = 0
        self._schedule_ticks = 0
        self._next_yield = 256
        self.reads = []
        self.printed = []
        self._read_references = []
        self._reads_omitted = 0
        self._program_result = _ABSENT
        self._caught = []
        self._deadline = time.monotonic() + program_contract.PROGRAM_DEADLINE_S
        self._reset_program_state()
        error: dict[str, Any] | None = None
        status = "applied"
        try:
            await action()
            self._guard()
        except ProgramFault as fault:
            error = fault.payload()
            status = "rejected" if fault.code in program_contract.PRE_RUN_FAULT_CODES else "runtime_error"
        # 重复失败批按结算前的操作快照判定，失败时不结算收尾意图
        # 回执统计包括收尾结算产生的操作
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
        receipt = json.dumps(
            self._receipt(status=status, applied=applied, failed=failed, error=error, note=note),
            ensure_ascii=False,
        )
        if error is not None and error["type"] == "deadline_exceeded":
            raise ProgramExecutionTimeout(receipt)
        return receipt

    def _register_failed_batch(self, failed: list[dict[str, Any]]) -> int:
        """用于给重复失败批守卫计数，返回"连续第几次提交同一失败批"（不足阈值重置为 0）"""
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

    def _scan_imports(self, nodes: list[ast.stmt]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
        "预检阶段收集导入绑定：与运行期同一份白名单，先判断属性调用是否成立"
        module_aliases = dict(self._module_aliases)
        imported_names = dict(self._imported_names)
        for statement in nodes:
            for node in ast.walk(statement):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name not in program_contract.PROGRAM_MODULES:
                            raise ProgramFault(
                                f"不开放的模块：{alias.name}；可导入的只有 "
                                f"{'、'.join(sorted(program_contract.PROGRAM_MODULES))}",
                                code="unsupported_statement",
                                line=node.lineno,
                            )
                        bound = alias.asname or alias.name
                        self._reserve_import_name(bound, line=node.lineno)
                        module_aliases[bound] = alias.name
                elif isinstance(node, ast.ImportFrom):
                    module_name = node.module or ""
                    if node.level or module_name not in program_contract.PROGRAM_MODULES:
                        raise ProgramFault(
                            f"不开放的模块：{module_name or '相对导入'}；可导入的只有 "
                            f"{'、'.join(sorted(program_contract.PROGRAM_MODULES))}",
                            code="unsupported_statement",
                            line=node.lineno,
                        )
                    allowed = program_contract.PROGRAM_MODULE_ATTRIBUTES.get(module_name, frozenset())
                    for alias in node.names:
                        if alias.name not in allowed:
                            raise ProgramFault(
                                f"{module_name} 不开放 {alias.name}；可导入的只有 {'、'.join(sorted(allowed))}",
                                code="unsupported_statement",
                                line=node.lineno,
                            )
                        bound = alias.asname or alias.name
                        self._reserve_import_name(bound, line=node.lineno)
                        imported_names[bound] = (module_name, alias.name)
        return module_aliases, imported_names

    @staticmethod
    def _unimported_module_hint(node: ast.Attribute, module_aliases: dict[str, str]) -> str | None:
        "属性基名是可导入模块但本程序没有 import 时，点名要先写的 import"
        base = node.value
        if not isinstance(base, ast.Name) or base.id in module_aliases:
            return None
        module_name = base.id
        if module_name not in program_contract.PROGRAM_MODULES:
            return None
        allowed = program_contract.PROGRAM_MODULE_ATTRIBUTES.get(module_name, frozenset())
        function = f"{module_name}.{node.attr}"
        if node.attr not in allowed:
            return f"{function} 未开放；{module_name} 只放行 {'、'.join(sorted(allowed))}"
        return f"调用 {function} 前先在本程序写 import {module_name}"

    def _preflight_syntax(self, nodes: list[ast.stmt]) -> None:
        """整段检查语法白名单；不求值、不调用工具，避免前半段写入后才发现禁用语法"""
        statements = (
            ast.Assign,
            ast.AugAssign,
            ast.Expr,
            ast.For,
            ast.While,
            ast.If,
            ast.Try,
            ast.Pass,
            ast.Break,
            ast.Continue,
            ast.FunctionDef,
            ast.Return,
            ast.Import,
            ast.ImportFrom,
        )
        expressions = (
            ast.Constant,
            ast.Name,
            ast.List,
            ast.Tuple,
            ast.Set,
            ast.Dict,
            ast.Subscript,
            ast.UnaryOp,
            ast.BinOp,
            ast.Compare,
            ast.Call,
            ast.IfExp,
            ast.BoolOp,
            ast.Starred,
            ast.ListComp,
            ast.SetComp,
            ast.DictComp,
            ast.Attribute,
            ast.Lambda,
            ast.JoinedStr,
            ast.FormattedValue,
        )
        module_aliases, imported_names = self._scan_imports(nodes)
        container_calls = {
            id(node.func)
            for statement in nodes
            for node in ast.walk(statement)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _METHOD_NAMES
        }
        module_calls = {
            id(node.func)
            for statement in nodes
            for node in ast.walk(statement)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in module_aliases
            and node.func.attr
            in program_contract.PROGRAM_MODULE_ATTRIBUTES.get(module_aliases[node.func.value.id], frozenset())
        }
        except_handlers = {
            id(node)
            for statement in nodes
            for node in ast.walk(statement)
            if isinstance(node, ast.ExceptHandler)
            and (
                node.type is None
                or (isinstance(node.type, ast.Name) and node.type.id == "Exception")
            )
        }
        lambda_names = {
            target.id
            for statement in nodes
            for node in ast.walk(statement)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        function_names = {
            node.name for statement in nodes for node in ast.walk(statement) if isinstance(node, ast.FunctionDef)
        }
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
            ast.comprehension,
            ast.Slice,
            ast.arguments,
            ast.arg,
            ast.ExceptHandler,
            ast.alias,
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
                if isinstance(node, ast.ExceptHandler) and id(node) not in except_handlers:
                    raise ProgramFault(
                        "except 只接受不写类型或 Exception，不支持其他异常类型与元组",
                        code="unsupported_statement",
                        line=line,
                    )
                if isinstance(node, ast.AugAssign) and not isinstance(node.target, (ast.Name, ast.Subscript)):
                    raise ProgramFault("增量赋值只支持变量与字典下标", code="bad_assignment", line=line)
                if isinstance(node, ast.Attribute) and id(node) not in container_calls and id(node) not in module_calls:
                    raise ProgramFault(
                        self._unimported_module_hint(node, module_aliases)
                        or f"不支持该属性访问 {_expression_text(node)}：只允许内置容器与字符串的常用方法"
                        "（如 dict.get/dict.items、list.append/list.extend、str.split/str.replace）；"
                        "已导入模块只允许调用放行函数（如 json.dumps），不开放属性读；"
                        "取键与写回用下标（x['键']），拼接用 +，功能项用目录列出的工具",
                        code="unsupported_expression",
                        line=line,
                    )
                if isinstance(node, ast.Assign) and len(node.targets) != 1:
                    raise ProgramFault("只支持单目标赋值或等长解包", code="bad_assignment", line=line)
                if isinstance(node, (ast.Assign, ast.For)):
                    target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                    if any(isinstance(part, (ast.Call, ast.Starred)) for part in ast.walk(target)):
                        raise ProgramFault("赋值目标不能调用函数或使用星号解包", code="bad_assignment", line=line)
                if isinstance(node, ast.FunctionDef):
                    arguments = node.args
                    if (
                        node.decorator_list
                        or arguments.posonlyargs
                        or arguments.vararg
                        or arguments.kwarg
                        or arguments.kwonlyargs
                        or arguments.defaults
                        or arguments.kw_defaults
                        or any(argument.annotation is not None for argument in arguments.args)
                        or node.returns is not None
                    ):
                        raise ProgramFault("def 只支持无默认值、无注解的普通位置参数", code="bad_call", line=line)
                    if (
                        node.name in self.tools
                        or node.name == "range"
                        or node.name in BUILTIN_FUNCTION_NAMES
                        or node.name in module_aliases
                        or node.name in imported_names
                        or (node.name.startswith("_") and node.name != "_")
                    ):
                        raise ProgramFault(f"不允许使用保留函数名：{node.name}", code="name_reserved", line=line)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    if (
                        node.id in self.tools
                        or node.id == "range"
                        or node.id in BUILTIN_FUNCTION_NAMES
                        or node.id in module_aliases
                        or node.id in imported_names
                        or (node.id.startswith("_") and node.id != "_")
                    ):
                        raise ProgramFault(f"不允许使用保留变量名：{node.id}", code="name_reserved", line=line)
                if isinstance(node, ast.Call):
                    if not isinstance(node.func, ast.Name):
                        if (
                            not isinstance(node.func, ast.Attribute)
                            or (id(node.func) not in container_calls and id(node.func) not in module_calls)
                        ):
                            hint = (
                                self._unimported_module_hint(node.func, module_aliases)
                                if isinstance(node.func, ast.Attribute)
                                else None
                            )
                            raise ProgramFault(
                                hint
                                or f"不支持该属性调用 {_expression_text(node.func)}："
                                "只允许内置容器与字符串的常用方法、已导入模块的放行属性；"
                                "取键与写回用下标（x['键']），拼接用 +，功能项用目录列出的工具",
                                code="unsupported_expression",
                                line=line,
                            )
                    else:
                        name = node.func.id
                        if name in lambda_names or name in function_names or name in imported_names:
                            continue
                        if name not in self.tools and name != "range" and name not in BUILTIN_FUNCTION_NAMES:
                            raise ProgramFault(_unknown_function_message(name), code="unknown_tool", line=line)
                        if name == "range":
                            invalid = not 1 <= len(node.args) <= 3 or bool(node.keywords)
                            message = "range 只接受1至3个整数位置参数"
                        elif name == "sorted":
                            invalid = any(keyword.arg not in {"key", "reverse"} for keyword in node.keywords)
                            message = "sorted 的关键字只接受 key 与 reverse"
                        elif name in {"min", "max"}:
                            invalid = any(keyword.arg != "key" for keyword in node.keywords)
                            message = f"{name} 的关键字只接受 key"
                        elif name == "dict":
                            invalid = False
                            message = ""
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
        """用于组装压缩回执（成功明文不回显，只给进度/读结果/失败清单）"""
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
            body["failed"] = [failed_view(op) for op in failed]
        if note is not None:
            body["note"] = note
        if error is not None:
            body["error"] = error
        if self.reads:
            body["reads"] = list(self.reads)
        if self.printed:
            body["printed"] = list(self.printed)
        if self._reads_omitted:
            body["reads_omitted"] = self._reads_omitted
        if self._program_result is not _ABSENT:
            body["result"] = self._program_result
        if self._caught:
            body["caught"] = list(self._caught)
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

    # 语句与表达式求值（白名单：非白名单节点结构化拒绝，不裸抛）

    async def _statements(self, nodes: list[Any]) -> None:
        """用于逐语句执行程序体（赋值/表达式/循环/条件/函数/导入/收尾）"""
        for node in nodes:
            await self._checkpoint()
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                await self._assign(node.targets[0], await self._value(node.value))
            elif isinstance(node, ast.AugAssign):
                await self._aug_assign(node)
            elif isinstance(node, ast.Expr):
                await self._value(node.value)
            elif isinstance(node, ast.For):
                await self._for_loop(node)
            elif isinstance(node, ast.While):
                await self._while_loop(node)
            elif isinstance(node, ast.If):
                body = node.body if bool(await self._value(node.test)) else node.orelse
                await self._statements(body)
            elif isinstance(node, ast.Try):
                await self._try_block(node)
            elif isinstance(node, ast.Pass):
                continue
            elif isinstance(node, ast.FunctionDef):
                self._define_function(node)
            elif isinstance(node, ast.Import):
                self._import_modules(node)
            elif isinstance(node, ast.ImportFrom):
                self._import_from(node)
            elif isinstance(node, ast.Break):
                raise _BreakSignal()
            elif isinstance(node, ast.Continue):
                raise _ContinueSignal()
            elif isinstance(node, ast.Return):
                raise _ReturnSignal(await self._value(node.value) if node.value is not None else None)
            else:
                raise ProgramFault(
                    f"未支持的 Python 语句：{type(node).__name__}",
                    code="unsupported_statement",
                    line=getattr(node, "lineno", None),
                )

    def _import_modules(self, node: ast.Import) -> None:
        "import 只绑定静态登记的模块对象，不做动态导入"
        for alias in node.names:
            module_name = alias.name
            if module_name not in program_contract.PROGRAM_MODULES:
                raise ProgramFault(
                    f"不开放的模块：{module_name}；可导入的只有 "
                    f"{'、'.join(sorted(program_contract.PROGRAM_MODULES))}",
                    code="unsupported_statement",
                    line=node.lineno,
                )
            bound = alias.asname or module_name
            self._reserve_import_name(bound, line=node.lineno)
            self.env[bound] = program_contract.PROGRAM_MODULES[module_name]
            self._module_aliases[bound] = module_name

    def _import_from(self, node: ast.ImportFrom) -> None:
        "from 导入只绑定该模块放行的可调用项"
        module_name = node.module or ""
        if node.level or module_name not in program_contract.PROGRAM_MODULES:
            raise ProgramFault(
                f"不开放的模块：{module_name or '相对导入'}；可导入的只有 "
                f"{'、'.join(sorted(program_contract.PROGRAM_MODULES))}",
                code="unsupported_statement",
                line=node.lineno,
            )
        allowed = program_contract.PROGRAM_MODULE_ATTRIBUTES.get(module_name, frozenset())
        for alias in node.names:
            if alias.name not in allowed:
                raise ProgramFault(
                    f"{module_name} 不开放 {alias.name}；可导入的只有 {'、'.join(sorted(allowed))}",
                    code="unsupported_statement",
                    line=node.lineno,
                )
            bound = alias.asname or alias.name
            self._reserve_import_name(bound, line=node.lineno)
            self.env[bound] = getattr(program_contract.PROGRAM_MODULES[module_name], alias.name)
            self._imported_names[bound] = (module_name, alias.name)

    def _reserve_import_name(self, name: str, *, line: int | None) -> None:
        "导入绑定不得覆盖工具名、基础函数名或 _ 前缀"
        if name in self.tools or name == "range" or name in BUILTIN_FUNCTION_NAMES or name.startswith("_"):
            raise ProgramFault(
                f"不允许用导入覆盖保留名：{name}；请改用 as 起一个别的名字",
                code="name_reserved",
                line=line,
            )

    def _define_function(self, node: ast.FunctionDef) -> None:
        "把 def 绑定到程序环境；参数绑定与 return 由调用边界处理"
        self.env[node.name] = _ProgramFunction(node.name, [argument.arg for argument in node.args.args], node.body)

    async def _invoke_function(self, function: _ProgramFunction, values: list[Any], *, line: int | None) -> Any:
        "位置参数临时绑定，调用结束后恢复；return 由信号携带结果"
        if len(values) != len(function.parameters):
            raise ProgramFault(
                f"{function.name} 需要 {len(function.parameters)} 个参数，实际 {len(values)} 个",
                code="bad_call",
                line=line,
            )
        saved = {name: self.env.get(name, _ABSENT) for name in function.parameters}
        try:
            for name, value in zip(function.parameters, values, strict=True):
                self.env[name] = value
            try:
                await self._statements(function.body)
            except _ReturnSignal as signal:
                return signal.value
            except (_BreakSignal, _ContinueSignal):
                raise ProgramFault("break/continue 只能在循环内使用", code="runtime_error", line=line) from None
            return None
        finally:
            for name, previous in saved.items():
                if previous is _ABSENT:
                    self.env.pop(name, None)
                else:
                    self.env[name] = previous

    async def _for_loop(self, node: ast.For) -> None:
        """遍历列表、元组或字典键；break/continue 在循环边界接走"""
        values = await self._value(node.iter)
        if isinstance(values, dict):
            # 字典按键遍历与 Python 语义一致，插入序稳定且有界
            values = list(values)
        if not isinstance(values, (list, tuple, set)):
            raise ProgramFault(
                "for 只能遍历列表、元组、集合或字典（可用变量或字面量）",
                code="unsupported_expression",
                line=node.lineno,
            )
        broke = False
        for item in values:
            await self._checkpoint()
            await self._assign(node.target, item)
            try:
                await self._statements(node.body)
            except _BreakSignal:
                broke = True
                break
            except _ContinueSignal:
                continue
        if not broke:
            await self._statements(node.orelse)

    async def _while_loop(self, node: ast.While) -> None:
        """条件循环；迭代次数有独立硬限，期限之外不再依赖单次检查点"""
        iterations = 0
        broke = False
        while bool(await self._value(node.test)):
            iterations += 1
            if iterations > program_contract.PROGRAM_MAX_WHILE_ITERATIONS:
                raise ProgramFault(
                    f"while 循环超过 {program_contract.PROGRAM_MAX_WHILE_ITERATIONS} 次",
                    code="runtime_error",
                    line=node.lineno,
                )
            await self._checkpoint()
            try:
                await self._statements(node.body)
            except _BreakSignal:
                broke = True
                break
            except _ContinueSignal:
                continue
        if not broke:
            await self._statements(node.orelse)

    async def _try_block(self, node: ast.Try) -> None:
        """try/except/else/finally；只捕获运行期错误，其余故障继续上抛"""
        try:
            try:
                await self._statements(node.body)
            except ProgramFault as fault:
                if fault.code != "runtime_error":
                    raise
                handler = self._match_handler(node.handlers)
                if handler is None:
                    raise
                self._note_caught(fault)
                await self._run_handler(handler, fault)
            else:
                await self._statements(node.orelse)
        finally:
            await self._statements(node.finalbody)

    def _match_handler(self, handlers: list[ast.ExceptHandler]) -> ast.ExceptHandler | None:
        "只认无类型与 Exception 两种 except 子句，不做异常类型区分"
        for handler in handlers:
            if handler.type is None:
                return handler
            if isinstance(handler.type, ast.Name) and handler.type.id == "Exception":
                return handler
        return None

    async def _run_handler(self, handler: ast.ExceptHandler, fault: ProgramFault) -> None:
        "执行 except 块；as 名字临时绑定为故障详情，块内其他赋值仍留在环境中"
        name = handler.name
        if not name:
            await self._statements(handler.body)
            return
        saved = self.env.get(name, _ABSENT)
        try:
            self.env[name] = fault.payload()
            await self._statements(handler.body)
        finally:
            if saved is _ABSENT:
                self.env.pop(name, None)
            else:
                self.env[name] = saved

    def _note_caught(self, fault: ProgramFault) -> None:
        "被捕获的故障进回执 caught：既不静默吞掉，也不作废整段程序"
        if len(self._caught) >= 20:
            return
        self._caught.append(fault.payload())

    def _set_program_result(self, value: Any, *, line: int | None) -> None:
        "顶层 return 的值进入回执 result，只接受 JSON 可序列化值"
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            raise ProgramFault(
                "return 的值必须是 JSON 可序列化值（str/int/float/bool/None/list/dict）",
                code="runtime_error",
                line=line,
            ) from None
        self._program_result = value

    async def _assign(self, node: Any, value: Any) -> None:
        """变量、等长解包及字典下标赋值，拒绝循环引用"""
        if isinstance(node, ast.Name):
            if node.id in self.tools or node.id == "range" or node.id in BUILTIN_FUNCTION_NAMES:
                raise ProgramFault(
                    f"不允许覆盖工具名或基础函数名：{node.id}；请把变量改为 {node.id}_result，工具名须保留以便后续调用",
                    code="name_reserved",
                    line=getattr(node, "lineno", None),
                )
            if node.id.startswith("_") and node.id != "_":
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
            pending, visited = [value], set()
            while pending:
                await self._checkpoint()
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

    async def _aug_assign(self, node: Any) -> None:
        "增量赋值：读当前值按运算符求值，再写回同一变量或字典下标"
        line = getattr(node, "lineno", None)
        current = await self._value(node.target)
        operand = await self._value(node.value)
        await self._assign(node.target, self._binop(current, node.op, operand, line=line))

    async def _value(self, node: Any) -> Any:
        """用于对白名单表达式求值（常量/名称/容器/下标/一元负号/比较/具名工具调用）"""
        await self._checkpoint()
        line = getattr(node, "lineno", None)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (str, int, float, bool)) or node.value is None:
                return node.value
            raise ProgramFault(f"不支持的常量：{type(node.value).__name__}", code="unsupported_expression", line=line)
        if isinstance(node, ast.Name):
            return self._resolve_name(node.id, line=line)
        if isinstance(node, ast.List):
            return await self._container_values(node.elts, kind="list", line=line)
        if isinstance(node, ast.Tuple):
            return await self._container_values(node.elts, kind="tuple", line=line)
        if isinstance(node, ast.Set):
            return await self._container_values(node.elts, kind="set", line=line)
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
        if isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp)):
            return await self._comprehension(node, line=line)
        if isinstance(node, ast.Slice):
            lower = await self._value(node.lower) if node.lower is not None else None
            upper = await self._value(node.upper) if node.upper is not None else None
            step = await self._value(node.step) if node.step is not None else None
            if any(value is not None and type(value) is not int for value in (lower, upper, step)):
                raise ProgramFault("切片边界必须是整数", code="unsupported_expression", line=line)
            if step == 0:
                raise ProgramFault("切片步长不能为 0", code="runtime_error", line=line)
            return slice(lower, upper, step)
        if isinstance(node, ast.Subscript):
            value = await self._value(node.value)
            index = await self._value(node.slice)
            try:
                return value[index]
            except (KeyError, IndexError, TypeError) as exc:
                detail = f"{_expression_text(node)} 取值失败：{exc}"
                if isinstance(value, dict):
                    keys = "、".join(str(key) for key in value)[:300]
                    detail += f"；可用键：{keys}" if keys else "；该字典为空"
                elif isinstance(value, (list, tuple, str)):
                    detail += f"；{type(value).__name__} 只接受 0..{len(value) - 1} 的整数下标"
                else:
                    detail += f"；该值类型是 {type(value).__name__}，不能用下标取值"
                raise ProgramFault(f"下标不可用：{detail}", code="runtime_error", line=line) from None
        if isinstance(node, ast.BinOp):
            return self._binop(await self._value(node.left), node.op, await self._value(node.right), line=line)
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
        if isinstance(node, ast.Lambda):
            return self._lambda(node, line=line)
        if isinstance(node, ast.JoinedStr):
            return await self._joined_str(node, line=line)
        if isinstance(node, ast.FormattedValue):
            return await self._formatted_value(node, line=line)
        if isinstance(node, ast.Compare):
            return await self._compare(node, line=line)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return await self._call(node, line=line)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            return await self._method_call(node, line=line)
        raise ProgramFault(
            f"未支持的 Python 表达式：{type(node).__name__}",
            code="unsupported_expression",
            line=line,
        )

    async def _container_values(self, elts: list[Any], *, kind: str, line: int | None) -> Any:
        """列表、元组与集合求值，星号展开只接受列表、元组或集合"""
        result: list[Any] = []
        for item in elts:
            if isinstance(item, ast.Starred):
                spread = await self._value(item.value)
                if not isinstance(spread, (list, tuple, set)):
                    raise ProgramFault("* 展开只接受列表、元组或集合", code="runtime_error", line=line)
                result.extend(spread)
            else:
                result.append(await self._value(item))
        if kind == "tuple":
            return tuple(result)
        if kind == "set":
            try:
                return set(result)
            except TypeError:
                raise ProgramFault("集合元素必须可哈希", code="runtime_error", line=line) from None
        return result

    async def _comprehension(self, node: Any, *, line: int | None) -> Any:
        """列表与字典推导式，支持多个迭代器和条件"""
        produced: list[Any] = []
        mapping: dict[Any, Any] = {}
        saved = self._save_target_names([generator.target for generator in node.generators])
        try:

            async def walk(index: int) -> None:
                if index == len(node.generators):
                    await self._checkpoint()
                    if isinstance(node, ast.DictComp):
                        key = await self._value(node.key)
                        mapping[key] = await self._value(node.value)
                    else:
                        produced.append(await self._value(node.elt))
                    return
                generator = node.generators[index]
                values = await self._value(generator.iter)
                if isinstance(values, dict):
                    values = list(values)
                if not isinstance(values, (list, tuple, set)):
                    raise ProgramFault("推导式只能遍历列表、元组、集合或字典", code="unsupported_expression", line=line)
                for item in values:
                    await self._checkpoint()
                    await self._assign(generator.target, item)
                    conditions_ok = True
                    for condition in generator.ifs:
                        if not bool(await self._value(condition)):
                            conditions_ok = False
                            break
                    if conditions_ok:
                        await walk(index + 1)

            await walk(0)
        finally:
            self._restore_target_names(saved)
        if isinstance(node, ast.DictComp):
            return mapping
        if isinstance(node, ast.SetComp):
            try:
                return set(produced)
            except TypeError:
                raise ProgramFault("集合元素必须可哈希", code="runtime_error", line=line) from None
        return produced

    def _save_target_names(self, targets: list[Any]) -> dict[str, Any]:
        "推导式循环变量按 Python 语义不泄漏：保存进入前的值"
        names = {name for target in targets for name in self._target_names(target)}
        return {name: self.env.get(name, _ABSENT) for name in names}

    def _restore_target_names(self, saved: dict[str, Any]) -> None:
        "推导式结束后恢复循环变量，未定义过的变量直接删除"
        for name, value in saved.items():
            if value is _ABSENT:
                self.env.pop(name, None)
            else:
                self.env[name] = value

    def _target_names(self, target: Any) -> list[str]:
        "收集赋值目标里的变量名（含元组/列表解包）"
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            return [name for item in target.elts for name in self._target_names(item)]
        return []

    def _binop(self, left: Any, operator: Any, right: Any, *, line: int | None) -> Any:
        "二元运算：+ 拼接同类容器，* 重复序列，其余交给数字运算"
        if isinstance(operator, ast.Add):
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            if isinstance(left, list) and isinstance(right, list):
                return left + right
            if isinstance(left, tuple) and isinstance(right, tuple):
                return left + right
            if isinstance(left, (list, tuple)) or isinstance(right, (list, tuple)):
                raise ProgramFault("+ 不能把列表/元组与非同类容器相加", code="runtime_error", line=line)
        if isinstance(operator, ast.Mult):
            repeated = self._repeat_values(left, right, line=line)
            if repeated is not None:
                return repeated
        return self._number_op(left, operator, right, line=line)

    def _repeat_values(self, left: Any, right: Any, *, line: int | None) -> Any:
        "序列 × 整数的重复；不适用时返回 None，交给算术分支"
        if type(right) is int and isinstance(left, (str, list, tuple)):
            sequence, count = left, right
        elif type(left) is int and isinstance(right, (str, list, tuple)):
            sequence, count = right, left
        else:
            return None
        if count > 0 and len(sequence) * count > program_contract.PROGRAM_MAX_REPEAT_ITEMS:
            raise ProgramFault(
                f"重复后的项数超过 {program_contract.PROGRAM_MAX_REPEAT_ITEMS}",
                code="runtime_error",
                line=line,
            )
        return sequence * max(count, 0)

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
        """比较运算：==/!=/in/not in/</<=/>/>=/is/is not，支持链式（a < b < c）"""
        left = await self._value(node.left)
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            right = await self._value(comparator)
            if isinstance(operator, ast.Eq):
                ok = left == right
            elif isinstance(operator, ast.NotEq):
                ok = left != right
            elif isinstance(operator, (ast.In, ast.NotIn)):
                if not isinstance(right, (list, tuple, set, dict, str)):
                    raise ProgramFault("in 的右侧需要列表/元组/集合/字典/字符串", code="runtime_error", line=line)
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
        """用于在调用写法错时把该名字的真实用法回给模型（构造器签名或工具参数名）"""
        try:
            return self._signature_hint(name) if self._signature_hint is not None else f"{name}(...)"
        except (TypeError, ValueError):
            return f"{name}(...)"

    def _type_reference(self, node: Any, *, line: int | None) -> Any:
        """isinstance 第二个参数只接受类型名或其元组，不开放任意表达式求值"""
        if isinstance(node, ast.Name):
            target = _TYPE_NAMES.get(node.id)
            if target is not None:
                return target
        if isinstance(node, ast.Tuple):
            return tuple(self._type_reference(item, line=line) for item in node.elts)
        raise ProgramFault(
            "isinstance 的第二个参数只能用类型名（str/int/float/bool/list/dict/set/tuple）",
            code="bad_call",
            line=line,
        )

    async def _call(self, node: ast.Call, *, line: int | None) -> Any:
        """用于执行一次具名调用（名字属于工具、基础函数或 range；工具只收具名参数）"""
        function = node.func
        if not isinstance(function, ast.Name):
            raise ProgramFault(
                "只支持直接调用工具函数（不支持嵌套调用或下标调用）",
                code="unsupported_expression",
                line=line,
            )
        name = function.id
        if name in self._imported_names:
            module_name, attribute = self._imported_names[name]
            return await self._module_call(module_name, attribute, node, line=line)
        candidate = self.env.get(name, _ABSENT)
        if isinstance(candidate, _ProgramLambda):
            if node.keywords:
                raise ProgramFault("lambda 只接受位置参数", code="bad_call", line=line)
            return await candidate(*[await self._value(arg) for arg in node.args])
        if isinstance(candidate, _ProgramFunction):
            if node.keywords:
                raise ProgramFault("def 函数只接受位置参数", code="bad_call", line=line)
            return await self._invoke_function(candidate, [await self._value(arg) for arg in node.args], line=line)
        if name == "range":
            arguments = [await self._value(arg) for arg in node.args]
            if node.keywords or not 1 <= len(arguments) <= 3 or any(type(arg) is not int for arg in arguments):
                raise ProgramFault("range 只接受1至3个整数位置参数", code="bad_call", line=line)
            try:
                total = len(range(*arguments))
            except OverflowError:
                raise ProgramFault("range 项数无法表示", code="bad_call", line=line) from None
            except ValueError:
                raise ProgramFault("range 的步长不能为0", code="bad_call", line=line) from None
            if total > program_contract.PROGRAM_MAX_RANGE_ITEMS:
                raise ProgramFault(
                    f"range 项数超过 {program_contract.PROGRAM_MAX_RANGE_ITEMS}（当前 {total}）",
                    code="runtime_error",
                    line=line,
                )
            return list(range(*arguments))
        if name == "isinstance":
            if node.keywords or len(node.args) != 2:
                raise ProgramFault("isinstance 只接受 2 个位置参数", code="bad_call", line=line)
            return self._builtin(
                name,
                [await self._value(node.args[0]), self._type_reference(node.args[1], line=line)],
                line=line,
            )
        if name == "sorted":
            return await self._sorted_call(node, line=line)
        if name in {"min", "max"}:
            return await self._min_max_call(name, node, line=line)
        if name == "dict":
            return await self._dict_call(node, line=line)
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

    async def _module_call(self, module_name: str, attribute: str, node: ast.Call, *, line: int | None) -> Any:
        "调用白名单模块的放行属性；裸属性读仍不开放"
        allowed = program_contract.PROGRAM_MODULE_ATTRIBUTES.get(module_name, frozenset())
        if attribute not in allowed:
            raise ProgramFault(
                f"{module_name} 不开放 {attribute}；可调用的只有 {'、'.join(sorted(allowed))}",
                code="unsupported_expression",
                line=line,
            )
        arguments = [await self._value(arg) for arg in node.args]
        keywords: dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                raise ProgramFault("模块函数不接受 ** 展开", code="bad_call", line=line)
            keywords[keyword.arg] = await self._value(keyword.value)
        function = getattr(program_contract.PROGRAM_MODULES[module_name], attribute)
        try:
            return function(*arguments, **keywords)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ProgramFault(f"{module_name}.{attribute} 调用失败：{exc}", code="runtime_error", line=line) from None

    async def _dict_call(self, node: ast.Call, *, line: int | None) -> dict[Any, Any]:
        "dict(位置参数, **关键字)：关键字构造与 ** 展开都按具名键写入"
        arguments = [await self._value(arg) for arg in node.args]
        if len(arguments) > 1:
            raise ProgramFault("dict 最多接受 1 个位置参数", code="bad_call", line=line)
        result = self._builtin("dict", arguments, line=line)
        for keyword in node.keywords:
            if keyword.arg is None:
                expanded = await self._value(keyword.value)
                if not isinstance(expanded, dict) or any(not isinstance(key, str) for key in expanded):
                    raise ProgramFault("** 展开只接受以字符串为键的字典", code="bad_call", line=line)
                result.update(expanded)
            else:
                result[str(keyword.arg)] = await self._value(keyword.value)
        return result

    def _lambda(self, node: ast.Lambda, *, line: int | None) -> Any:
        """构造只含普通位置参数的 lambda；参数在调用时临时绑定到变量环境"""
        arguments = node.args
        if arguments.vararg or arguments.kwarg or arguments.kwonlyargs or arguments.defaults or arguments.kw_defaults:
            raise ProgramFault("lambda 只支持无默认值的普通位置参数", code="bad_call", line=line)
        names = [argument.arg for argument in (*arguments.posonlyargs, *arguments.args)]

        async def invoke(*values: Any) -> Any:
            if len(values) != len(names):
                raise ProgramFault(
                    f"lambda 需要 {len(names)} 个参数，实际 {len(values)} 个", code="bad_call", line=line
                )
            saved = {name: self.env.get(name, _ABSENT) for name in names}
            try:
                for name, value in zip(names, values, strict=True):
                    self.env[name] = value
                return await self._value(node.body)
            finally:
                for name, previous in saved.items():
                    if previous is _ABSENT:
                        self.env.pop(name, None)
                    else:
                        self.env[name] = previous

        return _ProgramLambda(invoke)

    async def _joined_str(self, node: ast.JoinedStr, *, line: int | None) -> str:
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                parts.append(await self._formatted_value(value, line=line))
            else:
                raise ProgramFault("f-string 片段不受支持", code="unsupported_expression", line=line)
        return "".join(parts)

    async def _formatted_value(self, node: ast.FormattedValue, *, line: int | None) -> str:
        value = await self._value(node.value)
        if node.conversion == ord("r"):
            rendered = repr(value)
        elif node.conversion == ord("a"):
            rendered = ascii(value)
        elif node.conversion in (-1, ord("s")):
            rendered = str(value)
        else:
            raise ProgramFault("f-string 转换符不受支持", code="unsupported_expression", line=line)
        if node.format_spec is not None:
            spec = await self._value(node.format_spec)
            if not isinstance(spec, str):
                raise ProgramFault("f-string 格式说明必须是字符串", code="bad_call", line=line)
            try:
                rendered = format(value, spec)
            except (TypeError, ValueError) as exc:
                raise ProgramFault(f"f-string 格式化失败：{exc}", code="runtime_error", line=line) from None
        return rendered

    async def _method_call(self, node: ast.Call, *, line: int | None) -> Any:
        """执行内置容器/字符串方法；接收者类型与实参在运行时逐项校验"""
        if not isinstance(node.func, ast.Attribute):
            raise ProgramFault(
                "不支持该属性调用：只允许内置容器与字符串的常用方法", code="unsupported_expression", line=line
            )
        method = node.func.attr
        receiver_node = node.func.value
        if isinstance(receiver_node, ast.Name):
            module_name = self._module_aliases.get(receiver_node.id)
            if module_name is not None:
                return await self._module_call(module_name, method, node, line=line)
        if method not in _METHOD_NAMES:
            raise ProgramFault(
                f"不支持对象方法 {method}：只允许内置容器与字符串的常用方法",
                code="unsupported_expression",
                line=line,
            )
        if node.keywords:
            raise ProgramFault(f"{method} 只接受位置参数", code="bad_call", line=line)
        receiver = await self._value(node.func.value)
        args = [await self._value(arg) for arg in node.args]

        def arity(minimum: int, maximum: int | None = None) -> None:
            upper = minimum if maximum is None else maximum
            if not minimum <= len(args) <= upper:
                raise ProgramFault(
                    f"{method} 参数个数应为 {minimum}" + (f"~{upper}" if upper != minimum else ""),
                    code="bad_call",
                    line=line,
                )

        def integer(value: Any, label: str) -> int:
            if type(value) is not int:
                raise ProgramFault(f"{method} 的{label}必须是整数", code="bad_call", line=line)
            return value

        def text(value: Any, label: str) -> str:
            if not isinstance(value, str):
                raise ProgramFault(f"{method} 的{label}必须是字符串", code="bad_call", line=line)
            return value

        def optional_text(value: Any, label: str) -> str | None:
            return None if value is None else text(value, label)

        if isinstance(receiver, dict):
            if method == "get":
                arity(1, 2)
                default = args[1] if len(args) == 2 else None
                try:
                    return receiver.get(args[0], default)
                except TypeError as exc:
                    raise ProgramFault(f"dict.get 键不可用：{exc}", code="runtime_error", line=line) from None
            if method in {"keys", "values", "items"}:
                arity(0)
                return list(getattr(receiver, method)())
            if method == "copy":
                arity(0)
                return dict(receiver)
            if method == "update":
                arity(1)
                other = args[0]
                if not isinstance(other, dict):
                    raise ProgramFault("dict.update 只接受字典", code="bad_call", line=line)
                receiver.update(other)
                return None
            if method == "pop":
                arity(1, 2)
                try:
                    return receiver.pop(args[0], *args[1:])
                except KeyError:
                    raise ProgramFault(f"dict.pop 键不存在：{args[0]}", code="runtime_error", line=line) from None
                except TypeError as exc:
                    raise ProgramFault(f"dict.pop 键不可用：{exc}", code="runtime_error", line=line) from None
            raise ProgramFault(f"字典不支持方法 {method}", code="unsupported_expression", line=line)

        if isinstance(receiver, list):
            if method == "append":
                arity(1)
                if args[0] is receiver:
                    raise ProgramFault("列表不能追加自身", code="runtime_error", line=line)
                receiver.append(args[0])
                return None
            if method == "extend":
                arity(1)
                other = args[0]
                if isinstance(other, dict):
                    other = list(other)
                if not isinstance(other, (list, tuple)):
                    raise ProgramFault("list.extend 只接受列表或元组", code="bad_call", line=line)
                if other is receiver:
                    raise ProgramFault("列表不能扩展自身", code="runtime_error", line=line)
                receiver.extend(other)
                return None
            if method == "insert":
                arity(2)
                integer(args[0], "索引")
                receiver.insert(args[0], args[1])
                return None
            if method == "remove":
                arity(1)
                try:
                    receiver.remove(args[0])
                except ValueError:
                    raise ProgramFault("list.remove 的值不在列表中", code="runtime_error", line=line) from None
                return None
            if method == "pop":
                arity(0, 1)
                index = integer(args[0], "索引") if args else -1
                try:
                    return receiver.pop(index)
                except IndexError:
                    raise ProgramFault("list.pop 索引越界", code="runtime_error", line=line) from None
            if method == "sort":
                arity(0)
                try:
                    receiver.sort()
                except TypeError as exc:
                    raise ProgramFault(f"list.sort 无法比较元素：{exc}", code="runtime_error", line=line) from None
                return None
            if method == "reverse":
                arity(0)
                receiver.reverse()
                return None
            if method == "index":
                arity(1, 3)
                try:
                    return receiver.index(*args)
                except ValueError:
                    raise ProgramFault("list.index 的值不在列表中", code="runtime_error", line=line) from None
            if method == "count":
                arity(1)
                return receiver.count(args[0])
            if method == "copy":
                arity(0)
                return list(receiver)
            raise ProgramFault(f"列表不支持方法 {method}", code="unsupported_expression", line=line)

        if isinstance(receiver, tuple):
            if method == "index":
                arity(1, 3)
                try:
                    return receiver.index(*args)
                except ValueError:
                    raise ProgramFault("tuple.index 的值不在元组中", code="runtime_error", line=line) from None
            if method == "count":
                arity(1)
                return receiver.count(args[0])
            raise ProgramFault(f"元组不支持方法 {method}", code="unsupported_expression", line=line)

        if isinstance(receiver, str):
            if method in {"split", "rsplit"}:
                arity(0, 2)
                separator = optional_text(args[0], "分隔符") if args else None
                maxsplit = integer(args[1], "最大拆分次数") if len(args) == 2 else -1
                return list(getattr(receiver, method)(separator, maxsplit))
            if method in {"strip", "lstrip", "rstrip"}:
                arity(0, 1)
                chars = optional_text(args[0], "字符集") if args else None
                return getattr(receiver, method)(chars)
            if method == "replace":
                arity(2, 3)
                old, new = text(args[0], "旧文本"), text(args[1], "新文本")
                count = integer(args[2], "替换次数") if len(args) == 3 else -1
                return receiver.replace(old, new, count)
            if method in {"startswith", "endswith"}:
                arity(1, 2)
                prefix = args[0]
                if not isinstance(prefix, (str, tuple)):
                    raise ProgramFault(f"{method} 的匹配项必须是字符串或字符串元组", code="bad_call", line=line)
                start = integer(args[1], "起点") if len(args) == 2 else 0
                return getattr(receiver, method)(prefix, start)
            if method in {"find", "rfind", "index"}:
                arity(1, 3)
                sub = text(args[0], "子串")
                start = integer(args[1], "起点") if len(args) >= 2 else 0
                end = integer(args[2], "终点") if len(args) == 3 else len(receiver)
                try:
                    return getattr(receiver, method)(sub, start, end)
                except ValueError:
                    raise ProgramFault(f"str.{method} 的子串不在原文中", code="runtime_error", line=line) from None
            if method == "join":
                arity(1)
                values = args[0]
                if not isinstance(values, (list, tuple)) or any(not isinstance(item, str) for item in values):
                    raise ProgramFault("str.join 只接受字符串列表或元组", code="bad_call", line=line)
                return receiver.join(values)
            if method == "count":
                arity(1, 3)
                sub = text(args[0], "子串")
                start = integer(args[1], "起点") if len(args) >= 2 else 0
                end = integer(args[2], "终点") if len(args) == 3 else len(receiver)
                return receiver.count(sub, start, end)
            if method in {"lower", "upper", "casefold", "title", "capitalize", "isdigit", "isalpha", "isspace"}:
                arity(0)
                return getattr(receiver, method)()
            raise ProgramFault(f"字符串不支持方法 {method}", code="unsupported_expression", line=line)

        raise ProgramFault(
            f"{method} 不能用于 {type(receiver).__name__}；只允许内置容器与字符串方法",
            code="runtime_error",
            line=line,
        )

    async def _keyword_values(
        self, node: ast.Call, allowed: set[str], *, caller: str, line: int | None
    ) -> dict[str, Any]:
        "读取基础函数的关键字参数；只接受声明过的名字"
        values: dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg is None or keyword.arg not in allowed:
                raise ProgramFault(f"{caller} 的关键字只接受 {'、'.join(sorted(allowed))}", code="bad_call", line=line)
            if keyword.arg in values:
                raise ProgramFault(f"{caller} 的关键字重复：{keyword.arg}", code="bad_call", line=line)
            values[keyword.arg] = await self._value(keyword.value)
        return values

    async def _sorted_call(self, node: ast.Call, *, line: int | None) -> list[Any]:
        "sorted(可迭代对象, key=lambda 或 def 函数, reverse=bool)"
        arguments = [await self._value(arg) for arg in node.args]
        if len(arguments) != 1 or not isinstance(arguments[0], (list, tuple, set)):
            raise ProgramFault("sorted 只接受一个列表、元组或集合", code="bad_call", line=line)
        keywords = await self._keyword_values(node, {"key", "reverse"}, caller="sorted", line=line)
        key = keywords.get("key")
        if key is not None and not isinstance(key, (_ProgramLambda, _ProgramFunction)):
            raise ProgramFault("sorted 的 key 只接受 lambda 或程序内 def 函数", code="bad_call", line=line)
        reverse = keywords.get("reverse", False)
        if type(reverse) is not bool:
            raise ProgramFault("sorted 的 reverse 必须是布尔值", code="bad_call", line=line)
        items = list(arguments[0])
        try:
            if key is None:
                return sorted(items, reverse=reverse)
            decorated = []
            for item in items:
                await self._checkpoint()
                decorated.append((await self._invoke_key(key, item, line=line), item))
            decorated.sort(key=lambda pair: pair[0], reverse=reverse)
            return [item for _, item in decorated]
        except TypeError:
            raise ProgramFault("sorted 的元素类型不一致，无法排序", code="runtime_error", line=line) from None

    async def _min_max_call(self, name: str, node: ast.Call, *, line: int | None) -> Any:
        "min/max(可迭代对象或多项, key=lambda 或 def 函数)"
        arguments = [await self._value(arg) for arg in node.args]
        keywords = await self._keyword_values(node, {"key"}, caller=name, line=line)
        key = keywords.get("key")
        if key is not None and not isinstance(key, (_ProgramLambda, _ProgramFunction)):
            raise ProgramFault(f"{name} 的 key 只接受 lambda 或程序内 def 函数", code="bad_call", line=line)
        if len(arguments) == 1 and isinstance(arguments[0], (list, tuple, set)):
            items = list(arguments[0])
        elif len(arguments) >= 2:
            items = arguments
        else:
            raise ProgramFault(f"{name} 需要多个参数或一个列表", code="bad_call", line=line)
        if not items:
            raise ProgramFault(f"{name} 不能用于空序列", code="runtime_error", line=line)
        try:
            if key is None:
                return min(items) if name == "min" else max(items)
            best = items[0]
            best_key = await self._invoke_key(key, best, line=line)
            for item in items[1:]:
                await self._checkpoint()
                current = await self._invoke_key(key, item, line=line)
                better = current < best_key if name == "min" else current > best_key
                if better:
                    best, best_key = item, current
            return best
        except TypeError:
            raise ProgramFault(f"{name} 的元素类型不一致，无法比较", code="runtime_error", line=line) from None

    async def _invoke_key(self, key: Any, item: Any, *, line: int | None) -> Any:
        "排序键既可以是 lambda，也可以是程序内 def 函数"
        if isinstance(key, _ProgramLambda):
            return await key(item)
        return await self._invoke_function(key, [item], line=line)

    def _builtin(self, name: str, values: list[Any], *, line: int | None) -> Any:
        """基础函数的只读纯函数实现（只接受位置参数）"""
        if name in {"list", "tuple"}:
            if len(values) > 1:
                raise ProgramFault(f"{name} 最多接受 1 个参数", code="bad_call", line=line)
            target = values[0] if values else []
            if isinstance(target, dict):
                target = list(target)
            elif isinstance(target, str):
                target = list(target)
            elif isinstance(target, (list, tuple, set)):
                target = list(target)
            else:
                raise ProgramFault(f"{name} 只接受列表/元组/集合/字典/字符串", code="runtime_error", line=line)
            return target if name == "list" else tuple(target)
        if name == "set":
            if len(values) > 1:
                raise ProgramFault("set 最多接受 1 个参数", code="bad_call", line=line)
            if not values:
                return set()
            target = values[0]
            if isinstance(target, (list, tuple, set, dict, str)):
                try:
                    return set(target)
                except TypeError:
                    raise ProgramFault("set 的元素必须可哈希", code="runtime_error", line=line) from None
            raise ProgramFault("set 只接受列表/元组/集合/字典/字符串", code="runtime_error", line=line)
        if name == "dict":
            if len(values) > 1:
                raise ProgramFault("dict 最多接受 1 个参数", code="bad_call", line=line)
            if not values:
                return {}
            target = values[0]
            if isinstance(target, dict):
                result = dict(target)
            elif isinstance(target, (list, tuple)):
                try:
                    result = dict(target)
                except (TypeError, ValueError):
                    raise ProgramFault("dict 只接受键值对序列", code="runtime_error", line=line) from None
            else:
                raise ProgramFault("dict 只接受字典或键值对序列", code="runtime_error", line=line)
            return result
        if name == "zip":
            if any(not isinstance(item, (list, tuple, set)) for item in values):
                raise ProgramFault("zip 只接受列表、元组或集合", code="bad_call", line=line)
            zipped = list(zip(*values, strict=False))
            return zipped
        if name == "reversed":
            if len(values) != 1 or not isinstance(values[0], (list, tuple, str, dict)):
                raise ProgramFault("reversed 只接受列表/元组/字符串/字典", code="bad_call", line=line)
            reversed_values = list(reversed(values[0]))
            return reversed_values
        if name == "format":
            if not 1 <= len(values) <= 2:
                raise ProgramFault("format 接受一个值和一个可选格式说明", code="bad_call", line=line)
            spec = values[1] if len(values) == 2 else ""
            if not isinstance(spec, str):
                raise ProgramFault("format 的格式说明必须是字符串", code="bad_call", line=line)
            try:
                return format(values[0], spec)
            except (TypeError, ValueError) as exc:
                raise ProgramFault(f"format 失败：{exc}", code="runtime_error", line=line) from None
        if name == "len":
            if not isinstance(values, list) or len(values) != 1:
                raise ProgramFault("len 需要 1 个参数", code="bad_call", line=line)
            target = values[0]
            if not isinstance(target, (list, tuple, set, dict, str)):
                raise ProgramFault("len 只接受列表/元组/集合/字典/字符串", code="runtime_error", line=line)
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
        if name == "abs":
            if len(values) != 1 or type(values[0]) not in (int, float):
                raise ProgramFault("abs 只接受 1 个数字", code="runtime_error", line=line)
            return abs(values[0])
        if name == "sum":
            if len(values) != 1 or not isinstance(values[0], (list, tuple, set)):
                raise ProgramFault("sum 只接受一个列表、元组或集合", code="bad_call", line=line)
            try:
                return sum(values[0])
            except TypeError:
                raise ProgramFault("sum 的元素必须是数字", code="runtime_error", line=line) from None
        if name == "enumerate":
            if not 1 <= len(values) <= 2 or not isinstance(values[0], (list, tuple, set)):
                raise ProgramFault("enumerate 接受一个列表/元组/集合与可选起始值", code="bad_call", line=line)
            start = values[1] if len(values) == 2 else 0
            if len(values) == 2 and type(start) is not int:
                raise ProgramFault("enumerate 的起始值必须是整数", code="bad_call", line=line)
            return list(enumerate(values[0], start))
        if name == "isinstance":
            if len(values) != 2:
                raise ProgramFault("isinstance 只接受 2 个位置参数", code="bad_call", line=line)
            try:
                return isinstance(values[0], values[1])
            except TypeError:
                raise ProgramFault("isinstance 的类型参数不合法", code="bad_call", line=line) from None
        if name in {"any", "all"}:
            if len(values) != 1 or not isinstance(values[0], (list, tuple, set)):
                raise ProgramFault(f"{name} 只接受一个列表、元组或集合", code="bad_call", line=line)
            return any(values[0]) if name == "any" else all(values[0])
        if name == "round":
            if not 1 <= len(values) <= 2 or type(values[0]) not in (int, float):
                raise ProgramFault("round 接受一个数字和可选整数位数", code="bad_call", line=line)
            if len(values) == 2 and type(values[1]) is not int:
                raise ProgramFault("round 的位数必须是整数", code="bad_call", line=line)
            return round(*values)
        if name == "repr":
            if len(values) != 1:
                raise ProgramFault("repr 需要 1 个参数", code="bad_call", line=line)
            return repr(values[0])[:2000]
        if name == "print":
            rendered = " ".join(str(value) for value in values)
            if len(rendered) > program_contract.PROGRAM_PRINT_MAX_CHARS:
                rendered = (
                    f"{rendered[: program_contract.PROGRAM_PRINT_MAX_CHARS]}"
                    f"…[print 输出截断：原文共 {len(rendered)} 字符]"
                )
            self.printed.append(rendered)
            if len(self.printed) > 50:
                del self.printed[:-50]
            return None
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
                "receipt": {key: body[key] for key in ("record", "ref", "warnings") if key in body},
                "record": body.get("record")
                or (self._record_key(name, dict(call_args or {})) if self._record_key is not None else None),
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
        """用于把一次成功的检索读结果挂进回执 reads（内容不截断，只留最近若干条）"""
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
        """在解释器检查点核对本次程序期限"""
        self._schedule_ticks += 1
        if time.monotonic() > self._deadline:
            raise ProgramFault(
                f"单次程序执行超过 {int(program_contract.PROGRAM_DEADLINE_S)} 秒执行期限",
                code="deadline_exceeded",
            )

    async def _checkpoint(self) -> None:
        """定期让出事件循环，期限和取消在检查点生效"""
        self._guard()
        if self._schedule_ticks >= self._next_yield:
            self._next_yield = self._schedule_ticks + 256
            await asyncio.sleep(0)
            self._guard()
