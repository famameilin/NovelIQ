"""章节 Agent 连续性查询仓储测试"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import select

from src.agents.annotation.schema import (
    BoundDialogue,
    BoundForeshadowing,
    CaseSearchResult,
    PendingCase,
)
from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.config import settings
from src.preprocess.tokenize import tokenize
from src.storage.models import (
    Chapter,
    DialogueRecord,
    ForeshadowingThread,
    ForeshadowingThreadHit,
)
from src.storage.repositories import ForeshadowingRepository
from src.storage.repositories.annotation.continuity import (
    CasePoolRepository,
    DatabaseAnnotationQueryService,
    DialogueRecordRepository,
)
from src.storage.repositories.paragraph_repository import ParagraphRepository
from tests.support.chapter_annotation_helpers import (
    create_run_with_chunks,
    persist_chapter_annotation,
)


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
    for chunk_id, (chapter_id, text) in enumerate(zip(resolved_chapter_ids, texts, strict=True)):
        chunks.append(
            Chunk(
                index=chunk_id,
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


def test_case_search_returns_id_for_keys_and_description_pull(db_session) -> None:
    """2026-08-06 用于验证案例按 keys 与 description 查得真实 ID 后可回读"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜身份成谜"],
        title="案例联合检索",
    )
    annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
    )
    row = CasePoolRepository(db_session).create_case(
        run_id=run_id,
        annotation_id=annotation_id,
        pending_case=PendingCase(
            type="dialogue_speaker",
            keys=["顾霜"],
            description="真实身份悬而未决",
            chunk_id=1,
            target_key="target-case-1",
            target_ref={
                "kind": "dialogue",
                "dialogue_id": "candidate-1",
                "chunk_id": 1,
                "start": 0,
                "end": 2,
                "text": "顾霜",
            },
        ),
    )
    db_session.commit()
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=1,
        current_first_paragraph_id=0,
        current_last_paragraph_id=0,
    )

    key_matches = [
        item
        for item in service.search_pool("顾霜", hidden_case_ids=set()).results
        if isinstance(item, CaseSearchResult)
    ]
    description_matches = [
        item
        for item in service.search_pool("身份悬而未决", hidden_case_ids=set()).results
        if isinstance(item, CaseSearchResult)
    ]

    assert [item.id for item in key_matches] == [row.id]
    assert [item.id for item in description_matches] == [row.id]
    details = service.fetch_active_case_details(row.id)
    assert details is not None
    assert details.id == row.id
    assert details.type == "dialogue_speaker"


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
        db_session,
        run_id=run_id,
        current_chapter_id=500,
        current_first_paragraph_id=2,
        current_last_paragraph_id=2,
    )

    previous = await service.search_text("顾霜", range_name="previous")
    future = await service.search_text("顾霜", range_name="future")
    all_results = await service.search_text("顾霜", range_name="all")

    assert [(item.chapter_id, item.paragraph_ids) for item in previous] == [(100, [1])]
    assert previous[0].content == "前文顾霜初次现身"
    assert [(item.chapter_id, item.paragraph_ids) for item in future] == [(900, [0])]
    assert future[0].content == "后文顾霜身份揭晓"
    assert {(item.chapter_id, tuple(item.paragraph_ids), item.content) for item in all_results} == {
        (100, (1,), "前文顾霜初次现身"),
        (500, (2,), "当前章顾霜入城"),
        (900, (0,), "后文顾霜身份揭晓"),
    }


