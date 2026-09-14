"""章节标注全流程与 AgentAuditRecorder 的端到端审计集成测试"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.prompts import build_chunk_message
from src.agents.annotation.schema import ChunkParagraphInfo, SearchResult
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools
from src.agents.audit.observer import AgentTurnObserver
from src.agents.audit.recorder import AgentAuditRecorder
from src.agents.stream import ModelCallTiming
from src.storage.models import TokenUsage
from src.storage.models.agent_audit import AgentInvocation, AgentToolCall, AgentTurn
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _chunk_paragraph_info(text: str) -> ChunkParagraphInfo:
    """2026-08-18 用于构造单段落 ChunkParagraphInfo（事件锚点派生所需）"""
    return ChunkParagraphInfo(
        paragraph_ids=[0],
        char_spans=[(0, len(text))],
        texts=[text],
    )


def _two_paragraph_info(text: str) -> ChunkParagraphInfo:
    """2026-09-14 用于构造两段 ChunkParagraphInfo（write_metrics.labels 段落标签的段号取值域所需）"""
    return ChunkParagraphInfo(
        paragraph_ids=[0, 1],
        char_spans=[(0, 2), (2, len(text))],
        texts=[text[:2], text[2:]],
    )


pytestmark = pytest.mark.asyncio


def _count(db_session, model, run_id: str) -> int:
    """2026-08-10 用于按 run 统计审计行数"""
    return int(db_session.execute(select(func.count()).select_from(model).where(model.run_id == run_id)).scalar_one())


# ---------------------------------------------------------------------------
# 2026-09-13 小调用改造：以下测试桩与调用构造器是本文件自带副本（测试模块之间不互相
# import）；命名与写法同 tests/agents/test_annotation_agent.py 的 helper 部分。
# ---------------------------------------------------------------------------

class _QueryService:
    """2026-08-07 用于提供无数据库依赖的新合同查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """2026-08-07 用于返回空案例与伏笔检索结果"""
        del query, hidden_case_ids, case_type, limit
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


def _write_call(name: str, args: dict, *, call_id: str) -> dict:
    """2026-08-07 用于构造单个工具调用"""
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


# 2026-09-14 写入面重构：五个领域写入小调用从首轮起全部在工具面上（写者面全放开），
# 唯一收尾 finish_chapter（旧名 finish_chunk）
_ALL_WRITE_TOOLS = (
    "write_entity",
    "write_metrics",
    "write_event",
    "write_relation",
    "write_dialogue",
)


def _finish_chapter_call(call_id: str = "call-finish-chapter") -> dict:
    """2026-09-14 用于构造唯一收尾工具 finish_chapter 调用（判定并入本回合批次末尾）"""
    return _write_call("finish_chapter", {}, call_id=call_id)


def _metrics_calls(
    call_id: str = "call-metrics",
    labels: list[dict] | None = None,
) -> list[dict]:
    """2026-09-14 用于构造 write_metrics 小调用（指标整域一次提交，段落标签随本域提交）"""
    args: dict = {"summary": "住手回荡", "emotional_valence": 0, "narrative_function": "铺垫"}
    if labels is not None:
        args["labels"] = labels
    return [_write_call("write_metrics", args, call_id=call_id)]


def _paragraph_label_items() -> list[dict]:
    """2026-09-14 用于构造两条段落标签（旧 write_sentence_label 逐句小调用收编进
    write_metrics.labels；默认两条满足每章 2-3 段软下限）"""
    return [{"paragraph_id": 0, "emotion": -2}, {"paragraph_id": 1, "emotion": -1}]


def _entity_calls(
    *,
    name: str = "顾霜",
    el: str | None = None,
    call_id: str = "call-entity",
) -> list[dict]:
    """2026-09-14 用于构造 write_entity 小调用（一次登记一个实体，el=章内引用键）"""
    return [
        _write_call(
            "write_entity",
            {"name": name, "entity_type": "character", "el": el if el is not None else name},
            call_id=call_id,
        )
    ]


def _dialogue_calls(call_id: str = "call-dialogue") -> list[dict]:
    """2026-09-13 用于构造 write_dialogue 小调用（第一条候选判为真实对话）"""
    return [
        _write_call(
            "write_dialogue",
            {"candidate_index": 1, "verdict": "dialogue", "speaker": None, "tone": "平静"},
            call_id=call_id,
        )
    ]


