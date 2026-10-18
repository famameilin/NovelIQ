"""
章内 agent 程序运行时：八类构造器 + 检索/案例 + 收尾的执行面
"""

# ruff: noqa: E402 —— 文件末尾的 re-export 导入为有意的延迟导入。

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.agents.annotation.catalog import (
    AGENT_CONTRACT_TEXT,
    call_parameters,
    constructor_call_entries,
    render_list_signature,
)
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.program import build_program_tool
from src.agents.annotation.program_runtime import RestrictedProgramRuntime
from src.agents.annotation.search_projection import _call_rejection, build_program_tools
from src.agents.annotation.tools import FINISH_TOOL_NAME

from .agent_constructors import (
    _ConstructorCall,
    _receipt_message,
    _refused_receipt,
    _sync_entity_ref,
    _tool_receipt,
    _written_receipt,
    build_agent_constructors,
)
from .agent_ir import AgentAnnotation
from .errors import AnnotationDependencyError, AnnotationInvariantError
from .tool_batch import _execute_call


class AgentProgramRuntime(RestrictedProgramRuntime):
    """一个 agent 的程序面：八类构造器 + 检索/案例 + 收尾（绑定面只有 execute_code 与 finish）

    生命周期：一个 agent 建一次、跨回合复用（变量与逐 op 记录随之保留）。
    程序目录三个 agent 完全相同（AGENT_TOOL_NAMES + finish），域分工只写在职责文案里。
    """

    contract_text = AGENT_CONTRACT_TEXT

    def __init__(
        self,
        tool_map: dict[str, Any],
        ledger: AnnotationToolLedger,
        agent: AgentAnnotation,
        *,
        write_lock: asyncio.Lock | None = None,
        observer: Any = None,
        stream: Any = None,
    ) -> None:
        """用于绑定共享章级账本、生产工具表与本 agent 的产出记录

        模型可见面（绑定面）= [execute_code, finish]；execute_code 的程序目录 =
        AGENT_TOOL_NAMES（检索/案例）+ 八类构造器 + finish。执行面（execution_tools）
        是完整生产工具表——构造器编译出的那笔写入要经它落地，而正式写入工具不在模型可见面。

        write_lock：三个 agent 共享一个章级账本与一张事实图，账本快照/按条回滚
        与图写入都假定串行，所以内层调用按锁执行（模型生成期间不占锁）。
        """
        paragraph_info = ledger.paragraph_info
        if paragraph_info is None:
            raise AnnotationInvariantError("agent 程序面需要段落坐标映射，paragraph_info 缺失")
        paragraph_text_by_id = paragraph_info.text_by_visible_id()
        candidate_total = len(ledger.dialogue_candidates)
        entries = build_agent_constructors(
            agent,
            paragraph_text_by_id=paragraph_text_by_id,
            candidate_total=candidate_total,
        )
        if ledger.finish_work is None:
            raise AnnotationInvariantError("work 收尾校验未装配，不能启动程序面")
        self.finish_tool = tool_map[FINISH_TOOL_NAME]
        program_tools = build_program_tools(list(tool_map.values()))
        by_name = {str(tool.name): tool for tool in program_tools}
        # 可见面按 AGENT_TOOL_NAMES 的顺序取（那是模型目录的排列依据），不跟随工具表顺序
        visible_tools = [by_name[name] for name in AGENT_TOOL_NAMES if name in by_name]
        visible_tools.extend(
            by_name[name]
            for name in (
                "promise_case",
                "search_cases",
                "search_events",
                "search_graph",
                "read_event",
                "read_entity",
            )
            if name in by_name
        )
        namespace: dict[str, Any] = {str(tool.name): tool for tool in [*visible_tools, self.finish_tool]}
        namespace.update({name: function for name, function, _ in entries})
        super().__init__(
            [*visible_tools, self.finish_tool],
            namespace,
            observer=observer,
            stream=stream,
        )
        # 执行面是完整生产工具表——构造器编译出的那笔写入要经它落地，而正式写入工具不在
        # 模型可见面。
        self.execution_tools = {
            **{str(tool.name): tool for tool in program_tools},
            # 生产面也有一个同名 finish（章级收尾），本面必须用自己的那个
            FINISH_TOOL_NAME: self.finish_tool,
        }
        self.ledger = ledger
        self.agent = agent
        self.api_entries = entries
        self._constructor_names = frozenset(name for name, _, _ in entries)
        self._paragraph_text_by_id = paragraph_text_by_id
        self._write_lock = write_lock if write_lock is not None else asyncio.Lock()
        self._caseid_default: Any = None

    async def execute(self, code: str, caseid: Any = None) -> str:
        """程序显式默认关联只在本次执行有效，内层传 None 可取消"""
        self._caseid_default = caseid
        try:
            return await super().execute(code)
        finally:
            self._caseid_default = None

    def build_tool(self) -> Any:
        """用于构造 agent 的对外程序入口 execute_code（构造器与检索/案例/finish 同一份目录）"""
        return build_program_tool(
            self,
            extra_api=_AGENT_REFERENCE_SCOPE_TEXT,
            call_entries=[
                (name, [*params, ("caseid", "Any = None")], description)
                for name, params, description in constructor_call_entries(self.api_entries)
            ],
        )

    def _progress(self) -> dict[str, int]:
        """用于回执 progress（本 agent 已构造的记录计数）"""
        return self.agent.counts()

    def _receipt(
        self,
        *,
        status: str,
        applied: int,
        failed: list[dict[str, Any]],
        error: dict[str, Any] | None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """只回报本次程序的显式收尾，避免上一轮 finish 触发提前结束"""
        body = super()._receipt(status=status, applied=applied, failed=failed, error=error, note=note)
        receipts = [
            op.get("receipt") for op in self.ops if op["program_id"] == self._program_id and op["status"] == "success"
        ]
        body["written_refs"] = [
            {"record": item.get("record"), "ref": item["ref"]}
            for item in receipts
            if isinstance(item, dict) and item.get("ref")
        ]
        warnings = [warning for item in receipts if isinstance(item, dict) for warning in item.get("warnings", [])]
        if warnings:
            body["warnings"] = warnings
        if any(
            op["program_id"] == self._program_id and op["tool_name"] == FINISH_TOOL_NAME and op["status"] == "success"
            for op in self.ops
        ):
            body["finish"] = {"end_requested": True}
        return body

    async def _dispatch(self, name: str, args: dict[str, Any], *, line: int | None) -> Any:
        """用于执行程序里的一次调用（构造器与工具同一条路径、同一套回执与审计）

        每个名字走同样的步骤：寻址换算 → （构造器）当场校验成待写记录 → 经生产单条事务
        边界执行 → 落产出记录 → 收尾（op 记录 + 审计行各写一次）。回执只有三种：
        写成了 {status:"written", record, ref}、读到了数据本身（检索）、被拒
        {status:"rejected", record, field, code, expected, message}——不因为"这次调的是
        构造器还是工具"而换一套形状。
        """
        op_index = self._next_op_index(line=line)
        started_ns = time.perf_counter_ns()
        if self.ledger.chapter_finished:
            from .errors import AnnotationProtocolError

            error = AnnotationProtocolError(f"执行 {self.ledger.invocation_id} 已 finish，拒绝迟到调用={name}")
            return self._finish_call(
                name,
                op_index=op_index,
                line=line,
                status="error",
                receipt=_call_rejection(name, error, signature_hint=self._signature_hint(name)),
                call_args=dict(args),
                error=str(error),
                started_ns=started_ns,
            )
        # 模型写的那一次调用：op 记录与审计行都记它，执行用构造器编译出的生产入参
        call_args = dict(args)
        business_args = dict(call_args)
        caseid = business_args.pop("caseid", self._caseid_default)
        plan: _ConstructorCall | None = None
        if name in self._constructor_names:
            try:
                plan = self.tools[name](**business_args)
            except AnnotationInvariantError:
                self._close_turn()
                raise
            except Exception as exc:
                return self._finish_call(
                    name,
                    op_index=op_index,
                    line=line,
                    status="error",
                    receipt=_call_rejection(name, exc, signature_hint=self._signature_hint(name)),
                    call_args=call_args,
                    error=str(exc),
                    started_ns=started_ns,
                )
        target = name if plan is None else plan.tool
        exec_args = dict(business_args if plan is None else plan.args)
        if caseid is not None or "caseid" in call_args:
            exec_args["caseid"] = caseid
        if plan is not None and target is None:
            # 只落产出记录的构造器（label）：标签与章级指标同属一个域，单独一条写不出去
            plan.commit()
            self.ledger.written_record_keys.add(plan.record)
            receipt: Any = _written_receipt(plan.record, plan.ref)
            if caseid is not None:
                warning = {
                    "status": "warning",
                    "code": "case_no_independent_artifact",
                    "caseid": caseid,
                    "message": "label 随章级指标保存；请在 metric 写入时显式传 caseid 关联",
                }
                receipt.update(case_link=warning, warnings=[warning])
            return self._finish_call(
                name,
                op_index=op_index,
                line=line,
                status="success",
                receipt=receipt,
                call_args=call_args,
                error=None,
                started_ns=started_ns,
            )
        try:
            async with self._write_lock:
                identity = f"{self.ledger.invocation_id}-" if self.ledger.invocation_id else ""
                entry = await _execute_call(
                    {
                        "name": target,
                        "args": exec_args,
                        # call_id 是业务事实的全局唯一实际地址：graph_facts/case_entries 的
                        # business_call_id 唯一键按执行身份限定，只用程序内序号会跨执行撞键
                        "id": f"{identity}{self._program_id}-op{op_index}",
                    },
                    tool_map=self.execution_tools,
                    ledger=self.ledger,
                    # 审计行由本面的 _record_audit 统一写（构造器名=模型这一次动作），
                    # 内层写入不另开审计行：一个调用一行，两个面同一份字段。
                    observer=None,
                    stream=self.stream,
                    call_index=self._next_call_index(),
                    record_keys=self.ledger.written_record_keys,
                )
        except AnnotationDependencyError as exc:
            # 内层调用不写审计，程序面必须记录失败的检索及源码行后再上抛
            self._finish_call(
                name,
                op_index=op_index,
                line=line,
                status="error",
                receipt={"status": "error", "code": "dependency_unavailable", "message": str(exc)},
                call_args=call_args,
                error=str(exc),
                started_ns=started_ns,
            )
            # 外层 execute_code 仍需写自己的失败审计，回合由外层最后闭合
            raise
        except AnnotationInvariantError:
            self._close_turn()
            raise
        ok = str(entry.get("status") or "error") == "success"
        if ok and plan is not None:
            plan.commit()
            # 构造器记录键与底层写入记录共同授权本次原文锚点
            self.ledger.written_record_keys.add(plan.record)
        if not ok:
            receipt = _refused_receipt(name, None if plan is None else plan.record, entry.get("receipt"))
        elif plan is None:
            receipt = _tool_receipt(name, entry.get("receipt"))
        else:
            _sync_entity_ref(plan.ref, entry.get("receipt"))
            if plan.tool == "push_case" and isinstance(entry.get("receipt"), dict):
                plan.ref.update(
                    {key: entry["receipt"][key] for key in ("case_id", "description") if key in entry["receipt"]}
                )
            receipt = _written_receipt(plan.record, plan.ref)
            actual = entry.get("receipt")
            if isinstance(actual, dict):
                for key in ("case_link", "warnings"):
                    if key in actual:
                        receipt[key] = actual[key]
                content = actual.get("content") or {}
                if plan.tool == "write_event" and content.get("declaration_id"):
                    receipt["ref"].update(declaration_id=content["declaration_id"])
        return self._finish_call(
            name,
            op_index=op_index,
            line=line,
            status="success" if ok else "error",
            receipt=receipt,
            call_args=call_args,
            error=None if ok else str(entry.get("error") or _receipt_message(receipt) or "调用被拒"),
            started_ns=started_ns,
        )

    def _finish_call(
        self,
        name: str,
        *,
        op_index: int,
        line: int | None,
        status: str,
        receipt: Any,
        call_args: dict[str, Any],
        error: str | None,
        started_ns: int,
    ) -> Any:
        """用于一次调用的收尾：逐 op 记录与审计行各写一次（构造器与工具共用同一份实现）"""
        self._log_op(
            name,
            op_index=op_index,
            line=line,
            status=status,
            receipt=receipt,
            call_args=call_args,
            error=error,
        )
        self._record_audit(
            name,
            args=call_args,
            receipt=receipt,
            status=status,
            error=error,
            started_ns=started_ns,
            op_index=op_index,
            line=line,
        )
        return receipt

    def _close_turn(self) -> None:
        """用于合同违反时先闭合回合审计计时（否则 agent_turns 的耗时字段留空）"""
        observer = self.observer
        if observer is not None:
            observer.close_turn()

    def _signature_hint(self, name: str) -> str:
        """用于在参数名写错时把构造器签名原样回给模型（自纠不需要猜）"""
        for entry_name, function, _ in self.api_entries:
            if entry_name == name:
                return render_list_signature(name, call_parameters(name, function))
        return name

    def _record_audit(
        self,
        name: str,
        *,
        args: dict[str, Any],
        receipt: Any,
        status: str,
        error: str | None,
        started_ns: int,
        op_index: int,
        line: int | None,
    ) -> None:
        """用于把一个调用写进 agent_tool_calls（构造器与工具同一份字段）

        记录键与错误码取自回执（生产拒绝的 code、构造器校验的 code 或工具的载荷），
        source_line 来自模型程序里的源码行——构造器与工具都有，质量统计按
        (tool_name, error_code) 分桶。检索类回执就是数据本身（数组/对象），取字段前先按
        对象判形态。
        """
        if self.observer is None:
            return
        body: dict[str, Any] = receipt if isinstance(receipt, dict) else {}
        request_args = dict(args)
        request_args["_program"] = {
            "program_id": self._program_id,
            "op_index": op_index,
            "source_line": line,
            "record": body.get("record"),
            "direct_fallback": False,
        }
        if body.get("code"):
            request_args["_program"]["error_code"] = body["code"]
        self.observer.record_tool_call(
            call_index=self._next_call_index(),
            tool_name=name,
            request_args=request_args,
            raw_args=None,
            response=receipt,
            receipt=receipt,
            status=status,
            error=error,
            tool_duration_ms=max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000)),
            started_ns=started_ns,
        )


# 工具面常量置于文件末尾引用：两个方向的首次导入都安全（双方定义先于引用）。
from .agent_program import _AGENT_REFERENCE_SCOPE_TEXT, AGENT_TOOL_NAMES  # noqa: E402
