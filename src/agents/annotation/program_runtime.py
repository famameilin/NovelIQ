"""
程序面运行时：受限 AST 解释器基座与写者面程序运行时
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：program.py 大文件拆分——两个 runtime（RestrictedProgramRuntime/ProgramRuntime）
# 迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑与签名；限额常量与 _ProgramFault 保留在 program.py、
# 目录渲染与合同文案在 catalog.py、检索投影在 search_projection.py，均由本模块引用；
# program.py 对两个 runtime 保留 re-export，既有导入方零改动。

from __future__ import annotations

import ast
import json
import time
from typing import Any

# 限额常量经 program 模块属性读取（而非值拷贝）：tests 以 KEEP_*") 调整安全护栏，属性访问保持这一注入缝隙逐字生效。
from . import program as _program
from .catalog import PROGRAM_CONTRACT_TEXT, call_parameters
from .program import _ProgramFault, render_list_signature
from .search_projection import _failed_view, build_program_tools
from .tool_batch import _execute_call
from .tools import FINISH_TOOL_NAME, tool_record_key


class RestrictedProgramRuntime:
    """2026-09-16 受限 AST 解释器基座：程序面共用同一份"程序怎么跑"

    分工：本基类只管解释器语义（节点白名单、变量环境、步数/墙钟/条数硬限、逐 op
    记录与压缩回执）；"一次调用发生什么"由子类实现 _dispatch——正式与连续性工具面
    （ProgramRuntime）在它之上做构造器的写入生效。
    这样两边共用同一份语法边界与回执口径，谁也不复制业务校验。
    """

    # 工具目录从当前信封的实际工具表生成
    contract_text: str = ""

    def __init__(
        self,
        tool_list: list[Any],
        namespace: dict[str, Any],
        *,
        observer: Any = None,
        stream: Any = None,
    ) -> None:
        """以同一工具表生成目录并分发调用，不保留构造器编译路径"""
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
        self._deadline = time.monotonic() + _program._PROGRAM_DEADLINE_S
        self._reset_program_state()
        error: dict[str, Any] | None = None
        status = "applied"
        try:
            await self._statements(self._parse(code))
        except _ProgramFault as fault:
            error = fault.payload()
            status = "rejected" if fault.code in _program._PRE_RUN_FAULT_CODES else "runtime_error"
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
        if len(code) > _program._PROGRAM_MAX_CODE_CHARS:
            raise _ProgramFault(
                f"程序超过 {_program._PROGRAM_MAX_CODE_CHARS} 字符（当前 {len(code)}）",
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
        if len(values) > _program._PROGRAM_MAX_LOOP_ITEMS:
            raise _ProgramFault(
                f"for 的迭代项超过 {_program._PROGRAM_MAX_LOOP_ITEMS} 条（当前 {len(values)}）",
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
        if key in _program._PROGRAM_NAME_CONSTANTS:
            return _program._PROGRAM_NAME_CONSTANTS[key]
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
        if self._ops_in_program >= _program._PROGRAM_MAX_OPS:
            raise _ProgramFault(
                f"单个程序的内层操作超过 {_program._PROGRAM_MAX_OPS} 条",
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
                "record": body.get("record") or tool_record_key(name, dict(call_args or {})),
                "error_code": body.get("code"),
                "field": body.get("field"),
                "expected": body.get("expected"),
                "message": body.get("message") or body.get("error") or error,
                "direct_fallback": direct_fallback,
            }
        )
        if status == "success" and name in _program._READ_TOOL_NAMES:
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
        if len(text) > _program._READ_ECHO_MAX_CHARS:
            item["result"] = text[:_program._READ_ECHO_MAX_CHARS]
            item["truncated_chars"] = len(text)
        else:
            item["result"] = text
        self.reads.append(item)
        if len(self.reads) > _program._READ_ECHO_MAX_ITEMS:
            dropped = len(self.reads) - _program._READ_ECHO_MAX_ITEMS
            self.reads = self.reads[-_program._READ_ECHO_MAX_ITEMS:]
            self.reads.insert(0, {"note": f"更早的 {dropped} 条读结果已省略（要重看就再检索一次）"})

    def _guard(self) -> None:
        """用于在每条语句/表达式前检查步数与墙钟硬限"""
        self._steps += 1
        if self._steps > _program._PROGRAM_MAX_STEPS:
            raise _ProgramFault(
                f"单次程序执行步数超过 {_program._PROGRAM_MAX_STEPS}（疑似循环过大）",
                code="too_many_steps",
            )
        if time.monotonic() > self._deadline:
            raise _ProgramFault(
                f"单次程序执行超过 {int(_program._PROGRAM_DEADLINE_S)} 秒硬限",
                code="deadline_exceeded",
            )


class ProgramRuntime(RestrictedProgramRuntime):
    """2026-09-15 写者面程序运行时：受限解释器里逐条复用生产单条事务边界

    2026-09-19 随 agent 路径恢复：单块章的模型可见面=[execute_code, finish]，程序内直接
    调用正式工具（检索+写入+finish）；每条内层调用都走 graph._execute_call，与
    正式与连续性工具面共用同一份"快照 → 调用 → 按条回滚 → 审计"实现。
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
            tool_map=self.tools,
            ledger=self.ledger,
            observer=self.observer,
            stream=self.stream,
            call_index=self._next_call_index(),
            # 2026-09-20 写者面也要登记本章已写出的记录键：案例工具（push_case.record_id /
            # promise_case.result_id）按 ledger.written_record_keys 校验，这条路此前没登记
            # （原生批次与 正式与连续性工具面都登记了），于是写者面每次引用自己刚写的记录都被
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
            tool_map=self.tools,
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