def _event_calls(
    *,
    tree_key: str = "t1",
    description: str = "顾霜喝止众人",
    action: str = "喝止",
    child_key: str = "e1",
    child_description: str = "顾霜收势",
    child_action: str = "收势",
    call_id: str = "call-events",
) -> list[dict]:
    """2026-09-14 用于构造一棵事件树的小调用组（write_event 根 + 子事件，参与者内联 characters）

    根 el=树键、子 el=树键/节点键；树内先后=调用顺序（无序号参数）；旧
    write_event_root/write_event_child/write_character_participation 四调用合并为
    两调用，参与者的 emotion 等三态内联进各自节点的 characters 数组。
    """
    return [
        _write_call(
            "write_event",
            {
                "el": tree_key,
                "isroot": True,
                "description": description,
                "characters": [
                    {
                        "entityid": 1,
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": action,
                        "emotion": -1,
                    }
                ],
            },
            call_id=f"{call_id}-root",
        ),
        _write_call(
            "write_event",
            {
                "el": f"{tree_key}/{child_key}",
                "isroot": False,
                "type": "main",
                "description": child_description,
                "characters": [
                    {
                        "entityid": 1,
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": child_action,
                        "emotion": 0,
                    }
                ],
            },
            call_id=f"{call_id}-child",
        ),
    ]


@pytest.mark.asyncio
async def test_observer_records_each_physical_provider_request_separately(db_session) -> None:
    """2026-08-30 用于验证失败重试与成功请求分别保存安全参数指纹计时和 token"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜进入山门"])
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    recorder = AgentAuditRecorder(factory)
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="cloud",
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation",
        call_type="agent",
        model_name="test-model",
        model_provider="cloud",
    )
    request_messages = [SystemMessage(content="sys"), HumanMessage(content="标注")]
    base_request = {
        "request_index": 1,
        "attempt": 1,
        "transport": "stream",
        "parameters": {
            "model": "test-model",
            "base_url": "https://provider.example/v1",
            "extra_body": {"think": True},
            "timeout_s": 180,
            "tool_names": ["write_metrics"],
            "tool_contract_fingerprint": "b" * 64,
        },
        "config_fingerprint": "a" * 64,
    }
    observer.begin_provider_turn(
        context_summary={"phase": "chunk_open"},
        request_messages=request_messages,
        provider_request=base_request,
        started_ns=1,
    )
    observer.fail_provider_turn(
        error="stream interrupted",
        timing=ModelCallTiming(ttft_ms=20, model_ms=30),
        response_message=AIMessage(
            content="部分输出",
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        ),
    )
    observer.begin_provider_turn(
        context_summary={"phase": "chunk_open"},
        request_messages=request_messages,
        provider_request={**base_request, "attempt": 2},
        started_ns=2,
    )
    observer.complete_provider_turn(
        response_message=AIMessage(
            content="",
            tool_calls=[{"name": "write_metrics", "args": {}, "id": "call-1"}],
            additional_kwargs={"reasoning_content": "先核对原文"},
            usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        ),
        timing=ModelCallTiming(ttft_ms=10, model_ms=40),
    )

    db_session.rollback()
    turns = list(
        db_session.execute(
            select(AgentTurn).where(AgentTurn.invocation_id == invocation_id).order_by(AgentTurn.turn_index)
        ).scalars()
    )
    assert [turn.status for turn in turns] == ["error", "success"]
    assert [turn.context_summary["provider_request"]["request_index"] for turn in turns] == [1, 2]
    assert turns[0].context_summary["provider_request"]["attempt"] == 1
    assert turns[1].context_summary["provider_request"]["attempt"] == 2
    assert turns[0].context_summary["provider_request"]["config_fingerprint"] == "a" * 64
    assert turns[0].context_summary["provider_request"]["parameters"]["extra_body"] == {"think": True}
    assert "api_key" not in str(turns[0].context_summary["provider_request"])
    assert turns[0].ttft_ms == 20
    assert turns[1].ttft_ms == 10
    assert turns[0].raw_response["content"] == "部分输出"
    assert turns[0].raw_response["reasoning_observed"] is False
    assert turns[1].raw_response["reasoning_observed"] is True
    token_rows = list(db_session.execute(select(TokenUsage).where(TokenUsage.run_id == run_id)).scalars())
    assert sorted(row.total_tokens for row in token_rows) == [12, 20]


@pytest.mark.asyncio
async def test_no_tool_reply_closes_turns_then_fails(db_session) -> None:
    """2026-08-30 用于验证无工具回复每次物理请求各自错误收口且不新增混合失败行"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["“住手”回荡"])
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    recorder = AgentAuditRecorder(factory)
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation",
        call_type="agent",
        model_name="test-model",
        model_provider="local",
    )
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=1,
        current_chunk_id=0,
        current_chunk_text="\u201c住手\u201d回荡",
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=_chunk_paragraph_info("\u201c住手\u201d回荡"),
    )
    llm = _SequenceLLM([AIMessage(content="我不调用工具")] * 5)
    graph = build_annotation_graph(
        llm,
        build_annotation_tools(_QueryService(), ledger),
        ledger=ledger,
        max_iterations=30,
        observer=observer,
    )
    with pytest.raises(RuntimeError, match="未正常结束"):
        await graph.ainvoke(
            {
                "messages": [
                    SystemMessage(content="test"),
                    HumanMessage(content="标注这段"),
                ],
                "phase": "chunk_open",
                "iterations": 0,
                "error": None,
            }
        )
    recorder.finish_invocation(invocation_id, status="error", final_error="模型调用未正常结束")

    db_session.rollback()
    turns = list(db_session.execute(select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)).scalars())
    # 调用层重试预算默认 3 次：每次物理请求各自闭合，不再额外生成混合失败行
    assert len(turns) == 3
    assert all(turn.status == "error" for turn in turns)
    assert all(turn.turn_ms is not None and turn.turn_ms >= 0 for turn in turns)


