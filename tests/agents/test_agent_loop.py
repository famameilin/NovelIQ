"""会话结束、程序超时、消息身份及工具输入边界"""

import asyncio
import json
from typing import Annotated
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from src.agents.annotation.shared_tools import build_finish_tool
from src.agents.diagnosis.program_runtime import DiagnosisProgramRuntime
from src.agents.diagnosis.session_loop import build_diagnosis_loop
from src.agents.messages import AssistantMessage, UserMessage, merge_messages
from src.agents.program_runtime.contracts import ProgramExecutionTimeout
from src.agents.tools import tool
from tests.agents.test_diagnosis_agent import Replies, call


def initial_state():
    return {"messages": [UserMessage(content="完成业务")], "iterations": 0, "error": None}


def test_message_identity_replaces_in_place_and_preserves_order():
    original = UserMessage(content="初始", id="same")
    second = AssistantMessage(content="已有回复")
    updated = UserMessage(content="修改", id="same")
    appended = AssistantMessage(content="新回复")
    result = merge_messages([original, second], [updated, appended])
    assert result == [updated, second, appended]
    assert second.id and appended.id and second.id != appended.id


class NestedInput(BaseModel):
    value: Annotated[int, Field(ge=0)]


def test_tool_validation_preserves_nested_models_missing_and_explicit_none():
    @tool
    def capture(item: NestedInput, caseid: str | None = "default"):
        """返回实际参数类型与案例关联"""
        return item.value, caseid

    assert capture.invoke({"item": {"value": 3}}) == (3, "default")
    assert capture.invoke({"item": {"value": 3}, "caseid": None}) == (3, None)
    capture.args_schema = create_model(
        "CaptureInput",
        __base__=capture.args_schema,
        __config__=ConfigDict(extra="forbid"),
    )
    with pytest.raises(ValidationError):
        capture.invoke({"item": {"value": -1}})
    with pytest.raises(ValidationError):
        capture.invoke({"item": {"value": 1}, "unknown": True})
    nested_properties = capture.provider_schema()["function"]["parameters"]["$defs"]["NestedInput"]["properties"]
    assert nested_properties["value"]["minimum"] == 0


async def test_program_timeout_retains_success_and_stops_remaining_calls_and_model_rounds():
    effects = []

    @tool
    def write() -> str:
        """记录一项业务结果后使本次程序到期"""
        effects.append("written")
        runtime._deadline = 0
        return json.dumps({"status": "written"})

    observer = MagicMock()
    runtime = DiagnosisProgramRuntime([write, build_finish_tool(lambda: {})], observer=observer)
    model = Replies(
        [
            AssistantMessage(tool_calls=[call("execute_code", {"code": "write()\nwrite()"})]),
            AssistantMessage(tool_calls=[call("finish")]),
        ]
    )
    loop = build_diagnosis_loop(model, runtime, max_iterations=3, completion_check=lambda: [], observer=observer)
    with pytest.raises(ProgramExecutionTimeout) as error:
        await loop.run(initial_state())
    assert effects == ["written"] and len(model.requests) == 1
    assert runtime.ops[0]["status"] == "success"
    assert json.loads(error.value.receipt)["error"]["type"] == "deadline_exceeded"
    audit = [entry.kwargs for entry in observer.record_tool_call.call_args_list]
    assert [entry["tool_name"] for entry in audit] == ["write", "execute_code"]
    assert audit[0]["error"] is None and audit[1]["error"]
    assert runtime.take_end_request() is False


async def test_failed_program_does_not_promote_earlier_finish():
    runtime = DiagnosisProgramRuntime([build_finish_tool(lambda: {"status": "end_requested"})])
    model = Replies(
        [
            AssistantMessage(tool_calls=[call("execute_code", {"code": "finish()\nvalue = undefined"})]),
            AssistantMessage(tool_calls=[call("finish")]),
        ]
    )
    checked = []
    loop = build_diagnosis_loop(
        model,
        runtime,
        max_iterations=3,
        completion_check=lambda: checked.append(True) or [],
    )
    result = await loop.run(initial_state())
    assert result["completion_ok"] and len(model.requests) == 2 and checked == [True]


async def test_external_finish_does_not_skip_later_call_in_same_batch():
    effects = []

    @tool
    def write() -> str:
        """登记业务结果"""
        effects.append("written")
        return json.dumps({"status": "written"})

    runtime = DiagnosisProgramRuntime([write, build_finish_tool(lambda: {})])
    model = Replies(
        [
            AssistantMessage(
                tool_calls=[
                    call("finish"),
                    call("execute_code", {"code": "write()"}),
                ]
            )
        ]
    )

    def check():
        assert effects == ["written"]
        return []

    result = await build_diagnosis_loop(model, runtime, max_iterations=2, completion_check=check).run(initial_state())
    assert result["completion_ok"] and len(model.requests) == 1


async def test_long_ast_loop_cooperates_with_cancellation():
    runtime = DiagnosisProgramRuntime([])
    task = asyncio.create_task(runtime.execute("for item in range(100000):\n    value = item"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.parametrize(
    "code",
    [
        "values = range(700)\nresult = len(values[:350] + values[350:])",
        "values = range(700)\nresult = len([*values]) + len(tuple(values))",
        "values = range(700)\nmapping = {}\nfor index in values:\n    mapping[index] = index\nresult = len(mapping)",
        "values = range(700)\nresult = len(enumerate(values)) + len(zip(values, values)) + len(reversed(values))",
        "values = range(700)\nresult = len(sorted(values)) + len(dict([(index, index) for index in values]))",
        "values = range(700)\nvalues.append(700)\nvalues.insert(0, -1)\nvalues.extend([701])\nresult = len(values)",
        "mapping = {index: index for index in range(700)}\nmapping.update({701: 701})\n"
        "result = len(mapping.copy().keys())",
        "text = ','.join(['a' for index in range(700)])\nresult = len(text.split(','))",
    ],
)
async def test_container_operations_accept_more_than_500_items(code):
    runtime = DiagnosisProgramRuntime([])
    receipt = json.loads(await runtime.execute(code))
    assert receipt["status"] == "applied", receipt
    assert runtime.env["result"] > 500
