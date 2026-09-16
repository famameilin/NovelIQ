"""2026-09-16 章内并行 CodeAct 调度器测试（monkeypatch 块/章运行器，无 DB 依赖）

覆盖调度器契约：切几块开几并发（无信号量、无共享池）、块完成顺序不构成语义顺序、
任一失败取消其余在飞块并整章失败、块授权足迹与案例编号并入章账本、
章会话注入合并程序面（唯一 execute_code）与句柄索引首条消息、
关闭 codeact 的显式拒绝、边界段落与待决项视图。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.agents.annotation.block_program import BlockRunOutcome
from src.agents.annotation.chapter_merge import build_block_reports
from src.agents.annotation.errors import AnnotationInputError
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.local_ir import (
    BlockAnnotation,
    LocalEvidence,
    LocalMention,
    LocalPending,
)
from src.agents.annotation.reader_report import ReaderReport
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    ChunkMetricsInput,
    ChunkParagraphInfo,
    NarrativeFunction,
    SearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools
from src.config import settings
from src.workflows.annotate_helpers import block_codeact
from src.workflows.annotate_helpers.block_codeact import (
    build_block_boundaries,
    build_block_contexts,
    render_pending_view,
    run_chapter_block_codeact,
)

CHAPTER_TEXT = "第一段。" * 15  # 60 字，段落边界 0/20/40
SUB_CHUNKS = [(-1, CHAPTER_TEXT[:40], 0), (-2, CHAPTER_TEXT[40:], 40)]
PARAGRAPH_ROWS = [
    SimpleNamespace(paragraph_id=1, local_start_char=0, local_end_char=20, text=CHAPTER_TEXT[:20]),
    SimpleNamespace(paragraph_id=2, local_start_char=20, local_end_char=40, text=CHAPTER_TEXT[20:40]),
    SimpleNamespace(paragraph_id=3, local_start_char=40, local_end_char=60, text=CHAPTER_TEXT[40:]),
]


class _QueryService:
    """用于提供无数据库依赖的查询桩"""

    current_chapter_order = None

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """用于返回空案例检索结果"""
        del query, hidden_case_ids, case_type, limit, pending_cases
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        """用于返回空正文命中"""
        del query, range_name, limit
        return []

    def search_event_history(self, query, *, limit=50):
        """用于返回空历史事件树"""
        del query, limit
        return []


def _block(*, block_index: int, mentions: list[LocalMention], pending: list[LocalPending]) -> BlockAnnotation:
    """用于构造一个块的局部标注产出"""
    return BlockAnnotation(
        block_index=block_index,
        block_chunk_id=-(block_index + 1),
        block_text=SUB_CHUNKS[block_index][1],
        mentions=mentions,
        pending=pending,
    )


def _mention(*, key: str, name: str, paragraph_id: int) -> LocalMention:
    """用于构造一条带已核验证据的块内提及"""
    return LocalMention(
        key=key,
        name=name,
        entity_type="character",
        tags=[],
        description=None,
        attributes=None,
        evidence=(LocalEvidence(paragraph_id=paragraph_id, quote=name),),
    )


def _blocks() -> list[BlockAnnotation]:
    """用于构造两个块的生产形态产出（跨块同名人物 + 一条待决项）"""
    first = _block(
        block_index=0,
        mentions=[_mention(key="m1", name="顾霜", paragraph_id=1)],
        pending=[
            LocalPending(
                key="p1",
                kind="event_continuation",
                detail="本块末尾的冲突疑似在后块继续",
                evidence=(),
                handles=["B1:m1"],
                case_id="case-9",
            )
        ],
    )
    second = _block(
        block_index=1,
        mentions=[_mention(key="m1", name="顾霜", paragraph_id=3)],
        pending=[],
    )
    return [first, second]


def _outcome(block: BlockAnnotation, *, case_ids: set[str] | None = None) -> BlockRunOutcome:
    """用于构造一次块会话的产出（授权足迹按块号区分，便于断言并集）"""
    return BlockRunOutcome(
        block=block,
        final_messages=[],
        authorized_text_paragraph_ids={100 + block.block_index},
        authorized_chapter_ids={7},
        authorized_event_ids={f"ev-{block.block_index}"},
        authorized_tree_ids=set(),
        case_ids=case_ids or set(),
    )


def _fake_chapter_result() -> AgentRunResult:
    """用于构造章会话返回的章级结果"""
    return AgentRunResult(
        run_id="run-1",
        chapter_id=1,
        annotation=BoundChapterAnnotation(
            chapter_summary="章节代理产出",
            chunks=[
                BoundChunkAnnotation(
                    chunk_id=1,
                    metrics=ChunkMetricsInput(
                        summary="章节代理产出",
                        emotional_valence=0,
                        narrative_function=NarrativeFunction.SETUP,
                    ),
                    character_observations=[],
                    dialogues=[],
                    events=[],
                )
            ],
        ),
        resolved_cases=[],
        audit=AgentRunAudit(
            allow_future_context=False,
            write_records=[],
            authorized_chapter_ids=[1],
            authorized_text_paragraph_ids=[2],
        ),
    )


def _kwargs() -> dict:
    """用于构造调度器的完整入参"""
    return {
        "run_id": "run-1",
        "chapter_id": 1,
        "chapter_chunk_id": 1,
        "chapter_text": CHAPTER_TEXT,
        "chapter_paragraph_rows": list(PARAGRAPH_ROWS),
        "sub_chunks": list(SUB_CHUNKS),
        "llm": MagicMock(),
        "sql_session_factory": MagicMock(),
        "query_service_factory": MagicMock(),
        "graph_state": None,
        "stream": None,
        "novel_id": "default",
        "novel_title": None,
        "chapter_label": "第1章",
    }


@pytest.fixture(autouse=True)
def _codeact_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """用于默认开启程序面（关闭行为的用例自行覆盖）"""
    monkeypatch.setattr(settings.models.annotation, "codeact_enabled", True)


class TestBlockDispatch:
    @pytest.mark.asyncio
    async def test_dispatches_one_block_agent_per_chunk_concurrently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """切几块开几个块代理（同一事件循环里并发起跑），全部产出按块序装配"""
        contexts: list[object] = []
        inflight = 0
        peak = 0
        gate = asyncio.Event()

        async def fake_block_agent(*, context, **kwargs):
            del kwargs
            nonlocal inflight, peak
            contexts.append(context)
            inflight += 1
            peak = max(peak, inflight)
            if len(contexts) == 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), timeout=5)
            inflight -= 1
            return _outcome(_blocks()[context.block_index])

        async def fake_chapter_agent(**kwargs):
            del kwargs
            return _fake_chapter_result()

        monkeypatch.setattr(block_codeact, "run_block_agent", fake_block_agent)
        monkeypatch.setattr(block_codeact, "run_annotation_agent", fake_chapter_agent)

        await run_chapter_block_codeact(**_kwargs())

        assert [context.block_index for context in contexts] == [0, 1]
        # 两块同时在场：并发度 = 块数（没有并发闸门，靠"两块都进到等待点"证明）
        assert peak == 2
        first = contexts[0]
        assert first.block_count == 2
        assert first.paragraph_info.paragraph_ids == [1, 2]
        assert first.candidate_number_map == {}

    @pytest.mark.asyncio
    async def test_chapter_session_gets_handle_index_and_merge_surface(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """章会话：块句柄索引进首条消息、只读正文的候选走章级表、合并程序面按账本注入"""
        captured: dict = {}

        async def fake_block_agent(*, context, **kwargs):
            del kwargs
            return _outcome(_blocks()[context.block_index], case_ids={"case-9"})

        async def fake_chapter_agent(**kwargs):
            captured.update(kwargs)
            return _fake_chapter_result()

        monkeypatch.setattr(block_codeact, "run_block_agent", fake_block_agent)
        monkeypatch.setattr(block_codeact, "run_annotation_agent", fake_chapter_agent)

        await run_chapter_block_codeact(**_kwargs())

        message = captured["initial_messages_override"][1].content
        assert "<BlockAnnotations>" in message
        assert "B1:m1" in message and "B2:m1" in message
        assert message.index("B1:m1") < message.index("B2:m1")
        assert "<PendingItems>" in message and "B1:p1" in message
        assert "case-9" in message
        assert captured["current_chunks"] == [(1, CHAPTER_TEXT)]
        assert captured["sub_chunk_index"] == 0
        assert captured["program_mode"] is True
        assert captured["paragraph_info"].paragraph_ids == [1, 2, 3]
        assert [report.block_index for report in captured["reader_reports"]] == [0, 1]
        assert all(isinstance(report, ReaderReport) for report in captured["reader_reports"])
        assert captured["reader_reports"] == build_block_reports(_blocks())

    @pytest.mark.asyncio
    async def test_block_failure_cancels_inflight_blocks_and_fails_chapter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """块失败没有升级分支：其余在飞块被取消，整章失败"""
        cancelled: list[int] = []

        async def fake_block_agent(*, context, **kwargs):
            del kwargs
            if context.block_index == 1:
                raise RuntimeError("block boom")
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.append(context.block_index)
                raise
            return _outcome(_blocks()[0])

        async def fake_chapter_agent(**kwargs):
            del kwargs
            raise AssertionError("块失败时不得进入章会话")

        monkeypatch.setattr(block_codeact, "run_block_agent", fake_block_agent)
        monkeypatch.setattr(block_codeact, "run_annotation_agent", fake_chapter_agent)

        with pytest.raises(RuntimeError, match="block boom"):
            await asyncio.wait_for(run_chapter_block_codeact(**_kwargs()), timeout=10)

        assert cancelled == [0]

    @pytest.mark.asyncio
    async def test_requires_codeact_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """块面路径是 CodeAct 路径：关闭程序面时显式拒绝，不静默退化成原生写者"""
        monkeypatch.setattr(settings.models.annotation, "codeact_enabled", False)

        with pytest.raises(AnnotationInputError, match="codeact_enabled"):
            await run_chapter_block_codeact(**_kwargs())


class TestChapterProgramFactory:
    @pytest.mark.asyncio
    async def test_factory_merges_authorizations_and_builds_single_program_tool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """工厂先并入块授权足迹与案例编号，再返回合并面的唯一 execute_code"""
        captured: dict = {}

        async def fake_block_agent(*, context, **kwargs):
            del kwargs
            return _outcome(_blocks()[context.block_index], case_ids={"case-9"})

        async def fake_chapter_agent(**kwargs):
            captured.update(kwargs)
            return _fake_chapter_result()

        monkeypatch.setattr(block_codeact, "run_block_agent", fake_block_agent)
        monkeypatch.setattr(block_codeact, "run_annotation_agent", fake_chapter_agent)

        await run_chapter_block_codeact(**_kwargs())

        ledger = AnnotationToolLedger(
            run_scope="run-1",
            current_chapter_id=1,
            current_chunk_id=1,
            current_chunk_text=CHAPTER_TEXT,
            allow_future_context=False,
            graph=FactGraph(),
            paragraph_info=ChunkParagraphInfo(
                paragraph_ids=[1, 2, 3],
                char_spans=[(0, 20), (20, 40), (40, 60)],
                texts=[row.text for row in PARAGRAPH_ROWS],
            ),
        )
        tool = captured["program_tool_factory"](
            build_annotation_tools(_QueryService(), ledger), ledger, observer=None, stream=None
        )

        assert str(tool.name) == "execute_code"
        # 合并构造器目录随工具描述下发（模型可见面：一条工具 + 一份 API 目录）
        for constructor in ("bind", "import_relation", "merge_dialogues", "tree", "event", "metric"):
            assert f"{constructor}(" in str(tool.description)
        # 块授权足迹并入章账本：正文段落、授权章、事件、案例编号
        assert ledger.authorized_text_paragraph_ids == {100, 101}
        assert ledger.authorized_chapter_ids == {7}
        assert ledger.authorized_event_ids == {"ev-0", "ev-1"}
        assert set(ledger.case_number_registry.values()) == {"case-9"}


class TestBlockContexts:
    def test_contexts_carry_boundary_paragraphs_readonly(self) -> None:
        """边界段落=相邻一个完整段落；首块无前邻、末块无后邻"""
        contexts = build_block_contexts(
            chapter_paragraph_rows=list(PARAGRAPH_ROWS),
            sub_chunks=list(SUB_CHUNKS),
            candidate_maps=[{}, {}],
        )

        assert contexts[0].boundary_before is None
        assert contexts[0].boundary_after == (3, CHAPTER_TEXT[40:])
        assert contexts[1].boundary_before == (2, CHAPTER_TEXT[20:40])
        assert contexts[1].boundary_after is None

    def test_boundary_paragraphs_are_full_paragraphs(self) -> None:
        """边界段取整段原文（不是切片），且只取紧邻的一段"""
        rows = list(PARAGRAPH_ROWS)
        before, after = build_block_boundaries(
            rows,
            sub_chunk_offset=SUB_CHUNKS[1][2],
            sub_chunk_text=SUB_CHUNKS[1][1],
        )

        assert before == (2, rows[1].text)
        assert after is None


class TestPendingView:
    def test_renders_handle_kind_detail_and_extras(self) -> None:
        """待决项视图给出句柄、类别、详情与相关句柄/案例 id"""
        view = render_pending_view(_blocks())

        assert view.startswith("- B1:p1 [event_continuation] 本块末尾的冲突疑似在后块继续")
        assert "相关句柄：B1:m1" in view
        assert "案例 id：case-9" in view

    def test_empty_when_no_pending(self) -> None:
        """没有待决项时整块不出现（章节代理首条消息不带空区块）"""
        assert render_pending_view([]) == ""
        assert render_pending_view([_block(block_index=0, mentions=[], pending=[])]) == ""
