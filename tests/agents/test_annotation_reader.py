"""章内并行两段式：读者一次性报告、send_message 合同、读者图循环与写者准入测试

对应《章内并行设计-子代理只读顾问与主代理单写者》§5/§7/§16.1，
2026-09-12 修订（一次性上报 + 校验失败不打回 + 消息池删除）：
- send_message 每轮激活只允许调用一次，载荷按观察类分组复合上报；
- 格式/枚举/引文核验失败不打回：观察照常送达，问题以 warnings 呈现，
  未核验引文打 unverified 标记且不得用于写者案例取证；
- 写者取值域准入：write_entity 实体名 ∈ 报告并集 ∪ 图中已登记名（2026-09-13 取消暂存后
  写入即生效，准入在每次单条写入时判定，失败不牵连同批其他记录）。
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
from src.agents.annotation.prompts import build_reader_block_message
from src.agents.annotation.reader import ReaderBlockContext, build_reader_tools, run_reader_agent
from src.agents.annotation.reader_report import (
    ReaderReport,
    render_reader_reports,
    report_case_quotes,
    report_entity_name_keys,
)
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

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
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


def _reader_tools(ledger: AnnotationToolLedger, *, delivered: list[ReaderReport]) -> dict[str, Any]:
    tools = build_reader_tools(
        _QueryServiceStub(),
        ledger,
        delivered=delivered,
        block_index=0,
        candidate_number_map={1: 7},
    )
    return {tool.name: tool for tool in tools}


def _case_item() -> dict[str, Any]:
    return {
        "signal": "坐实",
        "entities": ["白芷", "秦穆"],
        "keywords": ["禁碑"],
        "observation": "秦穆重申禁碑禁令，案例坐实",
        "evidence": [{"paragraph_id": 102, "quote": "秦穆重申禁碑以南不可进入"}],
    }


class TestSendMessageReport:
    @pytest.mark.asyncio
    async def test_composite_report_delivered_once(self) -> None:
        """复合载荷一次性送达：各观察组原样进报告，回执 accepted"""
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        receipt = json.loads(
            await send_message.ainvoke(
                {
                    "entities": [{"name": "白芷", "entity_type": "character"}],
                    "cases": [_case_item()],
                    "notes": [{"text": "蹄印方向指向下一块开头的禁碑段落"}],
                }
            )
        )

        assert receipt["accepted"] is True
        assert receipt["report_delivered"] is True
        assert receipt["block"] == 1
        assert len(delivered) == 1
        report = delivered[0]
        assert report.block_index == 0
        assert [item["name"] for item in report.report["entities"]] == ["白芷"]
        assert report.report["cases"][0]["signal"] == "坐实"
        assert report.report["notes"][0]["text"].startswith("蹄印")

    @pytest.mark.asyncio
    async def test_quote_not_in_paragraph_delivered_with_unverified_flag(self) -> None:
        """U1a 修订：引文不在该段落 → 不打回，观察照常送达并打 unverified 标记"""
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        bad_evidence = [{"paragraph_id": 102, "quote": "禁碑以北不可进入"}]
        receipt = json.loads(
            await send_message.ainvoke({"cases": [{**_case_item(), "evidence": bad_evidence}]})
        )

        assert receipt["accepted"] is True
        assert any("引文不在段落" in warning for warning in receipt["warnings"])
        evidence = delivered[0].report["cases"][0]["evidence"]
        assert evidence[0]["unverified"] is True

    @pytest.mark.asyncio
    async def test_ambiguous_quote_marked_unverified(self) -> None:
        """U1b 修订：引文多处命中 → unverified + 警告"""
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        ambiguous_evidence = [{"paragraph_id": 103, "quote": "禁碑"}]
        receipt = json.loads(
            await send_message.ainvoke({"cases": [{**_case_item(), "evidence": ambiguous_evidence}]})
        )

        assert any("不唯一" in warning for warning in receipt["warnings"])
        assert delivered[0].report["cases"][0]["evidence"][0]["unverified"] is True

    @pytest.mark.asyncio
    async def test_paragraph_id_outside_block_marked_unverified(self) -> None:
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        outside_evidence = [{"paragraph_id": 999, "quote": "禁碑"}]
        receipt = json.loads(
            await send_message.ainvoke({"notes": [{"text": "相邻块线索", "evidence": outside_evidence}]})
        )

        assert any("不属于本子块" in warning for warning in receipt["warnings"])
        assert delivered[0].report["notes"][0]["evidence"][0]["unverified"] is True

    @pytest.mark.asyncio
    async def test_dialogue_candidate_index_out_of_range_warns_and_delivers(self) -> None:
        """U2 修订：候选序号越界 → 警告照常送达，不做章级折算"""
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        receipt = json.loads(
            await send_message.ainvoke(
                {"dialogues": [{"candidate_index": 99, "verdict": "dialogue", "speaker": "白芷"}]}
            )
        )

        assert any("超出本块候选范围" in warning for warning in receipt["warnings"])
        assert any("取本块 <DialogueCandidates> 表里展示的编号" in warning for warning in receipt["warnings"])
        item = delivered[0].report["dialogues"][0]
        assert item["candidate_index"] == 99
        assert "chapter_candidate_index" not in item

    def test_candidate_index_block_local_numbering_stated_on_reader_surfaces(self) -> None:
        """修复五（09-12）：读者面两处入口都明确 candidate_index 是块内 1 基编号"""
        ledger = _reader_ledger()
        send_message = _reader_tools(ledger, delivered=[])["send_message"]
        assert send_message.description is not None
        assert "块内 1 基" in send_message.description

        message = build_reader_block_message(
            block_number=1,
            block_total=2,
            paragraph_info=ledger.paragraph_info,
            candidates=ledger.dialogue_candidates,
        )
        assert "块内 1 基" in message

    @pytest.mark.asyncio
    async def test_dialogue_valid_maps_chapter_candidate_index(self) -> None:
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        await send_message.ainvoke(
            {
                "dialogues": [
                    {
                        "candidate_index": 1,
                        "verdict": "dialogue",
                        "speaker": "白芷",
                        "tone": "平静",
                        "evidence": [{"paragraph_id": 101, "quote": "槐叶赠你。"}],
                    }
                ]
            }
        )

        assert delivered[0].report["dialogues"][0]["chapter_candidate_index"] == 7

    @pytest.mark.asyncio
    async def test_paragraph_label_emotion_out_of_range_warns_and_delivers(self) -> None:
        """2026-09-14 句标签退役：观察组改名 paragraph_labels（{paragraph_id, emotion}），
        emotion 越界 -2..2 走 warnings、照常送达"""
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        receipt = json.loads(
            await send_message.ainvoke({"paragraph_labels": [{"paragraph_id": 102, "emotion": 5}]})
        )

        assert any("-2..2" in warning for warning in receipt["warnings"])
        assert delivered[0].report["paragraph_labels"][0]["emotion"] == 5

    @pytest.mark.asyncio
    async def test_note_without_evidence_no_warning(self) -> None:
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        receipt = json.loads(await send_message.ainvoke({"notes": [{"text": "块边界线索"}]}))

        assert receipt["accepted"] is True
        assert receipt["warnings"] == []
        assert "evidence" not in delivered[0].report["notes"][0]

    @pytest.mark.asyncio
    async def test_non_note_without_evidence_warns(self) -> None:
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        no_evidence_case = {key: value for key, value in _case_item().items() if key != "evidence"}
        receipt = json.loads(await send_message.ainvoke({"cases": [no_evidence_case]}))

        assert any("缺少 evidence" in warning for warning in receipt["warnings"])
        assert delivered[0].report["cases"][0]["signal"] == "坐实"

    @pytest.mark.asyncio
    async def test_entity_extra_field_delivered_as_is_with_warning(self) -> None:
        """09-12 实测高频违规：entity 多带 state 字段 → 警告但原样送达（写者读得懂）"""
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        receipt = json.loads(
            await send_message.ainvoke(
                {
                    "entities": [
                        {
                            "name": "马骁",
                            "entity_type": "character",
                            "state": {"身份": "太学学子"},
                            "evidence": [{"paragraph_id": 101, "quote": "白芷赠槐叶给顾霜"}],
                        }
                    ]
                }
            )
        )

        assert any("实体载荷不符合实体合同" in warning for warning in receipt["warnings"])
        item = delivered[0].report["entities"][0]
        assert item["state"] == {"身份": "太学学子"}
        assert "unverified" not in item["evidence"][0]

    @pytest.mark.asyncio
    async def test_second_call_rejected(self) -> None:
        """一次性合同：同一激活内第二次调用被拒绝"""
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        await send_message.ainvoke({"notes": [{"text": "第一条"}]})
        with pytest.raises(Exception, match="只允许调用一次"):
            await send_message.ainvoke({"notes": [{"text": "第二条"}]})
        assert len(delivered) == 1

    @pytest.mark.asyncio
    async def test_empty_call_delivers_nothing(self) -> None:
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        send_message = _reader_tools(ledger, delivered=delivered)["send_message"]

        receipt = json.loads(await send_message.ainvoke({}))

        assert receipt["accepted"] is True
        assert receipt["report_delivered"] is False
        assert delivered == []


class TestReaderReportHelpers:
    def test_entity_name_keys_collects_all_groups(self) -> None:
        report = ReaderReport(
            block_index=0,
            report={
                "entities": [{"name": "白芷", "entity_type": "character"}],
                "relations": [{"from_entity": "白芷", "to_entity": "顾霜", "relation_type": "赠予"}],
                "event_trees": [
                    {
                        "description": "赠叶",
                        "participants": [{"entity": "顾霜", "role": "主体"}],
                        "children": [
                            {
                                "type": "main",
                                "description": "收下",
                                "participants": [{"entity": "秦穆", "role": "客体"}],
                            }
                        ],
                    }
                ],
                "dialogues": [{"candidate_index": 1, "verdict": "dialogue", "speaker": "秦穆"}],
                "cases": [{"signal": "坐实", "entities": ["禁碑"], "observation": "x"}],
            },
        )

        keys = report_entity_name_keys([report])

        assert keys == {"白芷", "顾霜", "秦穆", "禁碑"}

    def test_case_quotes_excludes_unverified(self) -> None:
        report = ReaderReport(
            block_index=0,
            report={
                "cases": [
                    {
                        "signal": "坐实",
                        "observation": "x",
                        "evidence": [
                            {"paragraph_id": 102, "quote": "秦穆重申禁碑以南不可进入"},
                            {"paragraph_id": 102, "quote": "编造的引文", "unverified": True},
                        ],
                    }
                ],
                "notes": [{"text": "n", "evidence": [{"paragraph_id": 102, "quote": "非案例引文"}]}],
            },
        )

        assert report_case_quotes([report]) == ("秦穆重申禁碑以南不可进入",)

    def test_writer_view_renders_reports_in_block_order_with_placeholder(self) -> None:
        reports: list[ReaderReport | None] = [
            ReaderReport(
                block_index=1,
                report={"dialogues": [{"candidate_index": 1, "verdict": "dialogue", "chapter_candidate_index": 7}]},
                warnings=["dialogues[0] 某警告"],
            ),
            None,
            ReaderReport(block_index=0, report={"cases": [_case_item()]}),
        ]

        view = render_reader_reports(reports, block_total=3)

        assert view.index('block="1"') < view.index('block="2"') < view.index('block="3"')
        assert "（本块读者未上报观察）" in view
        assert "chapter_candidate_index" in view
        assert "format_warnings" in view
        assert "秦穆重申禁碑以南不可进入" in view


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
    async def test_reader_completes_on_no_tool_response_after_single_report(self) -> None:
        """读者无工具回复=上报完毕（require_tool_call=False 语义），一次性报告随产出返回"""
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        tools = _reader_tools(ledger, delivered=delivered)
        llm = _SequenceLLM(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call(
                            "send_message",
                            {
                                "cases": [_case_item()],
                                "notes": [{"text": "蹄印指向下一块"}],
                            },
                            "call-1",
                        )
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
        assert len(delivered) == 1
        assert list(delivered[0].report.keys()) == ["cases", "notes"]
        assert llm.calls == 2

    @pytest.mark.asyncio
    async def test_reader_reports_error_when_iteration_cap_reached(self) -> None:
        ledger = _reader_ledger()
        delivered: list[ReaderReport] = []
        tools = _reader_tools(ledger, delivered=delivered)
        llm = _SequenceLLM(
            [
                AIMessage(
                    content="",
                    tool_calls=[_tool_call("send_message", {"notes": [{"text": "t"}]}, "call-1")],
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
    async def test_writer_rejects_entity_names_outside_reports(self) -> None:
        """U4：写者写读者报告外的实体名 → 拒绝

        2026-09-13 取消暂存：实体登记从整批 write_entities 改为一次一个 write_entity，
        准入改为逐条写入即判定——报告外的名字依旧被拒绝（准入失败），但同批合法的名字
        不再被整条失败牵连（失败不丢已写入记录），这是单条记录边界下最接近的等价物。
        2026-09-14 write_entity 另必填模型自定的 el 章内引用键（apply_entity 的 el 参数）。
        """
        from src.agents.annotation.schema import EntityInput

        ledger = _reader_ledger()
        ledger.reader_reports = [
            ReaderReport(
                block_index=0,
                report={"entities": [{"name": "白芷", "entity_type": "character"}]},
            )
        ]

        ledger.apply_entity(EntityInput(name="白芷", entity_type="character"), el="白芷")
        with pytest.raises(ValueError, match="准入失败"):
            ledger.apply_entity(EntityInput(name="从未上报的实体", entity_type="character"), el="从未上报的实体")

        assert set(ledger.written_entities) == {"白芷"}

    @pytest.mark.asyncio
    async def test_writer_accepts_entity_names_from_reports_or_graph(self) -> None:
        """报告内实体名经 write_entity 写入即生效（2026-09-13 取消暂存后无域回执）"""
        from src.agents.annotation.schema import EntityInput

        ledger = _reader_ledger()
        ledger.reader_reports = [
            ReaderReport(
                block_index=0,
                report={"entities": [{"name": "白芷", "entity_type": "character"}]},
            )
        ]

        number = ledger.apply_entity(EntityInput(name="白芷", entity_type="character"), el="白芷")

        assert number is not None
        assert set(ledger.written_entities) == {"白芷"}
        assert ledger.domain_payloads["entities"].entities[0].name == "白芷"
        assert ledger.graph is not None and "白芷" in ledger.graph.entity_types

    @pytest.mark.asyncio
    async def test_case_reason_requires_verified_quote_fragment_from_reports(self) -> None:
        ledger = _reader_ledger()
        ledger.reader_reports = [
            ReaderReport(
                block_index=0,
                report={
                    "cases": [
                        {
                            "signal": "坐实",
                            "observation": "x",
                            "evidence": [{"paragraph_id": 101, "quote": "白芷赠槐叶给顾霜，暗示旧约仍在"}],
                        }
                    ]
                },
            )
        ]
        ledger.case_number_registry[3] = "case-1"

        # 完整引文 → 通过
        ledger.admit_case_reason("原文：白芷赠槐叶给顾霜，暗示旧约仍在，故坐实", tool_name="close_case")
        # ≥12 字连续片段 → 通过（引文共 15 字，前 12 字是合法片段）
        ledger.admit_case_reason("读者证据表明白芷赠槐叶给顾霜，暗示旧，案例坐实", tool_name="close_case")
        # 纯转写 → 拒绝
        with pytest.raises(ValueError, match="引文片段"):
            ledger.admit_case_reason("我觉得这个案例可以关闭了", tool_name="close_case")

    @pytest.mark.asyncio
    async def test_case_reason_rejects_unverified_quotes(self) -> None:
        """09-12 裁决：unverified 引文不得支撑案例裁决"""
        ledger = _reader_ledger()
        ledger.reader_reports = [
            ReaderReport(
                block_index=0,
                report={
                    "cases": [
                        {
                            "signal": "坐实",
                            "observation": "x",
                            "evidence": [
                                {"paragraph_id": 101, "quote": "白芷赠槐叶给顾霜，暗示旧约仍在", "unverified": True}
                            ],
                        }
                    ]
                },
            )
        ]
        ledger.case_number_registry[3] = "case-1"

        with pytest.raises(ValueError, match="已核验引文"):
            ledger.admit_case_reason("原文：白芷赠槐叶给顾霜，暗示旧约仍在，故坐实", tool_name="close_case")

    @pytest.mark.asyncio
    async def test_case_reason_rejected_when_reports_have_no_cases(self) -> None:
        ledger = _reader_ledger()
        ledger.reader_reports = [ReaderReport(block_index=0, report={"notes": [{"text": "t"}]})]

        with pytest.raises(ValueError, match="已核验引文"):
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

        with pytest.raises(AnnotationRetryableError):
            await run_reader_agent(
                run_id="run-1",
                chapter_id=20,
                context=context,
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
        # 2026-09-14 【进度账本】只注入写者面：读者没有写入域，不得携带注入块
        assert not any("进度账本" in str(message.content) for message in captured["messages"])
        first_human = captured["messages"][1].content
        assert '<paragraph id="101">' in first_human
        assert "CurrentSubBlock" in first_human
        assert "白芷赠槐叶给顾霜" in first_human
        assert "一次性上报" in first_human
