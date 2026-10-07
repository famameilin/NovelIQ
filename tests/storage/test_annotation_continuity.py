"""章节 Agent 连续性查询仓储测试"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config import settings
from src.storage.models import (
    Chapter,
)
from src.storage.repositories.annotation.continuity import (
    DatabaseAnnotationQueryService,
)
from src.storage.repositories.paragraph_repository import ParagraphRepository
from src.storage.text_units import Chunk
from src.utils.tokenize import tokenize
from src.workflows.paragraphs import split_chunk_paragraphs
from tests.support.chapter_annotation_helpers import (
    create_run_with_chunks,
)
from tests.support.model_stream_adapter import StreamedFakeModelMixin


def _factory(session):
    """2026-09-16 用于把测试会话包成查询工厂（每个查询各开一条新会话，与生产 sessionmaker 同形）

    查询服务按单次工具调用取还连接，所以工厂必须是"可反复调用开新会话"的对象；
    测试数据都已提交，新会话与既有会话同库同 schema、可见同样的行。
    """
    return lambda: Session(bind=session.get_bind())


class _CountedSession:
    """2026-09-16 用于记账一条查询会话是否被归还（除 execute/close 外全部转发真实会话）"""

    def __init__(self, inner, *, fail_on_execute: bool = False) -> None:
        """2026-09-16 用于绑定被记账的真实会话"""
        self._inner = inner
        self._fail_on_execute = fail_on_execute
        self.closed = False

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def execute(self, *args, **kwargs):
        if self._fail_on_execute:
            raise RuntimeError("查询失败")
        return self._inner.execute(*args, **kwargs)

    def close(self) -> None:
        self.closed = True
        self._inner.close()


class _SessionTracker:
    """2026-09-16 用于统计查询会话开合：live 是当前已开未关的会话数"""

    def __init__(self, session, *, fail_on_execute: bool = False) -> None:
        """2026-09-16 用于绑定被借用的真实会话"""
        self._bind = session.get_bind()
        self._fail_on_execute = fail_on_execute
        self.sessions: list[_CountedSession] = []

    @property
    def live(self) -> int:
        """2026-09-16 用于读取仍未归还的查询会话数"""
        return sum(1 for session in self.sessions if not session.closed)

    def factory(self):
        """2026-09-16 用于按次开一条被记账的查询会话"""
        counted = _CountedSession(Session(bind=self._bind), fail_on_execute=self._fail_on_execute)
        self.sessions.append(counted)
        return counted


def _insert_paragraphs(
    db_session,
    run_id: str,
    texts: list[str],
    chapter_ids: list[int] | None = None,
) -> tuple[int, int]:
    """2026-08-14 二期段落化：检索边界为段落事实源，测试须先落段落行并返回 min/max"""
    resolved_chapter_ids = chapter_ids or [1] * len(texts)
    offset = 0
    chunks = []
    for chapter_id, (chapter_id, text) in enumerate(zip(resolved_chapter_ids, texts, strict=True)):
        chunks.append(
            Chunk(
                index=chapter_id,
                text=text,
                start=offset,
                end=offset + len(text),
                chapter_id=chapter_id,
            )
        )
        offset += len(text)
    spans = split_chunk_paragraphs(chunks)
    spans = [replace(span, token_count=len(tokenize(span.text))) for span in spans]
    ParagraphRepository(db_session).insert_paragraphs(run_id, spans)
    db_session.commit()
    return 0, len(spans) - 1


@pytest.mark.asyncio
async def test_text_search_ranges_use_chapter_sequence_when_ids_are_out_of_order(db_session, monkeypatch) -> None:
    """2026-08-30 用于验证 previous/future/all 不依赖 chapter_id 或 paragraph_id 排序"""
    monkeypatch.setattr(settings.models.paragraph_embedding, "semantic_enabled", False)
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        # 段落 ID 将按输入顺序为 0/1/2，故后文章的段落 ID 反而最小
        texts=["后文顾霜身份揭晓", "前文顾霜初次现身", "当前章顾霜入城"],
        chapter_ids=[900, 100, 500],
        title="章节序号严格前文检索",
    )
    sequence_by_chapter_id = {100: 1, 500: 2, 900: 3}
    chapters = db_session.execute(select(Chapter).where(Chapter.run_id == run_id)).scalars().all()
    for chapter in chapters:
        chapter.sequence = sequence_by_chapter_id[chapter.chapter_id]
    db_session.commit()
    service = DatabaseAnnotationQueryService(
        _factory(db_session),
        run_id=run_id,
        current_chapter_id=500,
        current_first_paragraph_id=2,
        current_last_paragraph_id=2,
    )

    previous = await service.search_text("顾霜", range_name="previous")
    future = await service.search_text("顾霜", range_name="future")
    all_results = await service.search_text("顾霜", range_name="all")

    assert [(item.chapter_id, item.paragraph_id) for item in previous] == [(100, 1)]
    assert previous[0].excerpt == "前文顾霜初次现身"
    assert [(item.chapter_id, item.paragraph_id) for item in future] == [(900, 0)]
    assert future[0].excerpt == "后文顾霜身份揭晓"
    assert {(item.chapter_id, item.paragraph_id, item.excerpt) for item in all_results} == {
        (100, 1, "前文顾霜初次现身"),
        (500, 2, "当前章顾霜入城"),
        (900, 0, "后文顾霜身份揭晓"),
    }


@pytest.mark.asyncio
async def test_search_text_keyword_channel_supports_wildcards_and_multi_terms(
    db_session,
    monkeypatch,
) -> None:
    """2026-09-04 用于验证原文关键词通道按通配符与多词 OR 命中段落"""
    monkeypatch.setattr(settings.models.paragraph_embedding, "semantic_enabled", False)
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["伯安提议偷赤羽炽尾鸡，众人称好。", "贺兰山的风雪很大。"],
        chapter_ids=[1, 2],
        title="原文通配符检索",
    )
    service = DatabaseAnnotationQueryService(
        _factory(db_session),
        run_id=run_id,
        current_chapter_id=2,
        current_first_paragraph_id=1,
        current_last_paragraph_id=1,
    )

    wildcard = await service.search_text("偷%鸡", range_name="previous", limit=8)
    multi = await service.search_text("伯安 风雪", range_name="all", limit=8)
    miss = await service.search_text("不存在词", range_name="previous", limit=8)

    assert any("赤羽炽尾鸡" in item.excerpt for item in wildcard)
    assert {item.chapter_id for item in multi} == {1, 2}
    assert miss == []


@pytest.mark.asyncio
async def test_query_scope_returns_every_session_even_when_query_fails(db_session, monkeypatch) -> None:
    """2026-09-16 连接粒度=单次工具调用：查询会话用完即还，抛错路径同样归还

    每次查询各开一条会话（构造期解析章节序也一样），作用域退出后一律已关闭；
    失败查询不得把连接留给下一次模型生成。
    """
    monkeypatch.setattr(settings.models.paragraph_embedding, "semantic_enabled", False)
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"], title="只读作用域取还连接")
    tracker = _SessionTracker(db_session)
    service = DatabaseAnnotationQueryService(
        tracker.factory,
        run_id=run_id,
        current_chapter_id=1,
        current_first_paragraph_id=0,
        current_last_paragraph_id=0,
    )

    # 构造期解析章节序只用一次性会话，此时连接已经归还
    assert tracker.live == 0
    assert [session.closed for session in tracker.sessions] == [True]

    await service.search_text("顾霜", range_name="all")
    assert tracker.live == 0
    assert len(tracker.sessions) == 2

    failing = _SessionTracker(db_session, fail_on_execute=True)
    with pytest.raises(RuntimeError):
        DatabaseAnnotationQueryService(
            failing.factory,
            run_id=run_id,
            current_chapter_id=1,
            current_first_paragraph_id=0,
            current_last_paragraph_id=0,
        )
    assert failing.live == 0
    assert [session.closed for session in failing.sessions] == [True]


@pytest.mark.asyncio
async def test_graph_round_holds_no_query_connection_while_model_replies(db_session) -> None:
    """2026-09-16 模型回话那一刻连接占用为零：检索工具用完即还，live 在每次模型调用时都是 0

    计数工厂挂在真实查询服务上，脚本化模型每次回话前现读 live——只要有一轮工具
    调用没归还连接，读数就不为 0。这条是"连接不再横跨模型延迟"的直接证据。
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from src.agents.annotation.subagent_graph import build_subagent_graph
    from src.agents.annotation.tools import AnnotationToolLedger
    from src.fact_graph.graph import FactGraph
    from src.fact_graph.schema import ChapterParagraphInfo
    from tests.support.annotation_work_tools import build_annotation_tools, build_program_test_runtime

    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"], title="模型回话不占连接")
    tracker = _SessionTracker(db_session)
    service = DatabaseAnnotationQueryService(
        tracker.factory,
        run_id=run_id,
        current_chapter_id=1,
        current_first_paragraph_id=0,
        current_last_paragraph_id=0,
    )
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=1,
        current_chapter_text="顾霜身份成谜",
        allow_future_context=False,
        graph=FactGraph(run_scope=run_id),
        paragraph_info=ChapterParagraphInfo(paragraph_ids=[0], char_spans=[(0, 6)], texts=["顾霜身份成谜"]),
    )
    tools = build_annotation_tools(service, ledger)
    live_at_model_reply: list[int] = []

    class _SearchThenFinishLLM(StreamedFakeModelMixin):
        """2026-09-16 用于把"检索案例池 + 写指标 + 收尾"放进同一个回合的脚本化模型"""

        def bind_tools(self, tools):
            del tools
            return self

        async def ainvoke(self, messages):
            del messages
            live_at_model_reply.append(tracker.live)
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "execute_code",
                        "args": {"code": 'search_text(query="顾霜")\n'
                                 'metric(summary="顾霜身份成谜", emotional_valence=0, narrative_function="铺垫")\n'
                                 'finish()'},
                        "id": "c2",
                        "type": "tool_call",
                    },
                ],
            )

    runtime = build_program_test_runtime(tools, ledger)
    graph = build_subagent_graph(
        _SearchThenFinishLLM(), runtime.build_tool(), runtime.finish_tool,
        ledger=ledger, subagent=runtime.subagent, max_iterations=1,
    )
    state = await graph.ainvoke(
        {
            "messages": [SystemMessage(content="test"), HumanMessage(content="chunk")],
            "phase": "chapter_open",
            "iterations": 0,
            "error": None,
        }
    )

    assert live_at_model_reply == [0]
    assert tracker.live == 0
    assert state["error"] is None
