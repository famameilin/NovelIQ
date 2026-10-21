"""诊断程序面：复用受限解释器，逐操作执行原工具，不复制业务校验"""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.tools import StructuredTool

from src.agents.annotation.errors import AnnotationAuthorizationError, AnnotationDependencyError, AnnotationInputError
from src.agents.annotation.program_contract import PROGRAM_TOOL_NAME
from src.agents.annotation.program_runtime import RestrictedProgramRuntime
from src.agents.annotation.tool_batch import _invoke_tool

from .tools import WRITE_NAMES

_INPUT_ERRORS = (ValueError, AnnotationInputError, AnnotationAuthorizationError)


def bind_finish_ledger(finish_tool: Any, ledger: Any) -> Any:
    """通用 finish 只返回回执；诊断会话按标注三节点族运行时在批结算前登记结束请求

    会话图复用 annotation 的 route/check 节点，结束信号读 ledger.end_requested：
    程序面与原生 finish 共用同一工具对象，包一层让两条路径都登记，不改变工具回执与审计。
    finish 是共享工具的同步实现（coroutine=None），同步/异步两条路径分置包装。
    """
    if finish_tool.coroutine is not None:
        original = finish_tool.coroutine

        async def request_end_async(*args: Any, **kwargs: Any) -> Any:
            ledger.end_requested = True
            return await original(*args, **kwargs)

        finish_tool.coroutine = request_end_async
        return finish_tool

    original = finish_tool.func

    def request_end(*args: Any, **kwargs: Any) -> Any:
        ledger.end_requested = True
        return original(*args, **kwargs)

    finish_tool.func = request_end
    return finish_tool


class DiagnosisProgramDependencyError(AnnotationDependencyError):
    """程序运行依赖故障，记录审计后终止任务，不交给模型修正"""


