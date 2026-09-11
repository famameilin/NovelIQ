"""章内并行两段式工作流测试（monkeypatch 读者/写者运行器，无 DB 依赖）

对应《章内并行设计》§8/§16.1：
- 超长章两段式派发：每块一个读者、写者消费按块序消息池；
- U5 任一读者失败 → 取消其余在飞读者、整章失败、重跑重试；
- ask_reader 追问通道：轮数上限（进设置）、块号校验、新消息回执；
- 候选序号块→章映射。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.agents.annotation.errors import AnnotationInputError
from src.agents.annotation.messages import ReaderMessagePool
from src.agents.annotation.reader import ReaderRunOutcome
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    ChunkMetricsInput,
    ChunkParagraphInfo,
    NarrativeFunction,
)
from src.workflows.annotate_helpers import two_phase
from src.workflows.annotate_helpers.two_phase import (
    WriterAskReaderDispatcher,
    build_candidate_number_map,
    run_chapter_two_phase,
)

CHAPTER_TEXT = "第一段。" * 15  # 60 字，段落边界 0/20/40
SUB_CHUNKS = [(-1, CHAPTER_TEXT[:40], 0), (-2, CHAPTER_TEXT[40:], 40)]
PARAGRAPH_ROWS = [
    SimpleNamespace(paragraph_id=1, local_start_char=0, local_end_char=20, text=CHAPTER_TEXT[:20]),
    SimpleNamespace(paragraph_id=2, local_start_char=20, local_end_char=40, text=CHAPTER_TEXT[20:40]),
    SimpleNamespace(paragraph_id=3, local_start_char=40, local_end_char=60, text=CHAPTER_TEXT[40:]),
]


def _fake_writer_result() -> AgentRunResult:
    return AgentRunResult(
        run_id="run-1",
        chapter_id=1,
        annotation=BoundChapterAnnotation(
            chapter_summary="写者产出",
            chunks=[
                BoundChunkAnnotation(
                    chunk_id=1,
                    metrics=ChunkMetricsInput(
                        summary="写者产出",
                        emotional_valence=0,
                        narrative_function=NarrativeFunction.SETUP,
                    ),
                    character_observations=[],
                    dialogues=[],
                    events=[],
                    foreshadowings=[],
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


def _two_phase_kwargs() -> dict:
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


def _reader_outcome(block_index: int) -> ReaderRunOutcome:
    return ReaderRunOutcome(
        final_messages=[],
        authorized_text_paragraph_ids={100 + block_index},
        authorized_chapter_ids={5},
    )


class TestTwoPhaseDispatch:
    @pytest.mark.asyncio
    async def test_dispatches_one_reader_per_block_and_passes_pool_view_to_writer(
        self, monkeypatch
    ) -> None:
        """切几块开几个读者；写者首条请求携带按块序的消息池快照；审计足迹并入"""
        captured: dict = {}

        async def fake_reader(*, context, pool, **kwargs):
            del kwargs
            pool.append(
                block_index=context.block_index,
                kind="note",
                summary=f"块{context.block_index + 1}观察",
                payload={"text": "n"},
                evidence=[],
            )
            return _reader_outcome(context.block_index)

        async def fake_writer(**kwargs):
            captured.update(kwargs)
            return _fake_writer_result()

        monkeypatch.setattr(two_phase, "run_reader_agent", fake_reader)
        monkeypatch.setattr(two_phase, "run_annotation_agent", fake_writer)

        result = await run_chapter_two_phase(**_two_phase_kwargs())

        writer_message = captured["initial_messages_override"][1].content
        assert "块1观察" in writer_message
        assert "块2观察" in writer_message
        assert writer_message.index("块1观察") < writer_message.index("块2观察")
        assert captured["current_chunks"] == [(1, CHAPTER_TEXT)]
        assert captured["sub_chunk_index"] == 0
        assert captured["paragraph_info"].paragraph_ids == [1, 2, 3]
        assert isinstance(captured["reader_message_pool"], ReaderMessagePool)
        assert isinstance(captured["ask_reader_dispatcher"], WriterAskReaderDispatcher)
        # 读者授权段落（100、101）并入写者审计，案例授权章（5）一并并入
        assert result.audit.authorized_text_paragraph_ids == [2, 100, 101]
        assert set(result.audit.authorized_chapter_ids) == {1, 5}

    @pytest.mark.asyncio
    async def test_reader_failure_cancels_remaining_readers_and_fails_chapter(
        self, monkeypatch
    ) -> None:
        """U5：任一读者失败 → 其余在飞读者被取消、整章失败"""
        calls: list[int] = []
        cancelled: list[int] = []

        async def fake_reader(*, context, pool, **kwargs):
            del pool, kwargs
            calls.append(context.block_index)
            if context.block_index == 1:
                raise RuntimeError("reader boom")
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.append(context.block_index)
                raise
            return _reader_outcome(context.block_index)

        monkeypatch.setattr(two_phase, "run_reader_agent", fake_reader)

        with pytest.raises(RuntimeError, match="reader boom"):
            await asyncio.wait_for(run_chapter_two_phase(**_two_phase_kwargs()), timeout=10)

        assert cancelled == [0]
        # 失败块按 §8.5 会话级重跑 ≤2 次（首次 + 2 重试）
        assert calls.count(1) == 3


class TestWriterAskReaderDispatcher:
    def _dispatcher(self, pool: ReaderMessagePool, *, max_ask_rounds: int) -> WriterAskReaderDispatcher:
        from src.agents.annotation.reader import ReaderBlockContext

        contexts = [
            ReaderBlockContext(
                block_index=index,
                block_count=2,
                block_chunk_id=-(index + 1),
                block_text="块文本",
                paragraph_info=ChunkParagraphInfo(
                    paragraph_ids=[index + 1],
                    char_spans=[(0, 3)],
                    texts=["块文本"],
                ),
                candidate_number_map={},
            )
            for index in range(2)
        ]
        outcomes = [
            ReaderRunOutcome(final_messages=[], authorized_text_paragraph_ids=set(), authorized_chapter_ids=set())
            for _ in contexts
        ]
        return WriterAskReaderDispatcher(
            pool=pool,
            contexts=contexts,
            outcomes=outcomes,
            run_id="run-1",
            chapter_id=1,
            llm=MagicMock(),
            graph_state=None,
            query_service_factory=MagicMock(),
            session_factory=MagicMock(),
            stream=None,
            chapter_label=None,
            novel_id="default",
            max_ask_rounds=max_ask_rounds,
        )

    @pytest.mark.asyncio
    async def test_ask_returns_new_message_summaries_and_updates_outcome(self, monkeypatch) -> None:
        pool = ReaderMessagePool()
        dispatcher = self._dispatcher(pool, max_ask_rounds=0)
        captured: dict = {}

        async def fake_reader(*, context, pool, prior_messages, writer_question, **kwargs):
            del kwargs
            captured["question"] = writer_question
            captured["prior_len"] = len(prior_messages)
            pool.append(
                block_index=context.block_index,
                kind="note",
                summary="追问后的新观察",
                payload={"text": "新观察"},
                evidence=[],
            )
            return ReaderRunOutcome(
                final_messages=[object(), object()],
                authorized_text_paragraph_ids=set(),
                authorized_chapter_ids=set(),
            )

        monkeypatch.setattr(two_phase, "run_reader_agent", fake_reader)

        reply = json.loads(await dispatcher.ask(1, "请补查蹄印方向"))

        assert captured["question"] == "请补查蹄印方向"
        assert reply["accepted"] is True
        assert reply["block"] == 1
        assert [item["summary"] for item in reply["new_messages"]] == ["追问后的新观察"]
        assert pool.message_count() == 1

    @pytest.mark.asyncio
    async def test_ask_returns_only_this_continuation_messages_across_blocks(self, monkeypatch) -> None:
        """池按块序排序：追问前块时不得因切片错位取到后块的旧消息"""
        pool = ReaderMessagePool()
        pool.append(block_index=0, kind="note", summary="块1旧消息", payload={"text": "a"}, evidence=[])
        pool.append(block_index=1, kind="note", summary="块2旧消息", payload={"text": "b"}, evidence=[])
        dispatcher = self._dispatcher(pool, max_ask_rounds=0)

        async def fake_reader(*, context, pool, prior_messages, writer_question, **kwargs):
            del prior_messages, writer_question, kwargs
            pool.append(
                block_index=context.block_index,
                kind="note",
                summary="块1追问新消息",
                payload={"text": "new"},
                evidence=[],
            )
            return ReaderRunOutcome(
                final_messages=[], authorized_text_paragraph_ids=set(), authorized_chapter_ids=set()
            )

        monkeypatch.setattr(two_phase, "run_reader_agent", fake_reader)

        reply = json.loads(await dispatcher.ask(1, "补查"))

        assert [item["summary"] for item in reply["new_messages"]] == ["块1追问新消息"]

    @pytest.mark.asyncio
    async def test_ask_round_limit_configured_enforced(self, monkeypatch) -> None:
        """追问轮数上限来自设置 writer_max_ask_rounds（0 不限）"""
        pool = ReaderMessagePool()
        dispatcher = self._dispatcher(pool, max_ask_rounds=2)

        async def fake_reader(**kwargs):
            del kwargs
            return ReaderRunOutcome(
                final_messages=[], authorized_text_paragraph_ids=set(), authorized_chapter_ids=set()
            )

        monkeypatch.setattr(two_phase, "run_reader_agent", fake_reader)

        await dispatcher.ask(1, "q1")
        await dispatcher.ask(1, "q2")
        with pytest.raises(AnnotationInputError, match="上限"):
            await dispatcher.ask(1, "q3")
        assert dispatcher.rounds_used == 2

    @pytest.mark.asyncio
    async def test_ask_rejects_block_out_of_range(self) -> None:
        pool = ReaderMessagePool()
        dispatcher = self._dispatcher(pool, max_ask_rounds=0)

        with pytest.raises(AnnotationInputError, match="超出范围"):
            await dispatcher.ask(9, "q")


class TestCandidateNumberMap:
    def test_block_local_candidates_map_to_chapter_indexes(self) -> None:
        chapter_text = "前文。“甲言。”中段。后文。“乙言。”"
        boundary = chapter_text.index("后文。")
        sub_chunks = [(-1, chapter_text[:boundary], 0), (-2, chapter_text[boundary:], boundary)]

        maps = build_candidate_number_map(
            chapter_chunk_id=1,
            chapter_text=chapter_text,
            sub_chunks=sub_chunks,
        )

        assert maps[0][1] == 1  # 块1 候选1 → 章候选1
        assert maps[1][1] == 2  # 块2 候选1 → 章候选2

    def test_truncated_boundary_quote_maps_to_none(self) -> None:
        """切分点落在引号内部时块内出现截断候选，映射为 None 由写者自行对照"""
        chapter_text = "前文。“跨块引号句子”后文。“乙言。”"
        # 块边界切在引号内部
        cut = chapter_text.index("跨块") + 2
        sub_chunks = [(-1, chapter_text[:cut], 0), (-2, chapter_text[cut:], cut)]

        maps = build_candidate_number_map(
            chapter_chunk_id=1,
            chapter_text=chapter_text,
            sub_chunks=sub_chunks,
        )

        assert maps[0][1] is None  # 块1 的 unclosed_quote 截断候选
        assert maps[1][1] == 2  # 块2 内完整引号与章级候选 2 对齐