def test_foreshadowing_sync_dedupes_by_setup_event_id(db_session) -> None:
    """2026-08-18 用于验证去重键为 setup_event_id：同事件不重复建线程，不同事件各建一条"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜持 Sword 现身"],
        title="伏笔事件去重",
    )
    repository = ForeshadowingRepository(db_session)
    # 同一 setup_event_id 两次 sync（描述大小写不同）→ 去重，仅 1 线程 1 hit
    first_thread, first_hit = repository.sync(
        run_id=run_id,
        chapter_id=1,
        foreshadowing=BoundForeshadowing(
                        description="顾霜持 Sword",
                        confidence="high",
                        setup_node_id="event-setup-1",
                        setup_kind="悬念",
                        expected_payoff_family="身份揭露",
                        payoff_likelihood="medium",
                    ),
        setup_event_id="event-setup-1",
    )
    second_thread, second_hit = repository.sync(
        run_id=run_id,
        chapter_id=1,
        foreshadowing=BoundForeshadowing(
                        description="顾霜持 sword",
                        confidence="high",
                        setup_node_id="event-setup-1",
                        setup_kind="悬念",
                        expected_payoff_family="身份揭露",
                        payoff_likelihood="medium",
                    ),
        setup_event_id="event-setup-1",
    )
    db_session.commit()

    assert second_thread.setup_id == first_thread.setup_id
    assert first_hit is not None
    # 同章节同 thread 重复 sync 是纯 no-op：不重复写 hit、不制造假命中
    assert second_hit is None
    threads = list(
        db_session.execute(select(ForeshadowingThread).where(ForeshadowingThread.run_id == run_id)).scalars()
    )
    assert len(threads) == 1
    hits = list(
        db_session.execute(select(ForeshadowingThreadHit).where(ForeshadowingThreadHit.run_id == run_id)).scalars()
    )
    assert len(hits) == 1

    # 不同 setup_event_id 即使描述完全相同也各建一条线程
    third_thread, third_hit = repository.sync(
        run_id=run_id,
        chapter_id=1,
        foreshadowing=BoundForeshadowing(
                        description="顾霜持 sword",
                        confidence="high",
                        setup_node_id="event-setup-2",
                        setup_kind="悬念",
                        expected_payoff_family="身份揭露",
                        payoff_likelihood="medium",
                    ),
        setup_event_id="event-setup-2",
    )
    db_session.commit()
    assert third_thread.setup_id != first_thread.setup_id
    assert third_hit is not None and third_hit.is_new_setup is True
    threads = list(
        db_session.execute(select(ForeshadowingThread).where(ForeshadowingThread.run_id == run_id)).scalars()
    )
    assert len(threads) == 2


def test_foreshadowing_sync_existing_thread_writes_hit_and_advances_last_chapter(db_session) -> None:
    """2026-08-13 P1-3 用于验证已存在 thread 在更大 chunk 再次命中时补写 hit 并推进 last_chapter_id"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜立誓", "顾霜再誓"],
        chapter_ids=[1, 2],
        title="伏笔续接命中",
    )
    repository = ForeshadowingRepository(db_session)
    first_thread, first_hit = repository.sync(
        run_id=run_id,
        chapter_id=1,
        foreshadowing=BoundForeshadowing(
                        description="顾霜承诺护佑山门",
                        confidence="high",
                        setup_node_id="event-护佑",
                        setup_kind="承诺",
                        expected_payoff_family="守护",
                        payoff_likelihood="high",
                    ),
        setup_event_id="event-护佑",
    )
    assert first_thread.last_chapter_id == 1
    assert first_hit is not None and first_hit.is_new_setup is True

    second_thread, second_hit = repository.sync(
        run_id=run_id,
        chapter_id=2,
        foreshadowing=BoundForeshadowing(
                        description="顾霜承诺护佑山门",
                        confidence="high",
                        setup_node_id="event-护佑",
                        setup_kind="承诺",
                        expected_payoff_family="守护",
                        payoff_likelihood="high",
                    ),
        setup_event_id="event-护佑",
    )
    db_session.commit()

    assert second_thread.setup_id == first_thread.setup_id
    assert second_hit is not None
    assert second_hit.is_new_setup is False
    assert second_hit.chapter_id == 2
    # 新 chunk 更大时推进 last_chapter_id
    assert second_thread.last_chapter_id == 2
    hits = list(
        db_session.execute(
            select(ForeshadowingThreadHit)
            .where(ForeshadowingThreadHit.run_id == run_id)
            .order_by(ForeshadowingThreadHit.chapter_id)
        ).scalars()
    )
    assert [hit.chapter_id for hit in hits] == [1, 2]
    assert all(hit.setup_id == first_thread.setup_id for hit in hits)


def test_foreshadowing_sync_existing_thread_noop_on_same_chunk(db_session) -> None:
    """2026-08-13 P1-3 用于验证同 chunk 重复 sync 不推进 last_chapter_id 也不重复写 hit"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜立誓", "顾霜再誓", "顾霜三誓"],
        chapter_ids=[1, 2, 3],
        title="伏笔 no-op",
    )
    repository = ForeshadowingRepository(db_session)
    first_thread, _first_hit = repository.sync(
        run_id=run_id,
        chapter_id=2,
        foreshadowing=BoundForeshadowing(
                        description="顾霜承诺护佑山门",
                        confidence="high",
                        setup_node_id="event-护佑",
                        setup_kind="承诺",
                        expected_payoff_family="守护",
                        payoff_likelihood="high",
                    ),
        setup_event_id="event-护佑",
    )
    # 旧 chunk（0）再次 sync：新 chunk 更小，不得推进 last_chapter_id
    thread, hit = repository.sync(
        run_id=run_id,
        chapter_id=1,
        foreshadowing=BoundForeshadowing(
                        description="顾霜承诺护佑山门",
                        confidence="high",
                        setup_node_id="event-护佑",
                        setup_kind="承诺",
                        expected_payoff_family="守护",
                        payoff_likelihood="high",
                    ),
        setup_event_id="event-护佑",
    )
    db_session.commit()

    assert hit is not None
    assert thread.last_chapter_id == 2
    hits = list(
        db_session.execute(
            select(ForeshadowingThreadHit)
            .where(ForeshadowingThreadHit.run_id == run_id)
            .order_by(ForeshadowingThreadHit.chapter_id)
        ).scalars()
    )
    assert [hit.chapter_id for hit in hits] == [1, 2]


def test_sync_dialogues_dedupes_by_candidate_key_across_chunks(db_session) -> None:
    """2026-08-13 P2-4 用于验证幂等键为 (run_id, candidate_key)：跨章重复台词不再撞唯一约束"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["“住手”回荡。", "“住手”再次响起。"],
        chapter_ids=[1, 2],
        title="对话跨章去重",
    )
    repository = DialogueRecordRepository(db_session)
    dialogue = BoundDialogue(
        candidate_index=1,
        candidate_key="dlg_001",
        content="“住手”",
        start=0,
        end=3,
        speaker="顾霜",
        tone="平静",
    )
    first_rows = repository.sync_dialogues(
        run_id=run_id,
        chapter_id=1,
        dialogues=[dialogue],
    )
    # 第二章重复台词：按 (run_id, chapter_id) 查不到，但唯一约束是 (run_id, candidate_key)，
    # 修复后按 candidate_key 幂等，不重复写
    second_rows = repository.sync_dialogues(
        run_id=run_id,
        chapter_id=2,
        dialogues=[dialogue],
    )
    db_session.commit()

    assert len(first_rows) == 1
    assert second_rows == []
    rows = list(db_session.execute(select(DialogueRecord).where(DialogueRecord.run_id == run_id)).scalars())
    assert len(rows) == 1
    assert rows[0].candidate_key == "dlg_001"
    assert rows[0].chapter_id == 1