@pytest.mark.asyncio
async def test_annotation_model_exception_records_error_turn(db_session) -> None:
    """2026-08-11 用于验证标注模型调用异常时保留 error 回合并闭合计时"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["“住手”回荡"])
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    recorder = AgentAuditRecorder(factory)
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation",
        call_type="agent",
        model_name="test-model",
        model_provider="local",
    )
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=1,
        current_chunk_id=0,
        current_chunk_text="\u201c住手\u201d回荡",
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=_chunk_paragraph_info("\u201c住手\u201d回荡"),
    )
    llm = _SequenceLLM([])
    graph = build_annotation_graph(
        llm,
        build_annotation_tools(_QueryService(), ledger),
        ledger=ledger,
        max_iterations=30,
        observer=observer,
    )

    with pytest.raises(IndexError):
        await graph.ainvoke(
            {
                "messages": [
                    SystemMessage(content="test"),
                    HumanMessage(content="标注这段"),
                ],
                "phase": "chunk_open",
                "iterations": 0,
                "error": None,
            }
        )

    recorder.finish_invocation(invocation_id, status="error", final_error="IndexError")
    db_session.rollback()
    turns = list(db_session.execute(select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)).scalars())
    assert len(turns) == 1
    assert turns[0].status == "error"
    assert turns[0].error is not None
    assert turns[0].turn_ms is not None and turns[0].turn_ms >= 0


@pytest.mark.asyncio
async def test_annotation_turns_and_tool_calls_are_audited(db_session) -> None:
    """2026-08-30 用于验证每个物理模型请求与工具调用都有独立耗时且落库

    2026-09-13 取消暂存：一个模型回合 = 多个有类型的小调用（写入即生效，回执
    status=written）。2026-09-14 写入面重构：收尾由唯一 finish_chapter 表达（旧名
    finish_chunk），段落标签随 write_metrics.labels 提交（旧 write_sentence_label
    退役），参与者内联 write_event.characters；收尾判定推迟到本回合全部调用处理完
    后执行，因此"每个模型回合一行、每个工具调用一行"的不变量在新合同下逐调用验证
    （3 回合计 8 行，含 1 条被本回合失败记录拒绝的 finish_chapter）。
    """
    novel_id, run_id = create_run_with_chunks(db_session, texts=["“住手”回荡"])
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    recorder = AgentAuditRecorder(factory)
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation",
        call_type="agent",
        model_name="test-model",
        model_provider="local",
    )
    invalid_metrics = _write_call(
        "write_metrics",
        {
            "summary": " ",
            "emotional_valence": 0,
            "narrative_function": "铺垫",
        },
        call_id="call-metrics-bad",
    )
    # 2026-09-14 三轮小调用组：实体+坏指标+finish_chapter（指标没提交，
    # 收尾被拒 missing_record）→ 修正指标（随附两条段落标签）+事件树（参与者内联）→
    # 对话+finish_chapter（收尾通过）
    rounds = [
        [*_entity_calls(), invalid_metrics, _finish_chapter_call("call-finish-round1")],
        [
            *_metrics_calls(call_id="call-metrics-fixed", labels=_paragraph_label_items()),
            *_event_calls(),
        ],
        [
            *_dialogue_calls(),
            _finish_chapter_call("call-finish-round3"),
        ],
    ]
    llm = _SequenceLLM([_tool_message(calls) for calls in rounds])
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=1,
        current_chunk_id=0,
        current_chunk_text="“住手”回荡",
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=_two_paragraph_info("“住手”回荡"),
    )
    tools = build_annotation_tools(_QueryService(), ledger)
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=30,
        observer=observer,
    )
    result_state = await graph.ainvoke(
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
    recorder.finish_invocation(invocation_id, status="success")

    assert result_state["phase"] == "completed"
    db_session.rollback()
    assert _count(db_session, AgentInvocation, run_id) == 1
    invocation = db_session.execute(select(AgentInvocation).where(AgentInvocation.run_id == run_id)).scalar_one()
    assert invocation.status == "success"
    assert invocation.finished_at is not None

    turn_rows = list(
        db_session.execute(
            select(AgentTurn)
            .where(AgentTurn.invocation_id == invocation_id)
            .order_by(AgentTurn.turn_index, AgentTurn.id)
        ).scalars()
    )
    assert len(turn_rows) == 3
    assert [row.turn_index for row in turn_rows] == [1, 2, 3]
    for turn in turn_rows:
        assert turn.model_ms is not None and turn.model_ms >= 0
        assert turn.turn_ms is not None and turn.turn_ms >= 0
        assert turn.raw_response["role"] == "ai"
        assert turn.context_summary["phase"] in {"chunk_open", "completed"}
        # 2026-09-14 写者面全放开：每轮工具面都是五个领域写入小调用的全集
        # （active_write_tool/active_write_tools 两个描述开放窗口的审计键已随解锁机制删除）
        assert set(_ALL_WRITE_TOOLS) <= set(turn.context_summary["allowed_tool_names"])

    tool_rows = list(
        db_session.execute(
            select(AgentToolCall)
            .join(AgentTurn, AgentTurn.id == AgentToolCall.turn_id)
            .where(AgentTurn.invocation_id == invocation_id)
            .order_by(AgentToolCall.call_index, AgentToolCall.id)
        ).scalars()
    )
    # 每个模型回合一行、每个工具调用一行：按回合分组后逐调用核对
    rows_by_turn: dict[int, list[AgentToolCall]] = {}
    for row in tool_rows:
        rows_by_turn.setdefault(row.turn_id, []).append(row)
    assert len(tool_rows) == sum(len(calls) for calls in rounds) == 8
    for turn, calls in zip(turn_rows, rounds, strict=True):
        rows = rows_by_turn[turn.id]
        assert [row.tool_name for row in rows] == [call["name"] for call in calls]
        assert [row.call_index for row in rows] == list(range(len(calls)))

    failed_rows = [row for row in tool_rows if row.status == "error"]
    assert len(failed_rows) == 2
    # 坏指标：写入点结构化拒绝仍指向该条记录；收尾因指标没提交被拒
    failed_metrics = [row for row in failed_rows if row.tool_name == "write_metrics"]
    assert len(failed_metrics) == 1
    assert failed_metrics[0].receipt["status"] == "rejected"
    assert failed_metrics[0].receipt["record"] == "metrics"
    assert failed_metrics[0].error is not None
    failed_finish = [row for row in failed_rows if row.tool_name == "finish_chapter"]
    assert len(failed_finish) == 1
    assert failed_finish[0].receipt["status"] == "rejected"
    assert failed_finish[0].receipt["record"] == "finish_chapter"
    # 收尾被拒的归因是指标没提交（硬前提），不是"同回合有失败调用"——后者已不再阻塞收尾
    assert failed_finish[0].receipt["code"] == "missing_record"
    assert failed_finish[0].receipt["field"] == "metrics"
    for tool in tool_rows:
        assert tool.tool_duration_ms is not None and tool.tool_duration_ms >= 0
        assert tool.request_args is not None
    accepted_rows = [row for row in tool_rows if row.status == "success"]
    assert len(accepted_rows) == 6
    # 写入即生效：小调用成功回执一律 written（领域落账不推迟到任何收尾结算）
    written_rows = [row for row in accepted_rows if row.tool_name.startswith("write_")]
    assert len(written_rows) == 5
    assert all(row.receipt["status"] == "written" for row in written_rows)
    # 唯一收尾：通过的 finish_chapter 在批次末尾结算，回执携带各域条数
    finish_rows = [row for row in accepted_rows if row.tool_name == "finish_chapter"]
    assert len(finish_rows) == 1
    assert finish_rows[0].receipt["status"] == "completed"
    assert finish_rows[0].receipt["chunk_id"] == 0
    assert finish_rows[0].receipt["records"] == {
        "entities": 1,
        "metrics": 1,
        "events": 2,
        "relations": 0,
        "dialogues": 1,
        "character_observations": 2,
        "paragraph_labels": 2,
    }
    assert finish_rows[0].receipt["dialogue_defaulted"] == []

    token_rows = list(db_session.execute(select(TokenUsage).where(TokenUsage.run_id == run_id)).scalars())
    assert len(token_rows) == 3
    assert all(row.agent_turn_id is not None for row in token_rows)
    assert {row.agent_turn_id for row in token_rows} == {row.id for row in turn_rows}
