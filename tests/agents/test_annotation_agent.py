"""章节级标注 Agent 逐 chunk LangGraph 与 Runner 测试（独立提交 + 上下文上界）"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.annotation.errors import (
    AnnotationAuthorizationError,
    AnnotationInputError,
    AnnotationInvariantError,
)
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.prompts import build_chunk_message
from src.agents.annotation.runner import (
    run_annotation_agent,
    validate_bound_annotation,
)
from src.agents.annotation.schema import (
    ActiveCaseDetails,
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundSentenceLabel,
    CaseSearchResult,
    ChunkMetricsInput,
    ChunkParagraphInfo,
    EmotionalValence,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """2026-08-07 用于提供无数据库依赖的新合同查询桩"""

    def find_initial_case_candidates(self, current_text, *, semantic_limit=50, rotation_limit=50):
        """2026-08-07 用于返回空初始案例集合"""
        del current_text, semantic_limit, rotation_limit
        return [], []

    def search_pool(self, query, *, hidden_case_ids, limit=50):
        """2026-08-07 用于返回空案例与伏笔检索结果"""
        from src.agents.annotation.schema import SearchResult

        del query, hidden_case_ids, limit
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        """2026-08-07 用于返回空原文候选"""
        del query, range_name, limit
        return []

    def fetch_active_case_details(self, case_id):
        """2026-08-07 用于表示测试中没有 active 案例"""
        del case_id
        return None


class _SequenceLLM:
    """2026-08-07 用于按顺序返回 Agent 消息的测试模型（仅 ainvoke，无流式）"""

    def __init__(self, responses: list[AIMessage]) -> None:
        """2026-08-07 用于保存待返回的模型消息序列"""
        self.responses = list(responses)
        self.calls = 0
        self.captured_messages: list[list] = []
        self.captured_tool_names: list[list[str]] = []

    def bind_tools(self, tools):
        """2026-08-30 用于记录每个模型回合实际绑定的工具合同"""
        self.captured_tool_names.append([tool.name for tool in tools])
        return self

    async def ainvoke(self, messages):
        """2026-08-07 用于返回下一条测试模型消息并记录输入"""
        self.calls += 1
        self.captured_messages.append(list(messages))
        return self.responses.pop(0)


def _tool_message(calls: list[dict]) -> AIMessage:
    """2026-08-07 用于构造带工具调用的模型回复"""
    return AIMessage(content="", tool_calls=calls)


def _write_call(
    name: str,
    args: dict,
    *,
    call_id: str,
) -> dict:
    """2026-08-07 用于构造单个工具调用"""
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _metrics_call(call_id: str = "call-metrics", *, sentence_labels: list[dict] | None = None) -> dict:
    """2026-08-07 用于构造合法 write_metrics 调用

    2026-09-07 句级监督：句标签随 write_metrics 的 sentence_labels 参数搭车
    （不设独立工具）；默认两句满足每章 2 句软下限。
    """
    payload = {
        "summary": "住手回荡",
        "emotional_valence": "neutral",
        "narrative_function": "铺垫",
    }
    if sentence_labels is not None:
        payload["sentence_labels"] = sentence_labels
    return _write_call("write_metrics", payload, call_id=call_id)


def _entities_call(call_id: str = "call-entities") -> dict:
    """2026-08-08 用于构造合法 write_entities 调用"""
    return _write_call(
        "write_entities",
        {
            "entities": [
                {
                    "name": "顾霜",
                    "entity_type": "character",
                }
            ]
        },
        call_id=call_id,
    )


def _dialogues_call(call_id: str = "call-dialogues") -> dict:
    """2026-08-12 用于构造数组格式的 write_dialogues 调用（[序号, 三态, 说话人, 语气]）"""
    return _write_call(
        "write_dialogues",
        {"items": [[1, "dialogue", None, "平静"]]},
        call_id=call_id,
    )


def _events_call(call_id: str = "call-events") -> dict:
    """2026-08-22 用于构造合法 create_event 调用（服务端派发 id）"""
    return _write_call(
        "create_event",
        {
            "description": "顾霜喝止众人",
            "participants": [
                {
                    "entity": "顾霜",
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝止",
                    "emotion": "mild_negative",
                }
            ],
            "finalize_events": True,
        },
        call_id=call_id,
    )


def _empty_domain_calls() -> list[dict]:
    """2026-08-07 用于构造剩余空领域的写入调用"""
    return [
        _write_call("write_relations", {"items": []}, call_id="call-relations"),
    ]


def _serial_write_messages(*, dialogues: dict | None = None) -> list[AIMessage]:
    """2026-08-30 用于按真实依赖和每轮至多两种 write 构造三轮正式写入回复"""
    resolved_dialogues = dialogues if dialogues is not None else _dialogues_call()
    return [
        _tool_message([_entities_call(), _metrics_call()]),
        _tool_message([_events_call(), *_empty_domain_calls()]),
        _tool_message(
            [
                resolved_dialogues,
                _metrics_call(
                    call_id="call-metrics-labels",
                    sentence_labels=[
                        {"sentence": "住手", "emotion": "strong_negative"},
                        {"sentence": "回荡", "emotion": "mild_negative"},
                    ],
                ),
            ]
        ),
    ]


async def _invoke_graph(
    llm: _SequenceLLM,
    *,
    allow_future_context: bool,
    chunk: tuple[int, str] | None = None,
    max_iterations: int = 30,
) -> dict:
    """2026-08-10 用于执行最小单 chunk 章节 LangGraph（消息链累积合同）"""
    resolved_chunk = chunk or (1, "“住手”回荡")
    chunk_id, chunk_text = resolved_chunk
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=chunk_id,
        current_chunk_text=chunk_text,
        allow_future_context=allow_future_context,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len(chunk_text))],
            texts=[chunk_text],
        ),
    )
    tools = build_annotation_tools(_QueryService(), ledger)
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=max_iterations,
    )
    return await graph.ainvoke(
        {
            "messages": [
                SystemMessage(content="test"),
                HumanMessage(
                    content=build_chunk_message(
                        chunk_index=1,
                        chunk_total=1,
                        chunk_text=chunk_text,
                        candidates=ledger.dialogue_candidates,
                    )
                ),
            ],
            "phase": "chunk_open",
            "iterations": 0,
            "error": None,
        }
    )


def _bound_annotation(*, summary: str = "顾霜进入山门") -> BoundChapterAnnotation:
    """2026-08-07 用于构造 Runner 重试测试的最小章节标注"""
    return BoundChapterAnnotation(
        chapter_summary=summary,
        chunks=[
            BoundChunkAnnotation(
                chunk_id=1,
                metrics=ChunkMetricsInput(
                    summary="顾霜进入山门",
                    emotional_valence="neutral",
                    narrative_function="铺垫",
                ),
                character_observations=[],
                dialogues=[],
                events=[],
                foreshadowings=[],
            )
        ],
    )


def _agent_result() -> AgentRunResult:
    """2026-08-10 用于构造 Runner 重试测试的完整成功结果（新审计结构）"""
    return AgentRunResult(
        run_id="run-1",
        chapter_id=1,
        annotation=_bound_annotation(),
        resolved_cases=[],
        pushed_cases=[],
        audit=AgentRunAudit(
            allow_future_context=False,
            write_records=[],
            rotation_case_ids=[],
            authorized_chapter_ids=[1],
            authorized_text_paragraph_ids=[],
        ),
    )


def _tool_receipts(captured_round: list) -> list[str]:
    """2026-08-10 用于提取某轮模型请求中的全部 ToolMessage 内容"""
    return [str(message.content) for message in captured_round if getattr(message, "type", "") == "tool"]


@pytest.mark.asyncio
async def test_second_write_entities_appends_to_catalog_not_replaces() -> None:
    """2026-08-26 回归（2026-09-04 单一写面改契约为 op log）：write_entities 追加语义必须落进 FactGraph

    契约允许模型分两次提交实体（先新实体、后补别名），op log 必须累积三次调用
    的声明，最终由持久化层合并为实体目录；不再有 bound_payloads["entities"]。
    """
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text="住手回荡",
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, 4)],
            texts=["住手回荡"],
        ),
    )
    tools = build_annotation_tools(_QueryService(), ledger)
    by_name = {tool.name: tool for tool in tools}
    await by_name["search_graph"].ainvoke({"entities": ["侯飞白", "褚大山", "猴子"]})
    await by_name["write_entities"].ainvoke(
        {
            "entities": [
                {"name": "侯飞白", "entity_type": "character", "description": "贺军情报头子之子"},
                {"name": "褚大山", "entity_type": "character"},
            ]
        }
    )
    await by_name["write_entities"].ainvoke(
        {
            "entities": [
                {"name": "猴子", "entity_type": "character", "description": "侯飞白外号"},
            ]
        }
    )
    await by_name["write_entities"].ainvoke(
        {
            "entities": [
                {"name": "侯飞白", "entity_type": "character", "tags": ["小孩"]},
            ]
        }
    )
    assert "entities" not in ledger.bound_payloads
    ops = ledger.graph.entity_ops
    assert [op["name"] for op in ops] == ["侯飞白", "褚大山", "猴子", "侯飞白"]
    assert ops[0]["description"] == "贺军情报头子之子"
    assert ops[3]["tags"] == ["小孩"]


@pytest.mark.asyncio
async def test_single_chunk_chapter_completes_via_write_and_auto_finalize() -> None:
    """2026-08-07 用于验证单 chunk 章节经领域写入后由系统自动冻结完成"""
    llm = _SequenceLLM(_serial_write_messages())
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3


def test_initial_case_number_table_injected_into_first_message() -> None:
    """2026-09-04 第7章死锁回归：初始案例编号表必须出现在首条 human 消息

    cb4f96f1 压缩提示词时删掉了编号表注入但保留编号授权机制，模型看不到
    编号便把对话候选 index 当 case_number，空转至回合上限。
    """
    from src.agents.annotation.schema import CaseSearchResult

    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text="住手回荡",
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, 4)],
            texts=["住手回荡"],
        ),
    )
    ledger.register_initial_cases(
        [
            CaseSearchResult(
                id="case-1",
                type="对话案例",
                chunk_id=0,
                keys=["说话人"],
                description="疑似对话：猴子瘫在游廊哀嚎",
            )
        ],
        ["case-1"],
    )
    message = build_chunk_message(
        chunk_index=1,
        chunk_total=1,
        chunk_text="住手回荡",
        candidates=ledger.dialogue_candidates,
        initial_cases=ledger.initial_case_views(),
    )
    assert "<ActiveCases>" in message
    assert '"case_number": 1' in message
    assert "疑似对话：猴子瘫在游廊哀嚎" in message


def test_dialogue_candidate_view_field_aligned_with_write_param() -> None:
    """2026-09-10 候选渲染字段名与 write_dialogues 参数名对齐

    旧字段名 index 与 ActiveCases 的 case_number 同为小整数，模型每章重新
    推理两套编号关系（run a83fae3d 思考实测映射推理 1725 次）；改名后
    candidate_index 与 write_dialogues 参数字面一致，映射自明。
    """
    chunk_text = "“住手”回荡"
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text=chunk_text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len(chunk_text))],
            texts=[chunk_text],
        ),
    )
    message = build_chunk_message(
        chunk_index=1,
        chunk_total=1,
        chunk_text=chunk_text,
        candidates=ledger.dialogue_candidates,
    )
    assert '"candidate_index": 1' in message
    assert '"index":' not in message


@pytest.mark.asyncio
async def test_turn_budget_reminder_injected_near_iteration_cap() -> None:
    """2026-09-05 第3章死锁回归：临近内部循环上限的请求必须携带收尾提醒

    ch3 空转 15 轮 40 次检索 0 写入后撞硬顶，模型全程看不到轮次预算。
    提醒只进本次请求、不写入状态消息链（否则历史中逐轮堆积）。
    """
    search_call = _write_call("search_pool", {"query": "伯安"}, call_id="call-search")
    llm = _SequenceLLM([_tool_message([search_call])] * 4)
    result = await _invoke_graph(llm, allow_future_context=True, max_iterations=4)

    assert result.get("error") == "annotation LangGraph 内部循环达到上限 4"
    assert len(llm.captured_messages) == 4
    for index, messages in enumerate(llm.captured_messages):
        reminders = [
            message
            for message in messages
            if isinstance(message, HumanMessage) and "轮次预算" in str(message.content)
        ]
        remaining = 4 - index
        if remaining <= 3:
            assert len(reminders) == 1, f"第 {index + 1} 次请求应恰好携带一条提醒"
            assert messages[-1] is reminders[0]
        else:
            assert reminders == [], "远离上限的请求不得携带提醒"
    assert "剩余 3 轮" in str(llm.captured_messages[1][-1].content)
    assert "最后一轮" in str(llm.captured_messages[3][-1].content)


@pytest.mark.asyncio
async def test_five_writes_make_auto_finalize_always_succeed() -> None:
    """2026-08-30 用于验证实体依赖就绪后其余 write 按每轮两种在三轮内完成"""
    llm = _SequenceLLM(_serial_write_messages())
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 3
    formal_writes = {"write_entities", "write_dialogues", "create_event", "write_relations", "write_metrics"}
    assert [
        [name for name in tool_names if name in formal_writes]
        for tool_names in llm.captured_tool_names
    ] == [
        ["write_entities", "write_metrics"],
        ["write_entities", "write_metrics", "create_event", "write_relations", "write_dialogues"],
        ["write_entities", "write_metrics", "create_event", "write_relations", "write_dialogues"],
    ]
    assert [len(messages) for messages in llm.captured_messages] == [2, 5, 8]


@pytest.mark.asyncio
async def test_cross_batch_write_calls_in_one_round_are_all_rejected() -> None:
    """2026-08-30 用于验证同一回复跨正式写入批次时全部拒绝且不推进当前批次"""
    llm = _SequenceLLM(
        [
            _tool_message([_entities_call(), _dialogues_call(), _metrics_call()]),
            *_serial_write_messages(),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 4
    receipts = _tool_receipts(llm.captured_messages[1])
    assert len(receipts) == 3
    assert all('"accepted": false' in receipt for receipt in receipts)
    assert all("本轮未开放工具" in receipt for receipt in receipts)
    assert "write_entities" in llm.captured_tool_names[0]
    assert "write_entities" in llm.captured_tool_names[1]


@pytest.mark.asyncio
async def test_failed_write_rolls_back_only_that_calls_revision() -> None:
    """2026-08-30 用于验证当前正式写入失败后保持原阶段并允许下一轮修正"""
    invalid_entities = _write_call(
        "write_entities",
        {
            "entities": [{"name": " ", "entity_type": "character"}],
        },
        call_id="call-entities-bad",
    )
    llm = _SequenceLLM(
        [
            _tool_message([invalid_entities]),
            *_serial_write_messages(),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 4
    receipts = _tool_receipts(llm.captured_messages[1])
    assert len(receipts) == 1
    assert '"accepted": false' in receipts[0]
    assert '"tool": "write_entities"' in receipts[0]
    assert "write_entities" in llm.captured_tool_names[0]
    assert "write_entities" in llm.captured_tool_names[1]


@pytest.mark.asyncio
async def test_failed_entity_write_delays_dependent_writes_until_accepted() -> None:
    """2026-08-30 用于验证实体失败不阻断指标，实体被接受后依赖工具解锁且此后只追加不回收"""
    invalid_entities = _write_call(
        "write_entities",
        {"entities": [{"name": " ", "entity_type": "character"}]},
        call_id="call-entities-invalid",
    )
    llm = _SequenceLLM(
        [
            _tool_message([invalid_entities, _metrics_call()]),
            _tool_message([_entities_call(call_id="call-entities-fixed")]),
            _tool_message([_events_call(), *_empty_domain_calls()]),
            _tool_message(
                [
                    _dialogues_call(),
                    _metrics_call(
                        call_id="call-metrics-labels",
                        sentence_labels=[
                            {"sentence": "住手", "emotion": "strong_negative"},
                            {"sentence": "回荡", "emotion": "mild_negative"},
                        ],
                    ),
                ]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 4
    formal_writes = {"write_entities", "write_dialogues", "create_event", "write_relations", "write_metrics"}
    assert [name for name in llm.captured_tool_names[0] if name in formal_writes] == [
        "write_entities",
        "write_metrics",
    ]
    assert [name for name in llm.captured_tool_names[1] if name in formal_writes] == [
        "write_entities",
        "write_metrics",
    ]
    assert [name for name in llm.captured_tool_names[2] if name in formal_writes] == [
        "write_entities",
        "write_metrics",
        "create_event",
        "write_relations",
        "write_dialogues",
    ]
    first_round_receipts = _tool_receipts(llm.captured_messages[1])[-2:]
    assert '"tool": "write_entities"' in first_round_receipts[0]
    assert '"accepted": false' in first_round_receipts[0]
    assert '"domain": "metrics"' in first_round_receipts[1]
    assert '"accepted": true' in first_round_receipts[1]


@pytest.mark.asyncio
async def test_partial_writes_do_not_auto_finalize() -> None:
    """2026-08-30 用于验证非末事件树不阻断同轮独立关系写入且事件阶段保持开放"""
    first_event = _events_call(call_id="call-events-first")
    first_event["args"]["finalize_events"] = False
    second_event = _write_call(
        "create_event",
        {
            "description": "顾霜收势",
            "participants": [
                {
                    "entity": "顾霜",
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "收势",
                    "emotion": "neutral",
                }
            ],
            "finalize_events": True,
        },
        call_id="call-events-final",
    )
    llm = _SequenceLLM(
        [
            _tool_message([_entities_call(), _metrics_call()]),
            _tool_message([first_event, *_empty_domain_calls()]),
            _tool_message(
                [
                    second_event,
                    _dialogues_call(),
                    _metrics_call(
                        call_id="call-metrics-labels",
                        sentence_labels=[
                            {"sentence": "住手", "emotion": "strong_negative"},
                            {"sentence": "回荡", "emotion": "mild_negative"},
                        ],
                    ),
                ]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3
    assert [name for name in llm.captured_tool_names[1] if name in {"create_event", "write_relations"}] == [
        "create_event",
        "write_relations",
    ]
    assert [name for name in llm.captured_tool_names[2] if name in {"create_event", "write_relations"}] == [
        "create_event",
        "write_relations",
    ]


@pytest.mark.asyncio
async def test_three_create_event_calls_and_relation_write_succeed_in_one_round() -> None:
    """2026-08-30 用于验证一轮可重复调用三次 create_event 并独立提交关系写入"""
    first_event = _events_call(call_id="call-events-first")
    first_event["args"]["finalize_events"] = False
    second_event = _events_call(call_id="call-events-second")
    second_event["args"]["description"] = "顾霜追击"
    second_event["args"]["participants"][0]["action"] = "追击"
    second_event["args"]["finalize_events"] = False
    final_event = _events_call(call_id="call-events-final")
    final_event["args"]["description"] = "顾霜收势"
    final_event["args"]["participants"][0]["action"] = "收势"
    llm = _SequenceLLM(
        [
            _tool_message([_entities_call(), _metrics_call()]),
            _tool_message([first_event, second_event, final_event, *_empty_domain_calls()]),
            _tool_message(
                [
                    _dialogues_call(),
                    _metrics_call(
                        call_id="call-metrics-labels",
                        sentence_labels=[
                            {"sentence": "住手", "emotion": "strong_negative"},
                            {"sentence": "回荡", "emotion": "mild_negative"},
                        ],
                    ),
                ]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3
    event_round_receipts = _tool_receipts(llm.captured_messages[2])[-4:]
    assert sum('"tool": "create_event"' in receipt for receipt in event_round_receipts) == 3
    assert all('"accepted": true' in receipt for receipt in event_round_receipts)
    assert '"domain": "relations"' in event_round_receipts[-1]


@pytest.mark.asyncio
async def test_failed_event_write_does_not_block_relation_write_in_same_round() -> None:
    """2026-08-30 用于验证事件写入失败时同轮关系写入仍独立执行并保留成功回执"""
    invalid_event = _events_call(call_id="call-events-invalid")
    invalid_event["args"]["participants"][0]["role"] = "发送者"
    llm = _SequenceLLM(
        [
            _tool_message([_entities_call(), _metrics_call()]),
            _tool_message([invalid_event, *_empty_domain_calls()]),
            _tool_message(
                [
                    _events_call(call_id="call-events-fixed"),
                    _dialogues_call(),
                    _metrics_call(
                        call_id="call-metrics-labels",
                        sentence_labels=[
                            {"sentence": "住手", "emotion": "strong_negative"},
                            {"sentence": "回荡", "emotion": "mild_negative"},
                        ],
                    ),
                ]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3
    event_round_receipts = _tool_receipts(llm.captured_messages[2])[-2:]
    assert '"tool": "create_event"' in event_round_receipts[0]
    assert '"accepted": false' in event_round_receipts[0]
    assert '"domain": "relations"' in event_round_receipts[1]
    assert '"accepted": true' in event_round_receipts[1]


@pytest.mark.asyncio
async def test_truncated_tool_call_skips_business_tool_and_feeds_error_receipt() -> None:
    """
    2026-08-11 用于验证带截断标记的工具调用不执行业务写入，
    只回喂"参数不完整"错误回执，模型补全后章节仍能完成。
    """
    truncated_entities = {
        "name": "write_entities",
        "args": {},
        "id": "call-entities-truncated",
        "type": "tool_call",
        "truncated": True,
        "truncated_args": '{"entities": [{"name": "顾霜"',
    }
    # 聚合器在运行时以属性赋值挂载截断标记（绕过 create_tool_call 重建），测试同样模拟
    first_message = AIMessage(content="")
    first_message.tool_calls = [truncated_entities]
    llm = _SequenceLLM(
        [
            first_message,
            *_serial_write_messages(),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 4
    receipts = _tool_receipts(llm.captured_messages[1])
    rejected = [receipt for receipt in receipts if '"accepted": false' in receipt]
    accepted = [receipt for receipt in receipts if '"accepted": true' in receipt]
    assert len(rejected) == 1
    assert len(accepted) == 0
    assert '"tool": "write_entities"' in rejected[0]
    assert "截断" in rejected[0]


@pytest.mark.asyncio
async def test_auto_finalize_invariant_error_terminates_chapter() -> None:
    """2026-08-10 用于验证 receipt 齐全但 ready_chunk 缺失时按不变量错误终止而非回环修正"""
    llm = _SequenceLLM(_serial_write_messages())

    class _BrokenLedger(AnnotationToolLedger):
        """2026-08-30 用于模拟六领域回执齐全但 ready_chunk 被破坏"""

        def _rebuild_ready_chunk_if_complete(self) -> None:
            super()._rebuild_ready_chunk_if_complete()
            self.ready_chunk = None

    chunk_id, chunk_text = 1, "\u201c住手\u201d回荡"
    ledger = _BrokenLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=chunk_id,
        current_chunk_text=chunk_text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len(chunk_text))],
            texts=[chunk_text],
        ),
    )
    tools = build_annotation_tools(_QueryService(), ledger)
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=30,
    )
    with pytest.raises(AnnotationInvariantError, match="ready_chunk 缺失"):
        await graph.ainvoke(
            {
                "messages": [
                    SystemMessage(content="test"),
                    HumanMessage(
                        content=build_chunk_message(
                            chunk_index=1,
                            chunk_total=1,
                            chunk_text=chunk_text,
                            candidates=ledger.dialogue_candidates,
                        )
                    ),
                ],
                "phase": "chunk_open",
                "iterations": 0,
                "error": None,
            }
        )
    assert llm.calls == 3
    assert ledger.annotation is None
    assert ledger.completed_chunks == []


def test_validate_bound_annotation_requires_exact_chunk_order() -> None:
    """2026-08-07 用于验证系统绑定 chunks 必须精确覆盖 current"""
    annotation = _bound_annotation()
    with pytest.raises(ValueError, match="必须按原文顺序精确覆盖"):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            current_chunks=[(2, "另一个原文")],
        )


def test_validate_bound_annotation_verifies_dialogue_original_text() -> None:
    """2026-08-07 用于验证对话原文位置与内容由系统绑定且可回查"""
    annotation = _bound_annotation()
    chunk = annotation.chunks[0]
    chunk.dialogues = [
        BoundDialogue(
            candidate_index=1,
            candidate_key="dlg_1",
            content="住手",
            start=0,
            end=2,
        )
    ]
    with pytest.raises(ValueError, match="系统对话原文绑定不一致"):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            current_chunks=[(1, "顾霜进入山门")],
        )


@pytest.mark.asyncio
async def test_runner_single_failure_raises_without_chapter_retry() -> None:
    """2026-08-11 用于验证章节不再整章重试：单次失败直接抛异常且只使用一个只读 Session"""
    session = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(side_effect=RuntimeError("model failed")),
    ) as run_attempt:
        with pytest.raises(RuntimeError, match="model failed"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                current_chunks=[(1, "顾霜进入山门")],
                query_service_factory=lambda session: _QueryService(),
                session_factory=lambda: session,
                llm=MagicMock(),
                audit_recorder=MagicMock(),
            )
    assert run_attempt.await_count == 1


@pytest.mark.asyncio
async def test_runner_does_not_retry_authorization_errors() -> None:
    """2026-08-07 用于验证授权错误直接失败且不会进入第二次尝试"""
    session = MagicMock()
    recorder = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(side_effect=AnnotationAuthorizationError("unauthorized")),
    ) as run_attempt:
        with pytest.raises(AnnotationAuthorizationError, match="unauthorized"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                current_chunks=[(1, "顾霜进入山门")],
                query_service_factory=lambda current: _QueryService(),
                session_factory=lambda: session,
                llm=MagicMock(),
                audit_recorder=recorder,
            )
    assert run_attempt.await_count == 1
    session.rollback.assert_called_once()
    session.close.assert_called_once()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "error"


@pytest.mark.asyncio
async def test_runner_records_single_error_invocation() -> None:
    """2026-08-11 用于验证单次失败开启并收口一条 error 审计 invocation"""
    session = MagicMock()
    recorder = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                current_chunks=[(1, "顾霜进入山门")],
                query_service_factory=lambda session: _QueryService(),
                session_factory=lambda: session,
                llm=MagicMock(),
                audit_recorder=recorder,
            )
    assert recorder.start_invocation.call_count == 1
    assert recorder.start_invocation.call_args.kwargs["attempt_number"] == 1
    finish_calls = recorder.finish_invocation.call_args_list
    assert len(finish_calls) == 1
    assert finish_calls[0].kwargs["status"] == "error"
    assert "boom" in str(finish_calls[0].kwargs.get("final_error", ""))


@pytest.mark.asyncio
async def test_runner_returns_result_from_single_attempt() -> None:
    """2026-08-11 用于验证单次尝试成功即返回并收口 success 审计"""
    result = _agent_result()
    session = MagicMock()
    recorder = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(return_value=result),
    ) as run_attempt:
        actual = await run_annotation_agent(
            run_id="run-1",
            chapter_id=1,
            current_chunks=[(1, "顾霜进入山门")],
            query_service_factory=lambda session: _QueryService(),
            session_factory=lambda: session,
            llm=MagicMock(),
            audit_recorder=recorder,
        )
    assert actual == result
    assert run_attempt.await_count == 1
    assert recorder.finish_invocation.call_args.kwargs["status"] == "success"


@pytest.mark.asyncio
async def test_runner_accepts_multiple_sub_chunk_entries_and_negative_ids() -> None:
    """2026-08-14 M7（§20）用于验证多 chunk 输入与负子块 ID 通过章节身份校验"""
    session = MagicMock()
    result = _agent_result()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(return_value=result),
    ) as run_attempt:
        actual = await run_annotation_agent(
            run_id="run-1",
            chapter_id=1,
            current_chunks=[(-1, "第一个子块"), (-2, "第二个子块")],
            query_service_factory=lambda session: _QueryService(),
            session_factory=lambda: session,
            llm=MagicMock(),
            audit_recorder=MagicMock(),
        )
    assert actual == result
    assert run_attempt.await_count == 1


@pytest.mark.asyncio
async def test_runner_rejects_empty_chunk_text_entry() -> None:
    """2026-08-14 M7 用于验证逐条校验子块原文非空"""
    session = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(return_value=_agent_result()),
    ) as run_attempt:
        with pytest.raises(AnnotationInputError, match="原文不能为空"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                current_chunks=[(-1, "   ")],
                query_service_factory=lambda session: _QueryService(),
                session_factory=lambda: session,
                llm=MagicMock(),
                audit_recorder=MagicMock(),
            )
    assert run_attempt.await_count == 0


@pytest.mark.asyncio
async def test_runner_forwards_sub_chunk_index_to_attempt() -> None:
    """2026-08-14 M7（§20）用于验证 sub_chunk_index 透传到底层尝试"""
    session = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(return_value=_agent_result()),
    ) as run_attempt:
        await run_annotation_agent(
            run_id="run-1",
            chapter_id=1,
            current_chunks=[(-2, "第二个子块")],
            sub_chunk_index=1,
            query_service_factory=lambda session: _QueryService(),
            session_factory=lambda: session,
            llm=MagicMock(),
            audit_recorder=MagicMock(),
        )
    assert run_attempt.call_args.kwargs["sub_chunk_index"] == 1


def test_validate_bound_annotation_covers_multiple_sub_chunks() -> None:
    """2026-08-14 M7 用于验证多条目 current 按子块 ID 精确覆盖且对话按各自原文绑定"""
    first = BoundChunkAnnotation(
        chunk_id=-1,
        metrics=ChunkMetricsInput(
            summary="第一子块",
            emotional_valence="neutral",
            narrative_function="铺垫",
        ),
        character_observations=[],
        dialogues=[
            BoundDialogue(
                candidate_index=1,
                candidate_key="dlg_1",
                content="住手",
                start=0,
                end=2,
            )
        ],
        events=[],
        foreshadowings=[],
    )
    second = BoundChunkAnnotation(
        chunk_id=-2,
        metrics=ChunkMetricsInput(
            summary="第二子块",
            emotional_valence="neutral",
            narrative_function="铺垫",
        ),
        character_observations=[],
        dialogues=[
            BoundDialogue(
                candidate_index=1,
                candidate_key="dlg_2",
                content="退下",
                start=0,
                end=2,
            )
        ],
        events=[],
        foreshadowings=[],
    )
    annotation = BoundChapterAnnotation(
        chapter_summary="子块合并摘要",
        chunks=[first, second],
    )
    validate_bound_annotation(
        annotation,
        chapter_id=1,
        current_chunks=[(-1, "住手喝止"), (-2, "退下众人")],
    )
    # 顺序错位仍被拒绝
    with pytest.raises(ValueError, match="必须按原文顺序精确覆盖"):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            current_chunks=[(-2, "退下众人"), (-1, "住手喝止")],
        )


class _AliasCaseQueryService(_QueryService):
    """2026-08-12 用于提供 entity_alias 活动案例的图级测试查询桩"""

    def _alias_case(self) -> CaseSearchResult:
        return CaseSearchResult(
            id="alias-1",
            type="entity_alias",
            chunk_id=1,
            keys=["同一人物", "顾霜", "顾老"],
            description="疑似同一人物：顾霜 与 顾老",
        )

    def find_initial_case_candidates(
        self,
        current_text,
        *,
        semantic_limit=50,
        rotation_limit=50,
    ):
        del current_text, semantic_limit, rotation_limit
        return [self._alias_case()], ["alias-1"]

    def fetch_active_case_details(self, case_id):
        del case_id
        return ActiveCaseDetails(
            **self._alias_case().model_dump(mode="python"),
            target_key="target-alias-1",
            target_ref={"kind": "alias", "name_a": "顾霜", "name_b": "顾老", "chunk_id": 1},
        )


def _resolve_fact_case_call(call_id: str = "call-fact") -> dict:
    """2026-08-12 用于构造带非法 change_kind 的 resolve_fact_case 调用"""
    return _write_call(
        "resolve_fact_case",
        {
            "case_number": 1,
            "from_entity": "顾霜",
            "to_entity": "顾老",
            "relation_type": "同一人物",
            "change_kind": "强化关系",
            "reason": "指向同一人",
        },
        call_id=call_id,
    )


@pytest.mark.asyncio
async def test_resolve_fact_case_invalid_change_kind_returns_failed_receipt() -> None:
    """
    2026-08-12 用于验证非法 change_kind 以失败回执回到模型继续对话，
    而不是抛出让整章失败（下游持久化只认闭合枚举）。
    """
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text="\u201c住手\u201d回荡",
        allow_future_context=False,
        graph=FactGraph(
            history_entity_types={"顾霜": "character", "顾老": "character"},
            history_entity_names={"顾霜": "顾霜", "顾老": "顾老"},
        ),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len("\u201c住手\u201d回荡"))],
            texts=["\u201c住手\u201d回荡"],
        ),
    )
    ledger.graph_queried = True
    service = _AliasCaseQueryService()
    initial_cases, rotation_ids = service.find_initial_case_candidates("当前")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = build_annotation_tools(service, ledger)
    llm = _SequenceLLM(
        [
            _tool_message([_resolve_fact_case_call()]),
            *_serial_write_messages(),
        ]
    )
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=30,
    )
    result = await graph.ainvoke(
        {
            "messages": [
                SystemMessage(content="test"),
                HumanMessage(
                    content=build_chunk_message(
                        chunk_index=1,
                        chunk_total=1,
                        chunk_text="“住手”回荡",
                        candidates=ledger.dialogue_candidates,
                    )
                ),
            ],
            "phase": "chunk_open",
            "iterations": 0,
            "error": None,
        }
    )

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 4
    receipts = _tool_receipts(llm.captured_messages[1])
    rejected = [receipt for receipt in receipts if '"accepted": false' in receipt]
    assert len(rejected) == 1
    assert '"tool": "resolve_fact_case"' in rejected[0]
    assert "change_kind" in rejected[0]
    assert ledger.resolved_cases == []


@pytest.mark.asyncio
async def test_runner_resets_fact_graph_chapter_state_on_failure() -> None:
    """2026-08-12 用于验证章节失败路径恢复 FactGraph 历史快照，不残留当章脏状态

    2026-08-13 P1-1：begin_chapter 把章前状态并入 history_*，失败回滚恢复到
    「本章开始前」快照（上一章提交结果），而非 run 启动空状态。
    """
    graph_state = FactGraph(
        history_entity_types={"顾霜": "character"},
        history_entity_names={"顾霜": "顾霜"},
        history_relations={("顾霜", "顾老", "同一人物")},
    )
    assert graph_state.active_relations
    session = MagicMock()
    recorder = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(side_effect=RuntimeError("model failed")),
    ):
        with pytest.raises(RuntimeError, match="model failed"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                current_chunks=[(1, "顾霜进入山门")],
                query_service_factory=lambda session: _QueryService(),
                session_factory=lambda: session,
                llm=MagicMock(),
                audit_recorder=recorder,
                graph_state=graph_state,
            )
    # 失败后恢复到本章开始前快照：上一章提交的边与实体保留，章内追踪清空
    # （active_relations 按稳定键归一化，端点按字典序）
    assert graph_state.active_relations == {("顾老", "顾霜", "同一人物")}
    assert graph_state.chapter_added_relations == set()
    assert graph_state.entity_types == {"顾霜": "character"}


def test_validate_bound_annotation_verifies_sentence_label_spans() -> None:
    """2026-09-07 用于验证句标签坐标与原文绑定一致可回查"""
    annotation = _bound_annotation()
    chunk = annotation.chunks[0]
    chunk.sentence_labels = [
        BoundSentenceLabel(sentence="住手", emotion=EmotionalValence.NEUTRAL, start=3, end=5)
    ]
    validate_bound_annotation(
        annotation,
        chapter_id=1,
        current_chunks=[(1, "顾霜“住手”回荡")],
    )
    mismatched = BoundSentenceLabel(sentence="住手", emotion=EmotionalValence.NEUTRAL, start=0, end=2)
    chunk.sentence_labels = [mismatched]
    with pytest.raises(ValueError, match="系统自选句绑定不一致"):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            current_chunks=[(1, "顾霜“住手”回荡")],
        )


@pytest.mark.asyncio
async def test_graph_reinjects_missing_domain_hint_after_plain_text_reply(monkeypatch) -> None:
    """2026-09-08 用于验证模型纯文本汇报后被重发请求带上缺域提醒并补齐写入

    第13章死锁回归：模型写完 entities+metrics 后改用纯文本汇报，
    调用层重发时注入缺域清单，模型据此补齐剩余领域，章节正常完成。
    """
    async def _skip_sleep(_seconds: float) -> None:
        """2026-09-08 用于跳过重试退避等待"""

    monkeypatch.setattr("src.agents.stream.asyncio.sleep", _skip_sleep)
    llm = _SequenceLLM(
        [
            _tool_message([_entities_call(), _metrics_call()]),
            AIMessage(content="本章语义标注已完成，汇总如下……"),
            _tool_message(
                [
                    _events_call(),
                    _write_call("write_relations", {"items": []}, call_id="call-relations"),
                ]
            ),
            _tool_message(
                [
                    _dialogues_call(),
                    _metrics_call(
                        call_id="call-metrics-labels",
                        sentence_labels=[
                            {"sentence": "住手", "emotion": "strong_negative"},
                            {"sentence": "回荡", "emotion": "mild_negative"},
                        ],
                    ),
                ]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=True)

    assert result["error"] is None
    assert llm.calls == 4
    # 重发请求（第 3 次调用）末尾是缺域提醒，指出剩余领域与补齐写法
    resent = llm.captured_messages[2]
    last = resent[-1]
    assert isinstance(last, HumanMessage)
    assert "缺域提醒" in str(last.content)
    assert "relations" in str(last.content) and "dialogues" in str(last.content)
    # 首次请求与状态消息链都不含提醒：注入只对重发请求生效
    assert all("缺域提醒" not in str(m.content) for m in llm.captured_messages[1])
    assert all("缺域提醒" not in str(m.content) for m in result["messages"])
