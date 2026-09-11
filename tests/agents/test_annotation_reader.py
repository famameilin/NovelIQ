"""章内并行两段式：读者消息池、send_message 校验、读者图循环与写者准入测试

对应《章内并行设计-子代理只读顾问与主代理单写者》§5/§7/§16.1：
- U1 引文不在段落/多处命中 → 报错且消息不入池；
- U2 dialogue 候选序号越界 → 报错；
- U6 池序按 (block_index, message_id) 与入池先后无关；
- 写者取值域准入：write_entities 实体名、resolve/close reason 引文片段。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from src.agents.annotation.errors import AnnotationRetryableError
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import build_reader_graph
from src.agents.annotation.messages import ReaderMessagePool
from src.agents.annotation.reader import ReaderBlockContext, build_reader_tools, run_reader_agent
from src.agents.annotation.schema import ChunkParagraphInfo
from src.agents.annotation.tools import AnnotationToolLedger

_BLOCK_TEXT = (
    "白芷赠槐叶给顾霜，暗示旧约仍在。白芷道：“槐叶赠你。”\n"
    "秦穆重申禁碑以南不可进入。\n"
    "禁碑在村口，禁碑古老。\n"
)

_PARAGRAPH_TEXTS = [
    "白芷赠槐叶给顾霜，暗示旧约仍在。白芷道：“槐叶赠你。”",
    "秦穆重申禁碑以南不可进入。",
    "禁碑在村口，禁碑古老。",
]


class _QueryServiceStub:
    """2026-09-11 用于读者面检索工具的空查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50):
        from src.agents.annotation.schema import SearchResult

        del query, hidden_case_ids, case_type, limit
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        del query, range_name, limit
        return []

    def search_event_history(self, query, *, limit=50):
        del query, limit
        return []

    def fetch_active_case_details(self, case_id):
        del case_id
        return None

    def thread_exists(self, setup_id):
        del setup_id
        return False


def _reader_ledger() -> AnnotationToolLedger:
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=20,
        current_chunk_id=-1,
        current_chunk_text=_BLOCK_TEXT,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[101, 102, 103],
            char_spans=[(0, 25), (25, 38), (38, 51)],
            texts=list(_PARAGRAPH_TEXTS),
        ),
    )


def _reader_tools(ledger: AnnotationToolLedger, *, pool: ReaderMessagePool) -> dict[str, Any]:
    tools = build_reader_tools(
        _QueryServiceStub(),
        ledger,
        pool=pool,
        block_index=0,
        candidate_number_map={1: 7},
    )
    return {tool.name: tool for tool in tools}


def _case_payload() -> dict[str, Any]:
    return {
        "signal": "坐实",
        "entities": ["白芷", "秦穆"],
        "keywords": ["禁碑"],
        "observation": "秦穆重申禁碑禁令，案例坐实",
    }