def test_sync_dialogues_weak_binds_event_id_by_char_span(db_session) -> None:
    """2026-08-18 P3 用于验证对话只有唯一事件匹配时才写入 event_id"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜拔剑喝止，“住手”回荡。"],
        title="对话事件弱关联",
    )
    repository = DialogueRecordRepository(db_session)
    dialogue = BoundDialogue(
        candidate_index=1,
        candidate_key="dlg_001",
        content="住手",
        start=8,
        end=11,
        speaker="顾霜",
        tone="紧张",
    )
    rows = repository.sync_dialogues(
        run_id=run_id,
        chapter_id=1,
        dialogues=[dialogue],
        event_anchors=[
            ("event-wide", 0, 17),
            ("event-narrow", 6, 12),
            ("event-unrelated", 20, 25),
        ],
    )
    db_session.commit()

    assert len(rows) == 1
    assert rows[0].event_id is None


def test_sync_dialogues_no_event_anchor_keeps_null(db_session) -> None:
    """2026-08-18 P3 用于验证对话不在任何事件区间内时 event_id 保持 None"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜拔剑喝止，“住手”回荡。"],
        title="对话事件无匹配",
    )
    repository = DialogueRecordRepository(db_session)
    dialogue = BoundDialogue(
        candidate_index=1,
        candidate_key="dlg_001",
        content="住手",
        start=8,
        end=11,
        speaker="顾霜",
        tone="紧张",
    )
    rows = repository.sync_dialogues(
        run_id=run_id,
        chapter_id=1,
        dialogues=[dialogue],
        event_anchors=[("event-a", 0, 5)],
    )
    db_session.commit()

    assert len(rows) == 1
    assert rows[0].event_id is None


def test_search_event_history_excludes_future_events_by_chapter_sequence_when_ids_are_out_of_order(
    db_session,
    monkeypatch,
) -> None:
    """2026-08-30 用于验证事件历史只返回当前章节序号之前的树根"""
    monkeypatch.setattr(settings.models.paragraph_embedding, "semantic_enabled", False)
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜在后文拔剑迎敌。", "顾霜进入山门。", "顾霜在当前章入城。"],
        chapter_ids=[900, 100, 500],
        title="事件历史章节序号边界",
    )
    sequence_by_chapter_id = {100: 1, 500: 2, 900: 3}
    chapters = db_session.execute(select(Chapter).where(Chapter.run_id == run_id)).scalars().all()
    for chapter in chapters:
        chapter.sequence = sequence_by_chapter_id[chapter.chapter_id]
    db_session.commit()
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=100,
        events=[
            {
                "description": "顾霜进入山门",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": "evt-history-gate",
            },
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=900,
        events=[
            {
                "description": "顾霜拔剑迎敌",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "node_id": "evt-history-draw",
            },
        ],
    )
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=500,
        current_first_paragraph_id=2,
        current_last_paragraph_id=2,
    )

    prior = service.search_event_history("顾霜")
    assert [item.description for item in prior] == ["顾霜进入山门"]
    assert prior[0].root_node_id == "evt-history-gate"
    assert prior[0].cross_chapter is False
    assert all(item.root_node_id != "evt-history-draw" for item in prior)


def test_search_event_history_returns_empty_when_no_match(db_session, monkeypatch) -> None:
    """2026-08-18 用于验证无文本匹配时事件历史检索返回空列表"""
    monkeypatch.setattr(settings.models.paragraph_embedding, "semantic_enabled", False)
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门。"],
        title="事件历史空检索",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜进入山门",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
            },
        ],
    )
    db_session.commit()

    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=1,
        current_first_paragraph_id=0,
        current_last_paragraph_id=0,
    )

    assert service.search_event_history("不存在的关键词") == []
