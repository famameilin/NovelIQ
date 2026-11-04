"""诊断程序面：复用受限解释器，逐操作执行原工具，不复制业务校验"""

from __future__ import annotations

import json
import time
from typing import Any

from src.agents.annotation.catalog import call_parameters, render_list_signature
from src.agents.annotation.errors import AnnotationAuthorizationError, AnnotationDependencyError, AnnotationInputError
from src.agents.program_runtime.contracts import (
    PROGRAM_MAX_RANGE_ITEMS,
    PROGRAM_MAX_WHILE_ITERATIONS,
    PROGRAM_TOOL_NAME,
)
from src.agents.program_runtime.interpreter import RestrictedProgramRuntime
from src.agents.program_runtime.returns import TOOL_RETURN_SHAPES
from src.agents.tools import Tool, describe_argument_error, invoke_tool

from .tools import WRITE_NAMES

_INPUT_ERRORS = (ValueError, AnnotationInputError, AnnotationAuthorizationError)


class DiagnosisProgramDependencyError(AnnotationDependencyError):
    """程序运行依赖故障，记录审计后终止任务，不交给模型修正"""


class DiagnosisProgramRuntime(RestrictedProgramRuntime):
    """一个诊断执行复用一份变量环境；所有写入仍由原诊断工具维护内存草稿"""

    contract_text = (
        "使用 execute_code(code=...) 提交受限 Python 程序。只支持赋值与等长解包、"
        "增量赋值（+= -= *= /= //= %=）、具名工具调用（可 ** 展开）、"
        "列表/字典/元组/集合（含 * 与 ** 解包）、列表/字典/集合推导式、"
        "下标与切片、字典下标赋值、算术与比较、and/or/not、条件表达式、f-string、"
        "无默认值位置参数的 lambda 与 def（可 return）、for/while 与 if、try/except/else/finally、"
        "break/continue、import；"
        "range(stop)/range(start,stop,step) 与基础函数（len/str/int/float/bool/min/max/abs/sum/sorted/enumerate/"
        "isinstance/any/all/round/repr/print/list/dict/set/tuple/zip/reversed/format）"
        "只接受位置参数（dict 另接受 k=v 关键字）；sorted 另接受 key=lambda 或 def 函数与 reverse=bool，"
        "min/max 另接受 key=lambda 或 def 函数；"
        "内置容器与字符串方法（dict.get/keys/values/items/update、list.append/extend/insert/pop、"
        "str.split/strip/replace/join/find 等）可按属性调用；"
        "import 只开放 json/unicodedata/math/collections/datetime，模块属性只允许调用放行函数；"
        "except 不写类型或只写 Exception，只捕获运行期错误；"
        "业务工具仍只接受具名参数。"
        "执行前检查整段语法白名单；禁止其他属性访问、文件/网络访问；"
        "可调用函数只有目录列出的工具、基础函数、range 与已导入模块的放行函数。"
        f"range 与序列重复单项不超过 {PROGRAM_MAX_RANGE_ITEMS}，"
        f"while 不超过 {PROGRAM_MAX_WHILE_ITERATIONS} 次。\n"
        "工具返回实际 JSON 对象/列表，ID 工具返回实际 ID 字符串；变量跨程序保留。\n"
        "顶层 return 的值进入回执 result（只接受 JSON 可序列化值）；被 except 捕获的故障进回执 caught。\n"
        "同一程序可连续读取和写入，不等待模型下一轮搬运 ID。\n"
        "所有函数参数以以下真实 schema 为准；evidence 是 paragraph_id/quote/occurrence 对象列表，"
        "不是段号整数。只使用原工具返回的真实 ID 和段号。\n"
        "每项校验、案例关联、审计独立执行；被拒操作不生效，成功操作保留。"
        "批量 write 的 results 与 items 按原顺序对应，被拒项为 None；failed 点名索引、源码行和原因。\n"
        "函数赋值接收该函数真实返回值：批量 write 用 results/failed，不存在 written 键。"
        "reads/written 只属于 execute_code 外层回执，不能拿它们索引函数返回值；print 输出在 printed。"
        "link/contain 的成功结果也是 None，以 failed 的索引判断失败，不把 None 一律当拒绝。\n"
        "finish() 可放在程序内，仅请求执行完本程序后的完整性检查；"
        "无工具回复或外层 finish() 也请求同一检查。\n"
    )

    def __init__(
        self,
        tools: list[Any],
        *,
        observer: Any = None,
        invocation_id: str = "",
    ) -> None:
        super().__init__(
            tools,
            {tool.name: tool for tool in tools},
            observer=observer,
            signature_hint=lambda name: render_list_signature(name, call_parameters(name, self.tools.get(name))),
        )
        # 执行身份随 call_id 固定进业务地址：business_call_id 唯一键是全局的
        self.invocation_id = invocation_id
        self._pending_end = False
        self._end_requested = False
        self._written: list[dict[str, Any]] = []
        self._timings: dict[str, dict[str, float]] = {}

    def record_timing(self, name: str, category: str, elapsed_ns: int) -> None:
        "记录单项工具的锁等待或执行耗时，仅用于审计"
        self._timings.setdefault(name, {})[category + "_ms"] = round(elapsed_ns / 1_000_000, 3)

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
        for name, shape in TOOL_RETURN_SHAPES.items():
            if name in functions:
                functions[name]["returns"] = shape
        if "write_link" in functions:
            functions["write_link"]["returns"] = {
                "status": "written 或 partial",
                "results": "与 items 同序的结果数组",
                "failed": [{"index": "被拒项索引", "message": "实际原因"}],
                "progress": "事件线进度与会话草稿快照",
                "report_stale": "报告草稿是否失效",
            }
        if "retract_structure" in functions:
            functions["retract_structure"]["returns"] = {
                "status": "written 或 partial",
                "results": "与 items 同序的结果数组",
                "failed": [{"index": "被拒项索引", "message": "实际原因"}],
                "progress": "事件线进度与会话草稿快照",
            }
        if "write_event" in functions:
            functions["write_event"]["returns"] = {
                "status": "written",
                "tree_id": "事件树独立ID",
                "results": [{"status": "accepted_candidate", "event_id": "与 items 同序的真实成员ID"}],
                "failed": [],
            }
        if "write_diagnosis" in functions:
            functions["write_diagnosis"]["returns"] = {"status": "written", "record": "diagnosis_report"}
        if "name_event_lines" in functions:
            functions["name_event_lines"]["returns"] = {
                "status": "written",
                "record": "event_line_names",
                "names": "与提交一致的 tree_id 到线名映射",
                "progress": "事件线命名进度",
                "report_stale": "报告草稿是否失效",
            }
        catalog = {"functions": functions, "$defs": definitions}
        instructions = self.contract_text
        if "write_event" in functions:
            instructions += (
                "write_event(items=[...]) 一次提交一棵完整有序事件树，每项是完整事件，不传 operation；"
                "树身份读取 result['tree_id']，成员身份读取 result['results'][下标]['event_id']。\n"
            )
        if "write_entity" in functions:
            instructions += (
                "案例处置写入复用标注语义：write_entity(name,entity_type,el,tags?,description?,"
                "representative?) 补签或更新实体；"
                "write_relation(from_entity,to_entity,relation_type) 登记人物关系（同一人物边承载身份归并）；"
                "write_dialogue(candidate_index,verdict,speaker?,tone?) 按候选号判定说话人；"
                "对话候选号从读取工具返回的正式对话目录取得。\n"
            )
        if "claim_random_case" in functions:
            instructions += (
                "案例写入一律带 caseid=所办案例的真实 ID，先 claim_case 或 claim_random_case，办完 submit_case。\n"
                "提交回执的 candidates 最多十件且不预占；下次正常推理可指定领取熟悉案例，"
                "没有合适候选或返回 taken 时随机领取，不强制另开选案回合。\n"
            )
        if "write_diagnosis" in functions:
            instructions += (
                "write_outcome 的登记身份用 result['results'][0] 读取。\n"
                "write_diagnosis 只写报告字段，不复制事件树与结果草稿；narrative_organization、"
                "novel_id 和 foreshadow_expectation 由运行时在最终保存时绑定。\n"
            )
        return Tool.from_function(
            coroutine=self.execute,
            name=PROGRAM_TOOL_NAME,
            description=instructions + json.dumps(catalog, ensure_ascii=False, separators=(",", ":")),
        )

    def _reset_program_state(self) -> None:
        self._pending_end = self._end_requested = False
        self._written = []

    async def _after_program(self) -> None:
        # 先执行整批写入；语法/解释器故障时基座不调用此钩子，不能提前结束
        self._end_requested = self._pending_end

    def take_end_request(self) -> bool:
        """将已完成程序的结束请求交给会话循环"""
        requested = self._end_requested
        self._end_requested = False
        return requested

    @staticmethod
    def tool_error_is_fatal(name: str, error: BaseException) -> bool:
        return name == PROGRAM_TOOL_NAME and isinstance(error, DiagnosisProgramDependencyError)

    async def _dispatch(self, name: str, args: dict[str, Any], *, line: int | None) -> Any:
        # 事件列表是一棵完整事件树，其他工具的批量项各自独立
        if (
            name in WRITE_NAMES
            and name not in {"write_diagnosis", "write_event"}
            and isinstance(args.get("items"), list)
        ):
            items = args["items"]
            schema = self.tools[name].args_schema
            try:
                schema.model_validate(args)
            except ValueError:
                return await self._dispatch_single(name, args, line=line)
            results: list[Any] = []
            failed: list[dict[str, Any]] = []
            for index, item in enumerate(items):
                await self._checkpoint()
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
        self._timings.pop(name, None)
        # call_id 是业务事实的全局唯一实际地址：诊断前缀 + 执行身份 + 程序内序号
        identity = f"{self.invocation_id}-" if self.invocation_id else ""
        call_id = f"diagnosis-{identity}{self._program_id}-op{op_index}"
        error: BaseException | None = None
        payload: Any = None
        try:
            raw = await invoke_tool(self.tools, {"name": name, "args": args, "id": call_id})
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError):
                payload = raw
        except BaseException as exc:
            error = exc
        error_text = (str(error) or type(error).__name__) if error is not None else None
        argument_detail = describe_argument_error(error) if error is not None else None
        if argument_detail is not None:
            hint = self._signature_hint(name) if self._signature_hint is not None else ""
            error_text = f"参数不合法：{argument_detail}" + (f"；正确参数：{hint}" if hint else "")
        receipt = (
            payload
            if error is None
            else {
                "record": name,
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
                    "_timing": self._timings.pop(name, {}),
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