class TestSendMessageValidation:
    @pytest.mark.asyncio
    async def test_valid_case_message_enqueued_with_message_id(self) -> None:
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        send_message = _reader_tools(ledger, pool=pool)["send_message"]

        receipt = json.loads(
            await send_message.ainvoke(
                {
                    "kind": "case",
                    "summary": "禁碑伏笔坐实",
                    "payload": _case_payload(),
                    "evidence": [{"paragraph_id": 102, "quote": "秦穆重申禁碑以南不可进入"}],
                }
            )
        )

        assert receipt["accepted"] is True
        assert receipt["message_id"] == 1
        assert pool.message_count() == 1
        assert pool.ordered()[0].kind == "case"

    @pytest.mark.asyncio
    async def test_quote_not_in_paragraph_rejected_and_not_enqueued(self) -> None:
        """U1a：引文不在该段落 → 报错、消息不入池"""
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        send_message = _reader_tools(ledger, pool=pool)["send_message"]

        with pytest.raises(Exception, match="不在段落"):
            await send_message.ainvoke(
                {
                    "kind": "case",
                    "summary": "编造引文",
                    "payload": _case_payload(),
                    "evidence": [{"paragraph_id": 102, "quote": "禁碑以北不可进入"}],
                }
            )
        assert pool.message_count() == 0

    @pytest.mark.asyncio
    async def test_ambiguous_quote_rejected(self) -> None:
        """U1b：引文在段落内多处命中 → 报错要求加长"""
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        send_message = _reader_tools(ledger, pool=pool)["send_message"]

        with pytest.raises(Exception, match="不唯一"):
            await send_message.ainvoke(
                {
                    "kind": "case",
                    "summary": "短引文歧义",
                    "payload": _case_payload(),
                    "evidence": [{"paragraph_id": 103, "quote": "禁碑"}],
                }
            )
        assert pool.message_count() == 0

    @pytest.mark.asyncio
    async def test_paragraph_id_outside_block_rejected(self) -> None:
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        send_message = _reader_tools(ledger, pool=pool)["send_message"]

        with pytest.raises(Exception, match="不属于本子块"):
            await send_message.ainvoke(
                {
                    "kind": "note",
                    "summary": "越界段落",
                    "payload": {"text": "相邻块线索"},
                    "evidence": [{"paragraph_id": 999, "quote": "禁碑"}],
                }
            )
        assert pool.message_count() == 0

    @pytest.mark.asyncio
    async def test_dialogue_candidate_index_out_of_range_rejected(self) -> None:
        """U2：候选序号越界 → 报错"""
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        send_message = _reader_tools(ledger, pool=pool)["send_message"]

        with pytest.raises(Exception, match="超出本块候选范围"):
            await send_message.ainvoke(
                {
                    "kind": "dialogue",
                    "summary": "越界候选",
                    "payload": {"candidate_index": 99, "verdict": "dialogue"},
                }
            )
        assert pool.message_count() == 0

    @pytest.mark.asyncio
    async def test_dialogue_valid_message_resolves_chapter_candidate_index(self) -> None:
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        send_message = _reader_tools(ledger, pool=pool)["send_message"]

        await send_message.ainvoke(
            {
                "kind": "dialogue",
                "summary": "白芷赠叶",
                "payload": {"candidate_index": 1, "verdict": "dialogue", "speaker": "白芷", "tone": "平静"},
                "evidence": [{"paragraph_id": 101, "quote": "槐叶赠你。"}],
            }
        )

        message = pool.ordered()[0]
        assert message.chapter_candidate_index == 7

    @pytest.mark.asyncio
    async def test_sentence_label_emotion_out_of_range_rejected(self) -> None:
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        send_message = _reader_tools(ledger, pool=pool)["send_message"]

        with pytest.raises(Exception, match="-2..2"):
            await send_message.ainvoke(
                {
                    "kind": "sentence_label",
                    "summary": "越界情绪分",
                    "payload": {"sentence": "秦穆重申禁碑以南不可进入。", "emotion": 5},
                }
            )
        assert pool.message_count() == 0

    @pytest.mark.asyncio
    async def test_note_without_evidence_accepted(self) -> None:
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        send_message = _reader_tools(ledger, pool=pool)["send_message"]

        receipt = json.loads(
            await send_message.ainvoke(
                {
                    "kind": "note",
                    "summary": "块边界线索",
                    "payload": {"text": "蹄印方向指向下一块开头的禁碑段落"},
                }
            )
        )
        assert receipt["accepted"] is True
        assert pool.ordered()[0].evidence == []

    @pytest.mark.asyncio
    async def test_non_note_kind_without_evidence_rejected(self) -> None:
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        send_message = _reader_tools(ledger, pool=pool)["send_message"]

        with pytest.raises(Exception, match="至少一条 evidence"):
            await send_message.ainvoke(
                {"kind": "case", "summary": "无引文", "payload": _case_payload()}
            )
        assert pool.message_count() == 0


