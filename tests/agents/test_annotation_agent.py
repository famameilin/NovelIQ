"""章节级标注 Agent 逐 chunk LangGraph 与 Runner 测试（独立提交 + 上下文上界）"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.annotation.errors import AnnotationAuthorizationError, AnnotationInvariantError
from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.prompts import build_chunk_message
from src.agents.annotation.runner import (
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

    def read_text(self, chunk_id):
        """2026-08-07 用于返回测试原文"""
        del chunk_id
        return "后文"

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
                    "emotion": "mild_negative",
                }
            ]
        },
        call_id=call_id,
    )


def _dialogues_call(call_id: str = "call-dialogues") -> dict:
    """2026-08-07 用于构造按候选序号的 write_dialogues 调用（完整覆盖 1..N）"""
    return _write_call(
        "write_dialogues",
        {
            "items": [
                {
                    "candidate_index": 1,
                    "verdict": "dialogue",
                    "speaker": None,
                    "tone": "平静",
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
                    "participants": [{"entity": "顾霜", "role": "行动者"}],
                }
            ]
        },
        call_id=call_id,
    )


def _empty_domain_calls() -> list[dict]:
    """2026-08-07 用于构造剩余两个空领域的写入调用"""
    return [
        _write_call("write_relations", {"items": []}, call_id="call-relations"),
        _write_call("write_foreshadowings", {"items": []}, call_id="call-foreshadowings"),
    ]


def _full_write_calls(
    *,
    dialogues: dict | None = None,
) -> list[dict]:
    """2026-08-07 用于构造同一回复的全部七个领域写入调用"""
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
    """2026-08-10 用于执行最小单 chunk 章节 LangGraph（消息链累积合同）"""
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
                entities=BoundEntityDirectory(),
                character_observations=[],
                dialogues=[],
                events=[],
                relations=[],
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
            write_revisions=[],
            rotation_case_ids=[],
            authorized_text_chunk_ids=[1],
        ),
    )


def _tool_receipts(captured_round: list) -> list[str]:
    """2026-08-10 用于提取某轮模型请求中的全部 ToolMessage 内容"""
    return [
        str(message.content)
        for message in captured_round
        if getattr(message, "type", "") == "tool"
    ]


@pytest.mark.asyncio
async def test_single_chunk_chapter_completes_via_write_and_auto_finalize() -> None:
    """2026-08-07 用于验证单 chunk 章节经领域写入后由系统自动冻结完成"""
    llm = _SequenceLLM(
        [
            _tool_message(_full_write_calls()),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_seven_writes_make_auto_finalize_always_succeed() -> None:
    """2026-08-10 用于验证七个 write 全部成功后系统自动冻结并完成章节"""
    llm = _SequenceLLM(
        [
            _tool_message(_full_write_calls()),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_six_success_one_failure_keeps_six_receipts() -> None:
    """2026-08-10 用于验证一个 write 失败只回滚该调用，其余六个 receipt 全部保留"""
    invalid_metrics = _write_call(
        "write_metrics",
        {
            "summary": " ",
            "emotional_valence": "neutral",
            "narrative_function": "铺垫",
        },
        call_id="call-metrics-bad",
    )
    llm = _SequenceLLM(
        [
            _tool_message(
                [
                    _entities_call(),
                    _observations_call(),
                    _dialogues_call(),
                    _events_call(),
                    _write_call("write_relations", {"items": []}, call_id="call-relations"),
                    invalid_metrics,
                    _write_call(
                        "write_foreshadowings",
                        {"items": []},
                        call_id="call-foreshadowings",
                    ),
                ]
            ),
            _tool_message(
                [
                    _metrics_call(call_id="call-metrics-fixed"),
                ]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 2
    receipts = _tool_receipts(llm.captured_messages[1])
    accepted = [receipt for receipt in receipts if '"accepted": true' in receipt]
    rejected = [receipt for receipt in receipts if '"accepted": false' in receipt]
    assert len(accepted) == 6
    assert len(rejected) == 1
    assert '"tool": "write_metrics"' in rejected[0]


@pytest.mark.asyncio
async def test_failed_write_rolls_back_only_that_calls_revision() -> None:
    """2026-08-10 用于验证失败调用恢复该调用前账本而其他成功 write 修订保留"""
    invalid_metrics = _write_call(
        "write_metrics",
        {
            "summary": " ",
            "emotional_valence": "neutral",
            "narrative_function": "铺垫",
        },
        call_id="call-metrics-bad",
    )
    llm = _SequenceLLM(
        [
            _tool_message([invalid_metrics, _metrics_call(call_id="call-metrics-2")]),
            _tool_message(_full_write_calls()),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 2
    receipts = _tool_receipts(llm.captured_messages[1])
    accepted = [receipt for receipt in receipts if '"accepted": true' in receipt]
    rejected = [receipt for receipt in receipts if '"accepted": false' in receipt]
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert '"revision": 1' in accepted[0]
    assert '"tool": "write_metrics"' in rejected[0]


@pytest.mark.asyncio
async def test_partial_writes_do_not_auto_finalize() -> None:
    """2026-08-07 用于验证领域未写完时不会触发自动完成，补齐后才完成"""
    llm = _SequenceLLM(
        [
            _tool_message(
                [
                    _metrics_call(),
                    _entities_call(),
                    _observations_call(),
                    _dialogues_call(),
                    _events_call(),
                ]
            ),
            _tool_message(_empty_domain_calls()),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_truncated_tool_call_skips_business_tool_and_feeds_error_receipt() -> None:
    """
    2026-08-11 用于验证带截断标记的工具调用不执行业务写入，
    只回喂"参数不完整"错误回执，模型补全后章节仍能完成。
    """
    truncated_metrics = {
        "name": "write_metrics",
        "args": {},
        "id": "call-metrics-truncated",
        "type": "tool_call",
        "truncated": True,
        "truncated_args": '{"summary": "住手回荡", "emotional_va',
    }
    # 聚合器在运行时以属性赋值挂载截断标记（绕过 create_tool_call 重建），测试同样模拟
    first_message = AIMessage(content="")
    first_message.tool_calls = [truncated_metrics, _entities_call()]
    llm = _SequenceLLM(
        [
            first_message,
            _tool_message(
                [
                    _metrics_call(),
                    _observations_call(),
                    _dialogues_call(),
                    _events_call(),
                    *_empty_domain_calls(),
                ]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 2
    receipts = _tool_receipts(llm.captured_messages[1])
    rejected = [receipt for receipt in receipts if '"accepted": false' in receipt]
    accepted = [receipt for receipt in receipts if '"accepted": true' in receipt]
    assert len(rejected) == 1
    assert len(accepted) == 1
    assert '"tool": "write_metrics"' in rejected[0]
    assert "截断" in rejected[0]


@pytest.mark.asyncio
async def test_protocol_error_rejects_plain_text_reply() -> None:
    """2026-08-07 用于验证无工具回复不能推进章节"""
    llm = _SequenceLLM([AIMessage(content="已经完成")])
    result = await _invoke_graph(llm, allow_future_context=False)

    assert "annotation 工具协议错误" in str(result["error"])


@pytest.mark.asyncio
async def test_auto_finalize_invariant_error_terminates_chapter() -> None:
    """2026-08-10 用于验证 receipt 齐全但 ready_chunk 缺失时按不变量错误终止而非回环修正"""
    llm = _SequenceLLM(
        [
            _tool_message(_full_write_calls()),
        ]
    )

    class _BrokenLedger(AnnotationToolLedger):
        """2026-08-10 用于模拟 7 个 receipt 齐全但 ready_chunk 被破坏"""

        def _rebuild_ready_chunk_if_complete(self) -> None:
            super()._rebuild_ready_chunk_if_complete()
            self.ready_chunk = None

    chunk_id, chunk_text = 1, "“住手”回荡"
    ledger = _BrokenLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=chunk_id,
        current_chunk_text=chunk_text,
        allow_future_context=False,
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
    assert llm.calls == 1
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
