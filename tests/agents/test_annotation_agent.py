"""
标注 Agent 单元测试

- 图循环：agent 调用 finish 工具后进入 finalize 并产出合并输出
- 输出转换：MergedChunkAnnotation → 存储层结果
- 超长章节子代理：子块经同一入口独立会话处理
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from src.agents.annotation import IdentityMemory
from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.runner import convert_merged_output
from src.agents.annotation.schema import MergedChunkAnnotation
from src.agents.annotation.tools import build_annotation_tools


def _merged_payload() -> dict:
    return {
        "emotional_valence": "mild_negative",
        "event_type": "冲突",
        "pivot_moment": False,
        "cliffhanger": False,
        "chunk_summary": "顾霜以灵力压制贺重明，贺重明隐忍盘算",
        "characters": [
            {
                "name": "顾霜",
                "role_function": "主体",
                "action": "以灵力压制贺重明",
                "action_type": "战斗",
                "emotion_score": "mild_negative",
            }
        ],
        "location_appearances": [],
        "foreshadowing": {
            "has_foreshadowing": False,
            "confidence": "low",
        },
        "dialogues": [
            {
                "content": "今日便是你的死期。",
                "speaker": ["顾霜"],
                "tone": "强硬",
                "is_inner_monologue": False,
            }
        ],
        "relations": [],
        "identity_decisions": [
            {
                "name": "阿顾",
                "canonical": "顾霜",
                "entity_type": "character",
                "confidence": "high",
                "evidence": "原文",
            }
        ],
    }


class _FinishOnlyLLM:
    """假 LLM：第一轮直接调用 finish 工具提交合并输出"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "finish",
                    "args": self.payload,
                    "id": "call_finish_1",
                    "type": "tool_call",
                }
            ],
        )


@pytest.mark.asyncio
async def test_annotation_graph_produces_merged_output() -> None:
    memory = IdentityMemory()
    tools = build_annotation_tools(None, memory, run_id="run-1", chunk_id=1)
    graph = build_annotation_graph(_FinishOnlyLLM(_merged_payload()), tools)

    from langchain_core.messages import HumanMessage, SystemMessage

    result = await graph.ainvoke(
        {
            "messages": [
                SystemMessage(content="test"),
                HumanMessage(content="标注当前文本"),
            ],
            "attempts": 0,
            "output": None,
            "error": None,
        }
    )

    assert result.get("error") is None
    output = result.get("output")
    assert output is not None
    merged = MergedChunkAnnotation.model_validate(output)
    assert merged.chunk_summary.startswith("顾霜")
    assert merged.characters[0].name == "顾霜"
    assert merged.dialogues[0].speaker == ["顾霜"]


@pytest.mark.asyncio
async def test_annotation_graph_retries_on_invalid_output() -> None:
    """finish 输出校验失败时回 agent 重试，直到超限报错"""
    memory = IdentityMemory()
    tools = build_annotation_tools(None, memory, run_id="run-1", chunk_id=1)

    class _BadThenGoodLLM:
        def __init__(self) -> None:
            self.calls = 0

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                payload = _merged_payload()
                payload["emotional_valence"] = "invalid_value"
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "finish",
                            "args": payload,
                            "id": "call_finish_bad",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "finish",
                        "args": _merged_payload(),
                        "id": "call_finish_good",
                        "type": "tool_call",
                    }
                ],
            )

    llm = _BadThenGoodLLM()
    graph = build_annotation_graph(llm, tools)

    from langchain_core.messages import HumanMessage, SystemMessage

    result = await graph.ainvoke(
        {
            "messages": [SystemMessage(content="test"), HumanMessage(content="标注当前文本")],
            "attempts": 0,
            "output": None,
            "error": None,
        }
    )

    assert result.get("error") is None
    assert result.get("output") is not None
    assert llm.calls == 2


def test_convert_merged_output_produces_storage_result() -> None:
    chunk_text = "顾霜冷冷道：「今日便是你的死期。」贺重明不以为意。"
    merged = MergedChunkAnnotation.model_validate(_merged_payload())

    result = convert_merged_output(merged, chunk_text)

    assert result.annotation.chunk_summary.startswith("顾霜")
    assert result.annotation.characters[0].name == "顾霜"
    assert result.annotation.has_foreshadowing is False
    assert result.dialogues is not None and len(result.dialogues) == 1
    dialogue_index = result.dialogues[0][0]
    assert result.dialogue_speakers is not None and result.dialogue_speakers[dialogue_index] == ["顾霜"]
    assert result.dialogue_tones == {dialogue_index: "强硬"}
    assert result.dialogue_lengths == [len("今日便是你的死期。")]


def test_convert_merged_output_skips_dialogues_not_in_text() -> None:
    """对话原文不在 chunk 文本中时仍按顺序分配索引，不丢弃"""
    merged = MergedChunkAnnotation.model_validate(_merged_payload())

    result = convert_merged_output(merged, "完全无关的文本内容")

    assert result.dialogues is not None and len(result.dialogues) == 1
    assert result.dialogues[0][1] == "今日便是你的死期。"


def test_convert_merged_output_with_foreshadowing() -> None:
    payload = _merged_payload()
    payload["foreshadowing"] = {
        "has_foreshadowing": True,
        "foreshadowing_type": "对话",
        "setup_kind": "明确承诺",
        "anchor_text": "今日便是你的死期",
        "anchor_reason": "威胁性对话",
        "setup_summary": "顾霜扬言取贺重明性命",
        "why_unresolved_now": "尚未动手",
        "expected_payoff_family": "生死对决",
        "payoff_likelihood": "high",
        "is_new_setup": True,
        "linked_setup_id": None,
        "setup_status": "open",
        "confidence": "high",
    }
    merged = MergedChunkAnnotation.model_validate(payload)

    result = convert_merged_output(merged, "顾霜冷冷道：「今日便是你的死期。」")

    assert result.foreshadowing is not None
    assert result.foreshadowing.has_foreshadowing is True
    assert result.foreshadowing.setup_summary == "顾霜扬言取贺重明性命"


def test_convert_merged_output_relations() -> None:
    payload = _merged_payload()
    payload["relations"] = [
        {
            "from": "顾霜",
            "to": "贺重明",
            "type": "敌对",
            "change": "新建",
            "evidence": "顾霜压制贺重明",
        }
    ]
    merged = MergedChunkAnnotation.model_validate(payload)

    result = convert_merged_output(merged, "顾霜压制贺重明")

    assert result.relations is not None and len(result.relations) == 1
    assert result.relations[0].from_name == "顾霜"
    assert result.relations[0].to_name == "贺重明"
    assert result.relations[0].type == "敌对"
    assert result.relations[0].change == "新建"


def test_json_roundtrip_of_merged_schema() -> None:
    """MergedChunkAnnotation 可 JSON 序列化/反序列化（agent 工具参数合同）"""
    payload = _merged_payload()
    merged = MergedChunkAnnotation.model_validate(payload)
    dumped = json.loads(merged.model_dump_json())

    restored = MergedChunkAnnotation.model_validate(dumped)
    assert restored.identity_decisions[0].name == "阿顾"
    assert restored.identity_decisions[0].canonical == "顾霜"