class TestReaderMessagePool:
    def test_ordering_is_block_then_arrival_independent_of_completion_order(self) -> None:
        """U6：池序按 (block_index, message_id)，与读者完成顺序无关"""
        pool = ReaderMessagePool()
        pool.append(block_index=1, kind="note", summary="块2先完成", payload={"text": "b2"}, evidence=[])
        pool.append(block_index=0, kind="note", summary="块1后完成", payload={"text": "b1a"}, evidence=[])
        pool.append(block_index=0, kind="note", summary="块1第二条", payload={"text": "b1b"}, evidence=[])

        ordered = pool.ordered()
        assert [(message.block_index, message.message_id) for message in ordered] == [
            (0, 2),
            (0, 3),
            (1, 1),
        ]

    def test_discard_block_removes_only_that_block(self) -> None:
        pool = ReaderMessagePool()
        pool.append(block_index=0, kind="note", summary="a", payload={"text": "a"}, evidence=[])
        pool.append(block_index=1, kind="note", summary="b", payload={"text": "b"}, evidence=[])

        pool.discard_block(0)

        assert pool.message_count() == 1
        assert pool.ordered()[0].block_index == 1

    def test_entity_name_keys_collects_all_kinds(self) -> None:
        pool = ReaderMessagePool()
        pool.append(
            block_index=0,
            kind="entity",
            summary="实体",
            payload={"name": "白芷", "entity_type": "character"},
            evidence=[{"paragraph_id": 101, "quote": "白芷"}],
        )
        pool.append(
            block_index=0,
            kind="event_tree",
            summary="事件",
            payload={
                "description": "赠叶",
                "participants": [{"entity": "顾霜", "role": "主体"}],
                "children": [
                    {"type": "main", "description": "收下", "participants": [{"entity": "秦穆", "role": "客体"}]}
                ],
            },
            evidence=[{"paragraph_id": 101, "quote": "白芷"}],
        )
        pool.append(
            block_index=0,
            kind="case",
            summary="案例",
            payload={"signal": "坐实", "entities": ["禁碑"], "observation": "x"},
            evidence=[{"paragraph_id": 102, "quote": "禁碑"}],
        )

        assert pool.entity_name_keys() == {"白芷", "顾霜", "秦穆", "禁碑"}

    def test_case_quotes_returns_normalized_evidence_quotes(self) -> None:
        pool = ReaderMessagePool()
        pool.append(
            block_index=0,
            kind="case",
            summary="案例",
            payload=_case_payload(),
            evidence=[{"paragraph_id": 102, "quote": "秦穆重申禁碑以南不可进入"}],
        )
        pool.append(
            block_index=0,
            kind="note",
            summary="非案例",
            payload={"text": "n"},
            evidence=[],
        )

        assert pool.case_quotes() == ("秦穆重申禁碑以南不可进入",)

    def test_writer_view_renders_messages_in_block_order(self) -> None:
        pool = ReaderMessagePool()
        pool.append(
            block_index=0,
            kind="case",
            summary="案例一",
            payload=_case_payload(),
            evidence=[{"paragraph_id": 102, "quote": "禁碑以南不可进入"}],
        )
        pool.append(
            block_index=1,
            kind="dialogue",
            summary="对话判定",
            payload={"candidate_index": 1, "verdict": "dialogue"},
            evidence=[],
            chapter_candidate_index=7,
        )

        view = pool.writer_view()

        assert '<message id="1" block="1" kind="case">' in view
        assert '<message id="2" block="2" kind="dialogue">' in view
        assert "chapter_candidate_index" in view
        assert view.index('kind="case"') < view.index('kind="dialogue"')