class DiagnosisProgramRuntime(RestrictedProgramRuntime):
    """一个诊断执行复用一份变量环境；所有写入仍由原诊断工具维护内存草稿"""

    contract_text = (
        "使用 execute_code(code=...) 提交受限 Python 程序。只支持赋值与等长解包、具名工具调用（可 ** 展开）、"
        "列表/字典/元组（含 * 与 ** 解包）、列表/字典推导式、"
        "下标与切片、字典下标赋值、算术与比较、and/or/not、条件表达式、f-string、"
        "无默认值位置参数的 lambda 与 def（可 return）、有界 for 和 if；"
        "range(stop)/range(start,stop,step) 与基础函数（len/str/int/float/bool/min/max/abs/sum/sorted/enumerate/"
        "isinstance/any/all/round/repr/print/list/dict/tuple/zip/reversed/format）"
        "只接受位置参数，最多500项；sorted 另接受 key=lambda 与 reverse=bool，min/max 另接受 key=lambda；"
        "内置容器与字符串方法（dict.get/keys/values/items/update、list.append/extend/insert/pop、"
        "str.split/strip/replace/join/find 等）可按属性调用；"
        "列表拼接结果与字典新增键最多500项；业务工具仍只接受具名参数。"
        "执行前检查整段语法白名单；禁止 import、try/except、其他属性访问、文件/网络访问；"
        "可调用函数只有目录列出的工具、基础函数与 range。\n"
        "工具返回实际 JSON 对象/列表，ID 工具返回实际 ID 字符串；变量跨程序保留。\n"
        "write_event 的成功身份用 result['results'][0]['event_id'] 读取；"
        "write_arc/write_outcome 的登记身份用 result['results'][0] 读取，完整示例见系统提示词。\n"
        "同一程序可读取、创建子父事件、登记关联和提交报告，不等待模型下一轮搬运 ID。\n"
        "所有函数参数以以下真实 schema 为准；evidence 是 paragraph_id/quote/occurrence 对象列表，"
        "不是段号整数。只使用原工具返回的真实 ID 和段号。\n"
        "每项校验、案例关联、审计独立执行；被拒操作不生效，成功操作保留。"
        "批量 write 的 results 与 items 按原顺序对应，被拒项为 None；failed 点名索引、源码行和原因。\n"
        "write_diagnosis 只写报告字段，不复制叙事组织草稿；narrative_organization、"
        "novel_id 和 foreshadow_expectation 由运行时在最终保存时绑定。\n"
        "函数赋值接收该函数真实返回值：批量 write 用 results/failed，不存在 written 键。"
        "reads/written 只属于 execute_code 外层回执，不能拿它们索引函数返回值；print 输出在 printed。"
        "review/link 的成功结果也是 None，以 failed 的索引判断失败，不把 None 一律当拒绝。\n"
        "案例处置写入复用标注语义：write_entity(name,entity_type,el,tags?,description?,"
        "representative?) 补签或更新实体；"
        "write_relation(from_entity,to_entity,relation_type) 登记人物关系（同一人物边承载身份归并）；"
        "write_dialogue(candidate_index,verdict,speaker?,tone?) 按候选号判定说话人；"
        "对话候选号从读取工具返回的正式对话目录取得；"
        "案例写入一律带 caseid=所办案例的真实 ID（先 promise_case 接手）。\n"
        "finish() 可放在程序内，仅请求执行完本程序后的完整性检查；"
        "无工具回复或外层 finish() 也请求同一检查。\n"
    )

    def __init__(
        self,
        tools: list[Any],
        *,
        observer: Any = None,
        invocation_id: str = "",
        dialogue_total: Any = None,
    ) -> None:
        super().__init__(tools, {tool.name: tool for tool in tools}, observer=observer, dialogue_total=dialogue_total)
        # 执行身份随 call_id 固定进业务地址：business_call_id 唯一键是全局的
        self.invocation_id = invocation_id
        self._pending_end = False
        self._end_requested = False
        self._written: list[dict[str, Any]] = []

    def build_tool(self) -> Any:
        """目录由原工具 schema 生成，避免把标注面的 evidence 整数口径带入诊断"""
        definitions: dict[str, Any] = {}
        functions: dict[str, Any] = {}
        for tool in self.tool_list:
            schema = tool.args_schema.model_json_schema()
            for name, definition in schema.pop("$defs", {}).items():
                if name in definitions and definitions[name] != definition:
                    raise ValueError(f"诊断工具定义冲突: {name}")
                definitions[name] = definition
            functions[tool.name] = {"description": tool.description, "parameters": schema}
        # 业务函数返回值与 execute_code 回执分开事件，登记身份仍沿用原领域返回类型
        result_types = {
            "write_event": {
                "event": {"status": "written", "event_id": "真实事件ID"},
                "contain": None,
                "relation": "真实关系ID",
                "review": None,
            },
            "write_arc": {"arc": "真实叙事线ID", "link": None},
            "write_outcome": {"outcome": "真实结果ID", "link": None},
        }
        for name, types in result_types.items():
            if name not in functions:
                continue
            functions[name]["returns"] = {
                "status": "written 或 partial",
                "results": "与 items 同序的结果数组",
                "result_by_operation": types,
                "failed": [{"index": "被拒项索引", "message": "实际原因"}],
            }
        read_types = {
            "search_text": [{"content": "命中原文", "paragraph_ids": ["真实段号"], "chapter_id": "真实章号"}],
            "read_text": {
                "chapter_id": "真实章号",
                "paragraph_id": "真实段号",
                "char_start": "片段起点",
                "char_end": "片段终点",
                "content": "实际原文",
                "source_ref": "证据来源ID",
            },
            "search_events": {"events": ["索引行"], "total": "命中总数", "next_offset": "下一页偏移或null"},
            "read_event": {"kind": "读取对象类型", "evidence": ["原文证据"], "parent_event_id": "直接父事件或null"},
            "search_graph": {
                "entities": [{"id": "实体ID", "name": "规范名", "entity_type": "大类"}],
                "relations": [{"source_id": "实体ID", "target_id": "实体ID", "relation_type": "关系类型"}],
                "total_entities": "实体总数",
                "total_relations": "关系总数",
                "next_offset": "实体下一页偏移或null",
                "next_relation_offset": "关系下一页偏移或null",
            },
            "read_entity": {"id": "实体ID", "name": "规范名", "entity_type": "大类", "attributes": "属性对象"},
            "search_cases": [{"case_id": "真实案例ID", "case_type": "四类之一", "promised": "是否已承诺"}],
            "read_metrics": {
                "aggregate": "全局指标",
                "pivots": ["转折点"],
                "high_tension": ["高张力段"],
                "foreshadowing": ["伏笔来源"],
                "foreshadow_expectation": "伏笔回收预期",
                "relation_changes": ["关系变化"],
                "graph_signals": "图谱统计",
            },
            "read_topics": {"topics": [{"topic_id": "真实主题ID", "words": "主题词", "label": "标签"}]},
            "promise_case": {"status": "promised 或 taken", "case_id": "真实案例ID"},
            "push_case": {"case_id": "真实案例ID"},
            "finish": {"status": "end_requested"},
        }
        for name, shape in read_types.items():
            if name in functions:
                functions[name]["returns"] = shape
        if "write_diagnosis" in functions:
            functions["write_diagnosis"]["returns"] = {"status": "written", "record": "diagnosis_report"}
        catalog = {"functions": functions, "$defs": definitions}
        return StructuredTool.from_function(
            coroutine=self.execute,
            name=PROGRAM_TOOL_NAME,
            description=self.contract_text + json.dumps(catalog, ensure_ascii=False, separators=(",", ":")),
        )

    def _reset_program_state(self) -> None:
        self._pending_end = self._end_requested = False
        self._written = []

    async def _after_program(self) -> None:
        # 先执行整批写入；语法/解释器故障时基座不调用此钩子，不能提前结束
        self._end_requested = self._pending_end

    def take_end_request(self) -> bool:
        """只把已完成程序的结束请求交给图，不自行完成或保存诊断"""
        requested = self._end_requested
        self._end_requested = False
        return requested

    @staticmethod
    def tool_error_is_fatal(name: str, error: BaseException) -> bool:
        return name == PROGRAM_TOOL_NAME and isinstance(error, DiagnosisProgramDependencyError)

    async def _dispatch(self, name: str, args: dict[str, Any], *, line: int | None) -> Any:
        # 每个批量项仍是独立领域操作；先校验整批形状，执行失败不回滚其他成功项
        if name in WRITE_NAMES and name != "write_diagnosis" and isinstance(args.get("items"), list):
            items = args["items"]
            schema = self.tools[name].args_schema
            try:
                schema.model_validate(args)
            except ValueError:
                return await self._dispatch_single(name, args, line=line)
            results: list[Any] = []
            failed: list[dict[str, Any]] = []
            for index, item in enumerate(items):
                self._guard()
                payload = await self._dispatch_single(name, {**args, "items": [item]}, line=line, item_index=index)
                if payload is None:
                    results.append(None)
                    failed.append({"index": index, "message": "该项参数被拒，详见 failed 回执"})
                else:
                    results.extend(payload["results"])
                    failed.extend({**entry, "index": index} for entry in payload["failed"])
            return {"status": "partial" if failed else "written", "results": results, "failed": failed}
        return await self._dispatch_single(name, args, line=line)

    async def _dispatch_single(
        self,
        name: str,
        args: dict[str, Any],
        *,
        line: int | None,
        item_index: int | None = None,
    ) -> Any:
        op_index = self._next_op_index(line=line)
        started_ns = time.perf_counter_ns()
        # call_id 是业务事实的全局唯一实际地址：诊断前缀 + 执行身份 + 程序内序号
        identity = f"{self.invocation_id}-" if self.invocation_id else ""
        call_id = f"diagnosis-{identity}{self._program_id}-op{op_index}"
        error: BaseException | None = None
        payload: Any = None
        try:
            raw = await _invoke_tool(self.tools, {"name": name, "args": args, "id": call_id})
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError):
                payload = raw
        except BaseException as exc:
            error = exc
        error_text = (str(error) or type(error).__name__) if error is not None else None
        receipt = (
            payload
            if error is None
            else {
                "code": "invalid_arguments"
                if isinstance(error, _INPUT_ERRORS)
                else "dependency_unavailable"
                if isinstance(error, Exception)
                else "interrupted",
                "message": error_text,
            }
        )
        native = payload.get("result", payload) if isinstance(payload, dict) else payload
        partial = isinstance(native, dict) and native.get("status") == "partial"
        if partial:
            error_text = "; ".join(entry["message"] for entry in native["failed"])
        status = "success" if error is None and not partial else "error"
        # 不使用标注面的读取回显截断规则；诊断工具自身已经做分页和原文长度约束
        self._log_op(
            name, op_index=op_index, line=line, status=status, receipt=receipt, call_args=args, error=error_text
        )
        if item_index is not None:
            self.ops[-1]["item_index"] = item_index
        if self.observer is not None:
            self.observer.record_tool_call(
                call_index=self._next_call_index(),
                tool_name=name,
                request_args={
                    **args,
                    "_tool_call_id": call_id,
                    "_program": {
                        "program_id": self._program_id,
                        "op_index": op_index,
                        "source_line": line,
                        "item_index": item_index,
                    },
                },
                raw_args=None,
                response=receipt,
                receipt=receipt,
                error=error_text,
                tool_duration_ms=max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000)),
                started_ns=started_ns,
            )
        if error is not None:
            if isinstance(error, _INPUT_ERRORS):
                return None
            if not isinstance(error, Exception):
                raise error
            raise DiagnosisProgramDependencyError(f"诊断工具 {name} 依赖故障: {error}") from error
        entry = {"op": op_index, "line": line, "tool": name, "result": payload}
        if name.startswith(("read_", "search_", "get_")):
            # 基座对 search_cases 已做过通用投影，这里替换为诊断原工具的完整实际结果
            self.reads = [item for item in self.reads if item.get("op") != op_index]
            self.reads.append(entry)
        elif status == "success":
            self._written.append(entry)
        if name == "finish":
            self._pending_end = True
        return payload

    def _receipt(
        self,
        *,
        status: str,
        applied: int,
        failed: list[dict[str, Any]],
        error: dict[str, Any] | None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """仅返回本程序调用事实，不提供剩余回合、覆盖缺项或报告状态反馈"""
        body: dict[str, Any] = {"status": status}
        if failed:
            body["failed"] = [
                {
                    "op": item["op_index"],
                    "line": item["source_line"],
                    "tool": item["tool_name"],
                    "message": item["message"],
                    **({"item_index": item["item_index"]} if "item_index" in item else {}),
                }
                for item in failed
            ]
        if error is not None:
            body["error"] = error
        if note is not None:
            body["note"] = note
        if self.reads:
            body["reads"] = self.reads
        if self._written:
            body["written"] = self._written
        if self.env:
            body["variables"] = sorted(self.env)
        return body
