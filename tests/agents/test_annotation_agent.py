"""章节级标注 Agent 逐 chunk LangGraph 与 Runner 测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.annotation.errors import AnnotationAuthorizationError
from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.prompts import build_chunk_message
from src.agents.annotation.runner import (
    AnnotationAgentRunError,
    run_annotation_agent,
    validate_bound_annotation,
)
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEntityDirectory,
    ChunkMetricsInput,
    SuccessAudit,
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

    def search_graph(self, query, *, limit=50):
        """2026-08-07 用于返回无上一章节图版本"""
        del query, limit
        return None

    async def search_text(self, query, *, range_name, limit=50):
        """2026-08-07 用于返回空原文候选"""
        del query, range_name, limit
        return []

    def read_text(self, chunk_id):
        """2026-08-07 用于返回测试原文"""
        del chunk_id
        return "后文"

    def fetch_active_case_details(self, case_id):
        """2026-08-07 用于表示测试中没有 active 案例"""
        del case_id
        return None


class _SequenceLLM:
    """2026-08-07 用于按顺序返回 Agent 消息的测试模型"""

    def __init__(self, responses: list[AIMessage]) -> None:
        """2026-08-07 用于保存待返回的模型消息序列"""
        self.responses = list(responses)
        self.calls = 0
        self.captured_messages: list[list] = []

    def bind_tools(self, tools):
        """2026-08-07 用于模拟 LangChain 工具绑定"""
        del tools
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


def _metrics_call(call_id: str = "call-metrics") -> dict:
    """2026-08-07 用于构造合法 write_metrics 调用"""
    return _write_call(
        "write_metrics",
        {
            "summary": "住手回荡",
            "emotional_valence": "neutral",
            "narrative_function": "铺垫",
            "confidence": "high",
            "reason": "本章开端",
        },
        call_id=call_id,
    )


def _entities_call(call_id: str = "call-entities") -> dict:
    """2026-08-08 用于构造合法 write_entities 调用"""
    return _write_call(
        "write_entities",
        {
            "entities": [
                {
                    "name": "顾霜",
                    "entity_type": "character",
                    "confidence": "high",
                    "reason": "人物出现",
                }
            ]
        },
        call_id=call_id,
    )


def _observations_call(call_id: str = "call-observations") -> dict:
    """2026-08-07 用于构造合法 write_character_observations 调用"""
    return _write_call(
        "write_character_observations",
        {
            "items": [
                {
                    "character": "顾霜",
                    "role_function": "主体",
                    "action": "喝止",
                    "action_type": "对话",
                    "emotion": "mild_negative",
                    "confidence": "high",
                    "reason": "顾霜喝止",
                }
            ]
        },
        call_id=call_id,
    )


def _dialogues_call(call_id: str = "call-dialogues") -> dict:
    """2026-08-07 用于构造按候选顺序的 write_dialogues 调用"""
    return _write_call(
        "write_dialogues",
        {
            "items": [
                {
                    "is_dialogue": True,
                    "description": "喝止住手",
                    "speaker": None,
                    "confidence": "high",
                    "reason": "原文双引号",
                }
            ]
        },
        call_id=call_id,
    )


def _events_call(call_id: str = "call-events") -> dict:
    """2026-08-07 用于构造合法 write_events 调用"""
    return _write_call(
        "write_events",
        {
            "items": [
                {
                    "description": "顾霜喝止众人",
                    "participants": [{"entity": "顾霜", "participation": "主体"}],
                    "confidence": "high",
                    "reason": "喝止事件",
                }
            ]
        },
        call_id=call_id,
    )


def _empty_domain_calls() -> list[dict]:
    """2026-08-07 用于构造剩余三个空领域的写入调用"""
    return [
        _write_call("write_relations", {"items": []}, call_id="call-relations"),
        _write_call("write_states", {"items": []}, call_id="call-states"),
        _write_call("write_foreshadowings", {"items": []}, call_id="call-foreshadowings"),
    ]


def _full_write_calls(
    *,
    dialogues: dict | None = None,
) -> list[dict]:
    """2026-08-07 用于构造同一回复的全部八个领域写入调用"""
    resolved_dialogues = dialogues if dialogues is not None else _dialogues_call()
    return [
        _metrics_call(),
        _entities_call(),
        _observations_call(),
        resolved_dialogues,
        _events_call(),
        *_empty_domain_calls(),
    ]


async def _invoke_graph(
    llm: _SequenceLLM,
    *,
    allow_future_context: bool,
    chunk: tuple[int, str] | None = None,
    max_iterations: int = 30,
) -> dict:
    """2026-08-07 用于执行最小单 chunk 章节 LangGraph"""
    resolved_chunk = chunk or (1, "“住手”回荡")
    chunk_id, chunk_text = resolved_chunk
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=chunk_id,
        current_chunk_text=chunk_text,
        allow_future_context=allow_future_context,
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


def evidence(reason: str, chunk_id: int) -> list[dict]:
    """2026-08-07 用于构造系统文本依据"""
    return [{"reason": reason, "chunk_id": chunk_id}]


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
                    confidence="high",
                    reason="进入",
                ),
                entities=BoundEntityDirectory(),
                character_observations=[],
                dialogues=[],
                events=[],
                relations=[],
                states=[],
                foreshadowings=[],
            )
        ],
    )


def _agent_result() -> AgentRunResult:
    """2026-08-07 用于构造 Runner 重试测试的完整成功结果"""
    return AgentRunResult(
        run_id="run-1",
        chapter_id=1,
        annotation=_bound_annotation(),
        resolved_cases=[],
        pending_cases=[],
        audit=AgentRunAudit(
            allow_future_context=False,
            write_revisions=[],
            rotation_case_ids=[],
            authorized_text_chunk_ids=[1],
            success=SuccessAudit(
                attempt_number=1,
                messages=[],
                tool_calls=[],
                model_provider="local",
                duration_ms=1,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_single_chunk_chapter_completes_via_write_and_finalizers() -> None:
    """2026-08-07 用于验证单 chunk 章节经领域写入和单独完成工具冻结"""
    llm = _SequenceLLM(
        [
            _tool_message(_full_write_calls()),
            _tool_message([_write_call("complete_chunk", {}, call_id="call-complete")]),
            _tool_message(
                [_write_call("finish_chapter", {"chapter_summary": "顾霜喝止众人"}, call_id="call-finish")]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3


@pytest.mark.asyncio
async def test_batch_failure_rolls_back_then_recovers_with_new_revisions() -> None:
    """2026-08-07 用于验证同轮失败整体回滚且重新提交后从修订 1 开始"""
    invalid_entities = _write_call(
        "write_entities",
        {
            "entities": [
                {"name": "顾霜", "entity_type": "character", "confidence": "certain", "reason": "非法置信度"}
            ]
        },
        call_id="call-entities-bad",
    )
    llm = _SequenceLLM(
        [
            _tool_message([_metrics_call(), invalid_entities]),
            _tool_message(_full_write_calls()),
            _tool_message([_write_call("complete_chunk", {}, call_id="call-complete")]),
            _tool_message(
                [_write_call("finish_chapter", {"chapter_summary": "回滚后恢复"}, call_id="call-finish")]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 4
    rolled_back_messages = llm.captured_messages[1]
    assert any("已整体回滚" in str(message.content) for message in rolled_back_messages)


@pytest.mark.asyncio
async def test_protocol_error_rejects_mixed_finalizer_calls() -> None:
    """2026-08-07 用于验证 complete_chunk 与 finish_chapter 不能同轮调用"""
    llm = _SequenceLLM(
        [
            _tool_message(
                [
                    _write_call("complete_chunk", {}, call_id="call-complete"),
                    _write_call("finish_chapter", {"chapter_summary": "混合"}, call_id="call-finish"),
                ]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "chunk_open"
    assert "必须单独调用" in str(result["error"])


@pytest.mark.asyncio
async def test_protocol_error_rejects_plain_text_reply() -> None:
    """2026-08-07 用于验证无工具回复不能推进章节"""
    llm = _SequenceLLM([AIMessage(content="已经完成")])
    result = await _invoke_graph(llm, allow_future_context=False)

    assert "annotation 工具协议错误" in str(result["error"])


@pytest.mark.asyncio
async def test_future_disabled_batch_rollback_keeps_ledger_untouched() -> None:
    """2026-08-07 用于验证禁止 future 时整批回滚且账本保持未写入"""
    future_call = _write_call(
        "search_text",
        {"query": "顾霜", "range": "future"},
        call_id="call-future",
    )
    llm = _SequenceLLM(
        [
            _tool_message([future_call]),
            _tool_message(_full_write_calls()),
            _tool_message([_write_call("complete_chunk", {}, call_id="call-complete")]),
            _tool_message(
                [_write_call("finish_chapter", {"chapter_summary": "拒绝后文"}, call_id="call-finish")]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 4
    assert any("已整体回滚" in str(message.content) for message in llm.captured_messages[1])


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
            candidate_key="dlg_1",
            content="住手",
            start=0,
            end=2,
            description="喝止",
            confidence="high",
            reason="原文",
            evidence=evidence("原文", 1),
        )
    ]
    with pytest.raises(ValueError, match="系统对话原文绑定不一致"):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            current_chunks=[(1, "顾霜进入山门")],
        )


@pytest.mark.asyncio
async def test_runner_stops_after_third_retryable_failure() -> None:
    """2026-08-07 用于验证第三次失败后终止且每次使用全新只读 Session"""
    sessions = [MagicMock(), MagicMock(), MagicMock()]
    with (
        patch(
            "src.agents.annotation.runner._run_single_attempt",
            new=AsyncMock(side_effect=RuntimeError("model failed")),
        ) as run_attempt,
        patch("src.agents.annotation.runner.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        with pytest.raises(AnnotationAgentRunError, match="连续 3 次失败"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                current_chunks=[(1, "顾霜进入山门")],
                query_service_factory=lambda session: _QueryService(),
                session_factory=lambda: sessions.pop(0),
                llm=MagicMock(),
            )
    assert run_attempt.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_runner_does_not_retry_authorization_errors() -> None:
    """2026-08-07 用于验证授权错误直接失败且不会进入第二次尝试"""
    session = MagicMock()
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
            )
    assert run_attempt.await_count == 1
    session.rollback.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.asyncio
async def test_runner_retries_then_returns_successful_third_attempt() -> None:
    """2026-08-07 用于验证可重试错误后返回第三次成功结果"""
    result = _agent_result()
    sessions = [MagicMock(), MagicMock(), MagicMock()]
    llm = MagicMock()
    with (
        patch(
            "src.agents.annotation.runner._run_single_attempt",
            new=AsyncMock(side_effect=[RuntimeError("one"), RuntimeError("two"), result]),
        ) as run_attempt,
        patch("src.agents.annotation.runner.asyncio.sleep", new=AsyncMock()),
    ):
        actual = await run_annotation_agent(
            run_id="run-1",
            chapter_id=1,
            current_chunks=[(1, "顾霜进入山门")],
            query_service_factory=lambda session: _QueryService(),
            session_factory=lambda: sessions.pop(0),
            llm=llm,
        )
    assert actual == result
    assert run_attempt.await_count == 3
