"""章节标注全流程与 AgentAuditRecorder 的端到端审计集成测试"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.agents.stream_audit import ModelCallTiming
from src.agents.turn_observer import AgentTurnObserver, build_invocation_context
from src.audit.queries import fetch_agent_turns
from src.audit.recorder import AgentAuditRecorder
from src.fact_graph.inputs import ChapterParagraphInfo
from src.storage.models import WorkItem
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.model_stream_adapter import StreamedFakeModelMixin


def _chunk_paragraph_info(text: str) -> ChapterParagraphInfo:
    """2026-08-18 用于构造单段落 ChapterParagraphInfo（事件锚点派生所需）"""
    return ChapterParagraphInfo(
        paragraph_ids=[0],
        char_spans=[(0, len(text))],
        texts=[text],
    )


def _two_paragraph_info(text: str) -> ChapterParagraphInfo:
    """2026-09-14 用于构造两段 ChapterParagraphInfo（write_metrics.labels 段落标签的段号取值域所需）"""
    return ChapterParagraphInfo(
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

    async def search_text(self, query, *, range_name, limit=50):
        """2026-08-07 用于返回空原文候选"""
        del query, range_name, limit
        return []


class _SequenceLLM(StreamedFakeModelMixin):
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
# 唯一收尾 finish（旧名 finish_chunk）
_ALL_WRITE_TOOLS = (
    "write_entity",
    "write_metrics",
    "write_event",
    "write_relation",
    "write_dialogue",
)


def _finish_chapter_call(call_id: str = "call-finish-chapter") -> dict:
    """2026-09-14 用于构造唯一收尾工具 finish 调用（判定并入本回合批次末尾）"""
    return _write_call("finish", {}, call_id=call_id)


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
    return [{"paragraph_id": 1, "emotion": -2}, {"paragraph_id": 2, "emotion": -1}]


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
    两调用，参与者的 emotion 等三态内联进各自节点的 characters 数组
    （2026-09-19 id 纪律：entityid 用 el 键引用，运行期编号已删）。
    """
    return [
        _write_call(
            "write_event",
            {
                "el": tree_key,
                "evidence": 1,
                "characters": [
                    {
                        "name": "顾霜",
                        "entity_type": "character",
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": action,
                        "emotion": -1,
                    }
                ],
                "title": description,
                "problem": "明确事件问题",
                "summary": description,
                "event_type": "行动",
                "status": "ongoing",
            },
            call_id=f"{call_id}-root",
        ),
        _write_call(
            "write_event",
            {
                "el": f"{tree_key}/{child_key}",
                "evidence": 2,
                "characters": [
                    {
                        "name": "顾霜",
                        "entity_type": "character",
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": child_action,
                        "emotion": 0,
                    }
                ],
                "title": child_description,
                "problem": "明确事件问题",
                "summary": child_description,
                "event_type": "行动",
                "status": "ongoing",
            },
            call_id=f"{call_id}-child",
        ),
    ]


@pytest.mark.asyncio
async def test_observer_records_each_physical_provider_request_separately(db_session) -> None:
    """2026-08-30 用于验证失败重试与成功请求分别保存安全参数指纹计时和 token"""
    from uuid import uuid4

    novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜进入山门"])
    work_id = f"work-{uuid4().hex[:12]}"
    db_session.add(
        WorkItem(work_id=work_id, role="solo", annotation_run_id=run_id, annotation_chapter_id=1)
    )
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    recorder = AgentAuditRecorder(factory)
    context = build_invocation_context(
        run_id=run_id,
        task_type="annotation",
        execution_id=f"annot-exec-{uuid4().hex[:12]}",
        attempt_number=1,
        model="test-model",
        chapter_id=1,
        work_id=work_id,
        role="solo",
    )
    invocation_id = recorder.start_invocation(**context)
    observer = AgentTurnObserver(recorder, invocation_id=invocation_id, context=context)
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
        context_summary={"phase": "chapter_open"},
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
        context_summary={"phase": "chapter_open"},
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
    turns = fetch_agent_turns(db_session, run_id)
    assert [turn.status for turn in turns] == ["error", "success"]
    assert [turn.turn_index for turn in turns] == [1, 2]
    assert [turn.context_summary["provider_request"]["request_index"] for turn in turns] == [1, 2]
    assert turns[0].context_summary["provider_request"]["attempt"] == 1
    assert turns[1].context_summary["provider_request"]["attempt"] == 2
    assert turns[0].context_summary["provider_request"]["config_fingerprint"] == "a" * 64
    assert turns[0].context_summary["provider_request"]["parameters"]["extra_body"] == {"think": True}
    assert "api_key" not in str(turns[0].context_summary["provider_request"])
    assert turns[0].timings["ttft"] == 20
    assert turns[1].timings["ttft"] == 10
    assert turns[0].raw_response["content"] == "部分输出"
    assert turns[0].raw_response["reasoning_observed"] is False
    assert turns[1].raw_response["reasoning_observed"] is True
    assert sorted(turn.total_tokens for turn in turns if turn.total_tokens is not None) == [12, 20]