class _SequenceLLM:
    """2026-09-11 用于按顺序返回读者消息的测试模型（非流式路径）"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def bind_tools(self, tools):
        del tools
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        del messages
        return self.responses.pop(0)


def _tool_call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class TestReaderGraphLoop:
    @pytest.mark.asyncio
    async def test_reader_completes_on_no_tool_response_and_enqueues_messages(self) -> None:
        """读者无工具回复=上报完毕（require_tool_call=False 语义），消息全部入池"""
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        tools = _reader_tools(ledger, pool=pool)
        llm = _SequenceLLM(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call(
                            "send_message",
                            {
                                "kind": "case",
                                "summary": "案例坐实",
                                "payload": _case_payload(),
                                "evidence": [{"paragraph_id": 102, "quote": "秦穆重申禁碑以南不可进入"}],
                            },
                            "call-1",
                        ),
                        _tool_call(
                            "send_message",
                            {"kind": "note", "summary": "边界线索", "payload": {"text": "蹄印指向下一块"}},
                            "call-2",
                        ),
                    ],
                ),
                AIMessage(content="本块观察已全部上报完毕。"),
            ]
        )
        graph = build_reader_graph(llm, list(tools.values()), ledger=ledger, max_iterations=10)

        result_state = await graph.ainvoke(
            {"messages": [SystemMessage(content="reader")], "phase": "chunk_open", "iterations": 0, "error": None}
        )

        assert result_state["error"] is None
        assert pool.message_count() == 2
        assert [message.kind for message in pool.ordered()] == ["case", "note"]
        assert llm.calls == 2

    @pytest.mark.asyncio
    async def test_reader_reports_error_when_iteration_cap_reached(self) -> None:
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        tools = _reader_tools(ledger, pool=pool)
        llm = _SequenceLLM(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call(
                            "send_message",
                            {"kind": "note", "summary": "s", "payload": {"text": "t"}},
                            "call-1",
                        )
                    ],
                )
            ]
            * 1
        )
        graph = build_reader_graph(llm, list(tools.values()), ledger=ledger, max_iterations=1)

        result_state = await graph.ainvoke(
            {"messages": [SystemMessage(content="reader")], "phase": "chunk_open", "iterations": 0, "error": None}
        )

        assert result_state["error"] is not None
        assert "上限" in result_state["error"]


class TestWriterAdmission:
    @pytest.mark.asyncio
    async def test_writer_rejects_entity_names_outside_message_pool(self) -> None:
        """U4：写者写消息池外的实体名 → 拒绝"""
        from src.agents.annotation.schema import EntityDirectoryInput, EntityInput

        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        pool.append(
            block_index=0,
            kind="entity",
            summary="实体",
            payload={"name": "白芷", "entity_type": "character"},
            evidence=[{"paragraph_id": 101, "quote": "白芷"}],
        )
        ledger.reader_message_pool = pool
        payload = EntityDirectoryInput(
            entities=[
                EntityInput(name="白芷", entity_type="character"),
                EntityInput(name="从未上报的实体", entity_type="character"),
            ]
        )

        with pytest.raises(ValueError, match="准入失败"):
            ledger.write_domain("entities", payload, tool_name="write_entities")

    @pytest.mark.asyncio
    async def test_writer_accepts_entity_names_from_pool_or_graph(self) -> None:
        from src.agents.annotation.schema import EntityDirectoryInput, EntityInput

        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        pool.append(
            block_index=0,
            kind="entity",
            summary="实体",
            payload={"name": "白芷", "entity_type": "character"},
            evidence=[{"paragraph_id": 101, "quote": "白芷"}],
        )
        ledger.reader_message_pool = pool
        payload = EntityDirectoryInput(entities=[EntityInput(name="白芷", entity_type="character")])

        ledger.write_domain("entities", payload, tool_name="write_entities")

        assert "entities" in ledger.domain_receipts

    @pytest.mark.asyncio
    async def test_case_reason_requires_quote_fragment_from_case_messages(self) -> None:
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        pool.append(
            block_index=0,
            kind="case",
            summary="案例",
            payload=_case_payload(),
            evidence=[{"paragraph_id": 101, "quote": "白芷赠槐叶给顾霜，暗示旧约仍在"}],
        )
        ledger.reader_message_pool = pool
        ledger.case_number_registry[3] = "case-1"

        # 完整引文 → 通过
        ledger.admit_case_reason("原文：白芷赠槐叶给顾霜，暗示旧约仍在，故坐实", tool_name="close_case")
        # ≥12 字连续片段 → 通过（引文共 15 字，前 12 字是合法片段）
        ledger.admit_case_reason("读者证据表明白芷赠槐叶给顾霜，暗示旧，案例坐实", tool_name="close_case")
        # 纯转写 → 拒绝
        with pytest.raises(ValueError, match="引文片段"):
            ledger.admit_case_reason("我觉得这个案例可以关闭了", tool_name="close_case")

    @pytest.mark.asyncio
    async def test_case_reason_rejected_when_pool_has_no_case_messages(self) -> None:
        ledger = _reader_ledger()
        pool = ReaderMessagePool()
        pool.append(
            block_index=0,
            kind="note",
            summary="n",
            payload={"text": "t"},
            evidence=[],
        )
        ledger.reader_message_pool = pool

        with pytest.raises(ValueError, match="未上报任何案例消息"):
            ledger.admit_case_reason("随便一个理由", tool_name="close_case")


class TestRunReaderAgent:
    @pytest.mark.asyncio
    async def test_run_reader_agent_builds_block_message_with_paragraph_ids(self) -> None:
        """读者工具面只有只读检索 + send_message；首条请求以段落清单注入正文"""
        captured: dict[str, Any] = {}

        class _SessionStub:
            def get_bind(self):
                return None

            def execute(self, *args, **kwargs):
                raise AssertionError("非 PostgreSQL 会话不应执行 READ ONLY")

            def rollback(self):
                pass

            def close(self):
                pass

        class _ExplodingLLM:
            def bind_tools(self, tools):
                captured["tools"] = [tool.name for tool in tools]
                return self

            async def ainvoke(self, messages):
                captured["messages"] = list(messages)
                raise RuntimeError("stop")

        context = ReaderBlockContext(
            block_index=0,
            block_count=2,
            block_chunk_id=-1,
            block_text=_BLOCK_TEXT,
            paragraph_info=ChunkParagraphInfo(
                paragraph_ids=[101, 102, 103],
                char_spans=[(0, 25), (25, 38), (38, 51)],
                texts=list(_PARAGRAPH_TEXTS),
            ),
            candidate_number_map={1: 7},
        )
        pool = ReaderMessagePool()

        with pytest.raises(AnnotationRetryableError):
            await run_reader_agent(
                run_id="run-1",
                chapter_id=20,
                context=context,
                pool=pool,
                query_service_factory=lambda session: session,
                session_factory=lambda: _SessionStub(),
                llm=_ExplodingLLM(),
                graph_state=FactGraph(),
                audit_recorder=MagicMock(),
            )

        assert "send_message" in captured["tools"]
        assert "search_pool" in captured["tools"]
        assert "write_metrics" not in captured["tools"]
        assert "resolve_fact_case" not in captured["tools"]
        first_human = captured["messages"][1].content
        assert '<paragraph id="101">' in first_human
        assert "CurrentSubBlock" in first_human
        assert "白芷赠槐叶给顾霜" in first_human
