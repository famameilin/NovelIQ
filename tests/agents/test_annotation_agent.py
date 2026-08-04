"""
标注 Agent 单元测试

- 图循环：agent 调用 finish 工具后进入 finalize 并产出合并输出
- 输出转换：MergedChunkAnnotation → 存储层结果
- 超长章节子代理：子块经同一入口独立会话处理
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from src.agents.annotation import IdentityMemory
from src.agents.annotation.evidence import AnnotationEvidenceLedger
from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.runner import convert_merged_output, validate_merged_output_against_chunk
from src.agents.annotation.schema import MergedChunkAnnotation
from src.agents.annotation.tools import build_annotation_tools
from src.agents.graph import build_agent_graph
from src.rag.evidence_types import EvidenceItem
from src.storage.repositories.annotation.foreshadowing_threads import ActiveSetupPoolEntry


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
                "name": "顾霜",
                "canonical": "顾霜",
                "entity_type": "character",
                "confidence": "high",
                "evidence": "顾霜",
            }
        ],
    }


class _FinishOnlyLLM:
    """假 LLM：第一轮直接调用 finish 工具提交合并输出"""

    def __init__(self, payload: dict, *, wrapped: bool = True) -> None:
        self.payload = payload
        self.wrapped = wrapped

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        args = {"annotation": self.payload} if self.wrapped else self.payload
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "finish",
                    "args": args,
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
async def test_annotation_graph_rejects_flat_finish_args_when_tool_schema_requires_wrapper() -> None:
    """
    2026-08-02 用于拒绝绕过真实 finish 工具 annotation 包装字段的扁平参数
    """
    memory = IdentityMemory()
    tools = build_annotation_tools(None, memory, run_id="run-1", chunk_id=1)
    graph = build_annotation_graph(_FinishOnlyLLM(_merged_payload(), wrapped=False), tools)

    from langchain_core.messages import HumanMessage, SystemMessage

    result = await graph.ainvoke(
        {
            "messages": [SystemMessage(content="test"), HumanMessage(content="标注当前文本")],
            "attempts": 0,
            "output": None,
            "error": None,
        }
    )

    assert result.get("output") is None
    assert "必须且只能包含包装字段 annotation" in str(result.get("error"))


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
                            "args": {"annotation": payload},
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
                        "args": {"annotation": _merged_payload()},
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


@pytest.mark.asyncio
async def test_agent_graph_stops_before_exceeding_tool_iteration_limit() -> None:
    """
    2026-08-04 用于保证普通工具循环达到 max_iterations 后返回明确错误而非递归异常
    """

    @tool
    def inspect_evidence() -> str:
        """
        2026-08-04 用于模拟可重复调用的普通 Agent 取证工具
        """
        return "证据"

    @tool
    def finish(annotation: MergedChunkAnnotation) -> str:
        """
        2026-08-04 用于为通用图测试提供符合真实包装结构的完成工具
        """
        del annotation
        return "OK"

    class _LoopingLLM:
        """持续请求普通工具的测试模型"""

        def bind_tools(self, _tools):
            """
            2026-08-04 用于模拟 LangChain 工具绑定
            """
            return self

        async def ainvoke(self, _messages):
            """
            2026-08-04 用于持续生成普通工具调用
            """
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "inspect_evidence", "args": {}, "id": "call-loop", "type": "tool_call"},
                ],
            )

    from langchain_core.messages import HumanMessage, SystemMessage

    graph = build_agent_graph(
        _LoopingLLM(),
        [inspect_evidence, finish],
        max_attempts=5,
        max_tool_iterations=1,
        response_model=MergedChunkAnnotation,
        first_hint="完成标注",
    )
    result = await graph.ainvoke(
        {
            "messages": [SystemMessage(content="test"), HumanMessage(content="标注")],
            "attempts": 0,
            "tool_iterations": 0,
            "output": None,
            "error": None,
            "candidate": None,
        }
    )

    assert result["tool_iterations"] == 1
    assert "工具调用超过上限 1" in str(result["error"])


@pytest.mark.asyncio
async def test_annotation_graph_revises_previous_candidate_with_partial_finish() -> None:
    """
    2026-08-03 用于验证校验失败后只提交局部字段即可保留其他阶段结果
    """
    memory = IdentityMemory()
    tools = build_annotation_tools(None, memory, run_id="run-1", chunk_id=1)

    class _BadThenPatchLLM:
        """先提交错误完整结果再提交单字段修正"""

        def __init__(self) -> None:
            """
            2026-08-03 用于初始化完整候选与局部修正测试模型
            """
            self.calls = 0

        def bind_tools(self, _tools):
            """
            2026-08-03 用于返回测试模型自身以模拟工具绑定
            """
            return self

        async def ainvoke(self, _messages):
            """
            2026-08-03 用于先提交结构错误结果再只修正情感字段
            """
            self.calls += 1
            if self.calls == 1:
                payload = _merged_payload()
                payload["emotional_valence"] = "invalid"
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "finish",
                            "args": {"annotation": payload},
                            "id": "call_finish_bad",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "revise_finish",
                        "args": {"correction": {"emotional_valence": "neutral"}},
                        "id": "call_revise_finish",
                        "type": "tool_call",
                    }
                ],
            )

    llm = _BadThenPatchLLM()
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
    assert result["output"]["emotional_valence"] == "neutral"
    assert result["output"]["chunk_summary"] == _merged_payload()["chunk_summary"]
    assert result["output"]["characters"] == _merged_payload()["characters"]
    assert result["output"]["dialogues"][0]["content"] == _merged_payload()["dialogues"][0]["content"]
    assert result["output"]["dialogues"][0]["speaker"] == _merged_payload()["dialogues"][0]["speaker"]
    assert result["output"]["relations"] == _merged_payload()["relations"]
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_annotation_graph_rejects_finish_mixed_with_other_tool_calls() -> None:
    """
    2026-08-02 用于阻止同一轮 finish 与其他工具并发导致工具调用被静默跳过
    """
    memory = IdentityMemory()
    tools = build_annotation_tools(None, memory, run_id="run-1", chunk_id=1)

    class _MixedThenFinishLLM:
        """先混合调用再单独提交 finish 的测试模型"""

        def __init__(self) -> None:
            """
            2026-08-02 用于初始化混合工具调用测试模型的调用次数
            """
            self.calls = 0

        def bind_tools(self, _tools):
            """
            2026-08-02 用于返回测试模型自身以模拟工具绑定
            """
            return self

        async def ainvoke(self, _messages):
            """
            2026-08-02 用于先生成混合调用再生成唯一 finish 调用
            """
            self.calls += 1
            finish_call = {
                "name": "finish",
                "args": {"annotation": _merged_payload()},
                "id": f"call_finish_{self.calls}",
                "type": "tool_call",
            }
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "lookup_identity",
                            "args": {"name": "顾霜"},
                            "id": "call_lookup_1",
                            "type": "tool_call",
                        },
                        finish_call,
                    ],
                )
            return AIMessage(content="", tool_calls=[finish_call])

    llm = _MixedThenFinishLLM()
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


@pytest.mark.asyncio
async def test_annotation_graph_does_not_reuse_previous_invalid_finish_call() -> None:
    """
    2026-08-02 用于保证校验失败后模型未再次提交 finish 时不会复用旧参数
    """
    memory = IdentityMemory()
    tools = build_annotation_tools(None, memory, run_id="run-1", chunk_id=1)

    class _InvalidThenTextLLM:
        """先提交无效结果再只返回文本的测试模型"""

        def __init__(self) -> None:
            """
            2026-08-02 用于初始化旧 finish 复用测试模型的调用次数
            """
            self.calls = 0

        def bind_tools(self, _tools):
            """
            2026-08-02 用于返回测试模型自身以模拟工具绑定
            """
            return self

        async def ainvoke(self, _messages):
            """
            2026-08-02 用于首轮提交无效 finish 后返回无工具文本
            """
            self.calls += 1
            if self.calls == 1:
                payload = _merged_payload()
                payload["emotional_valence"] = "invalid"
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "finish",
                            "args": {"annotation": payload},
                            "id": "call_finish_invalid",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(content="尚未重新提交")

    graph = build_annotation_graph(_InvalidThenTextLLM(), tools)

    from langchain_core.messages import HumanMessage, SystemMessage

    result = await graph.ainvoke(
        {
            "messages": [SystemMessage(content="test"), HumanMessage(content="标注当前文本")],
            "attempts": 0,
            "output": None,
            "error": None,
        }
    )

    assert result.get("output") is None
    assert result.get("error") == "agent 未调用 finish 工具提交结果"


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


def test_convert_merged_output_rejects_dialogues_not_in_text() -> None:
    """
    2026-08-02 用于拒绝落库当前 chunk 中不存在的对话原文
    """
    merged = MergedChunkAnnotation.model_validate(_merged_payload())

    with pytest.raises(ValueError, match="对话未逐字出现在当前原文"):
        convert_merged_output(merged, "完全无关的文本内容")


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


def test_foreshadowing_schema_rejects_existing_thread_without_setup_id() -> None:
    """
    2026-08-02 用于拒绝缺少真实 linked_setup_id 的既有伏笔线程结果
    """
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
        "is_new_setup": False,
        "linked_setup_id": None,
        "setup_status": "reinforced",
        "confidence": "high",
    }

    with pytest.raises(ValueError, match="requires linked_setup_id"):
        MergedChunkAnnotation.model_validate(payload)


def test_annotation_tools_expose_visible_foreshadowing_setup_ids() -> None:
    """
    2026-08-02 用于验证活跃伏笔工具返回当前 chunk 之前的真实 setup_id
    """
    session = MagicMock()
    memory = IdentityMemory()
    tools = build_annotation_tools(
        None,
        memory,
        run_id="run-1",
        chunk_id=8,
        session=session,
    )
    thread_tool = next(tool for tool in tools if tool.name == "list_active_foreshadowing_threads")
    entry = ActiveSetupPoolEntry(
        setup_id="setup-real-uuid",
        setup_summary="顾霜扬言取贺重明性命",
        setup_kind="明确承诺",
        expected_payoff_family="生死对决",
        payoff_likelihood="high",
        confidence="high",
        strength="high",
        status="reinforced",
        last_chunk_id=6,
    )

    with patch(
        "src.storage.repositories.annotation.foreshadowing_threads."
        "fetch_active_foreshadowing_threads_for_prompt",
        return_value=[entry],
    ) as mock_fetch:
        rendered = thread_tool.invoke({})

    assert "setup_id=setup-real-uuid" in rendered
    assert "summary=顾霜扬言取贺重明性命" in rendered
    mock_fetch.assert_called_once_with(
        session,
        "run-1",
        max_chunk_id=7,
    )


def test_convert_merged_output_relations() -> None:
    payload = _merged_payload()
    payload["dialogues"] = []
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
    assert restored.identity_decisions[0].name == "顾霜"
    assert restored.identity_decisions[0].canonical == "顾霜"


def test_validate_merged_output_rejects_ungrounded_character() -> None:
    """
    2026-08-02 用于拒绝人物未逐字出现在当前原文的标注结果
    """
    payload = _merged_payload()
    payload["characters"][0]["name"] = "虚构人物"
    merged = MergedChunkAnnotation.model_validate(payload)

    with pytest.raises(ValueError, match="人物未逐字出现在当前原文"):
        validate_merged_output_against_chunk(
            merged,
            "顾霜冷冷道：「今日便是你的死期。」",
        )


def test_validate_merged_output_rejects_ungrounded_relation_evidence() -> None:
    """
    2026-08-02 用于拒绝关系依据未逐字出现在当前原文的标注结果
    """
    payload = _merged_payload()
    payload["relations"] = [
        {
            "from": "顾霜",
            "to": "贺重明",
            "type": "敌对",
            "change": "新建",
            "evidence": "两人早已结仇",
        }
    ]
    merged = MergedChunkAnnotation.model_validate(payload)

    with pytest.raises(ValueError, match="关系证据未逐字出现在当前原文"):
        validate_merged_output_against_chunk(
            merged,
            "顾霜压制贺重明，并说道：「今日便是你的死期。」",
        )


def test_validate_merged_output_rejects_ungrounded_identity_decision() -> None:
    """
    2026-08-02 用于拒绝缺少当前原文依据的身份合并结果
    """
    payload = _merged_payload()
    payload["identity_decisions"] = [
        {
            "name": "阿顾",
            "canonical": "顾霜",
            "entity_type": "character",
            "confidence": "high",
            "evidence": "阿顾就是顾霜",
        }
    ]
    merged = MergedChunkAnnotation.model_validate(payload)

    with pytest.raises(ValueError, match="身份称呼未出现在当前原文"):
        validate_merged_output_against_chunk(
            merged,
            "顾霜冷冷道：「今日便是你的死期。」",
        )


def test_validate_merged_output_accepts_historical_evidence_from_current_ledger() -> None:
    """
    2026-08-02 用于验证 finish 可以引用本轮真实检索到的历史自然段证据
    """
    payload = _merged_payload()
    payload["historical_evidence_citations"] = [
        {
            "evidence_id": "paragraph:2:0:10:20",
            "purpose": "identity",
            "claim": "历史原文确认阿顾是顾霜的称呼",
        }
    ]
    ledger = AnnotationEvidenceLedger()
    ledger.register_evidence_items(
        [
            EvidenceItem(
                evidence_type="semantic_recall",
                source="paragraph_embeddings",
                content="众人称顾霜为阿顾。",
                evidence_id="paragraph:2:0:10:20",
                chunk_id=2,
                retrieval_method="semantic",
            )
        ],
        objective="identity",
    )

    validate_merged_output_against_chunk(
        MergedChunkAnnotation.model_validate(payload),
        "顾霜冷冷道：「今日便是你的死期。」",
        evidence_ledger=ledger,
    )


def test_validate_merged_output_rejects_unknown_historical_evidence_id() -> None:
    """
    2026-08-02 用于拒绝 finish 引用本轮证据账本中不存在的历史证据 ID
    """
    payload = _merged_payload()
    payload["historical_evidence_citations"] = [
        {
            "evidence_id": "paragraph:999:0:0:10",
            "purpose": "identity",
            "claim": "不存在的历史依据",
        }
    ]

    with pytest.raises(ValueError, match="未出现在本轮检索账本"):
        validate_merged_output_against_chunk(
            MergedChunkAnnotation.model_validate(payload),
            "顾霜冷冷道：「今日便是你的死期。」",
            evidence_ledger=AnnotationEvidenceLedger(),
        )


def test_validate_merged_output_rejects_historical_evidence_objective_mismatch() -> None:
    """
    2026-08-02 用于拒绝把身份检索证据直接冒充关系检索证据
    """
    payload = _merged_payload()
    payload["historical_evidence_citations"] = [
        {
            "evidence_id": "paragraph:2:0:10:20",
            "purpose": "relation",
            "claim": "历史原文支持两人关系",
        }
    ]
    ledger = AnnotationEvidenceLedger()
    ledger.register_evidence_items(
        [
            EvidenceItem(
                evidence_type="semantic_recall",
                source="paragraph_embeddings",
                content="众人称顾霜为阿顾。",
                evidence_id="paragraph:2:0:10:20",
                chunk_id=2,
                retrieval_method="semantic",
            )
        ],
        objective="identity",
    )

    with pytest.raises(ValueError, match="用途与检索目标不一致"):
        validate_merged_output_against_chunk(
            MergedChunkAnnotation.model_validate(payload),
            "顾霜冷冷道：「今日便是你的死期。」",
            evidence_ledger=ledger,
        )
