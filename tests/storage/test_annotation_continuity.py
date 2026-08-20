"""章节 Agent 连续性查询仓储测试"""

from __future__ import annotations

from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

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
async def test_text_search_returns_only_matching_later_paragraphs(db_session, monkeypatch) -> None:
    """2026-08-14 二期段落化：后文搜索按段落边界返回当前位置之后的匹配段落"""
    monkeypatch.setattr(settings.models.paragraph_embedding, "semantic_enabled", False)
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜在当前章现身", "第二章没有目标内容", "第三章顾霜身份揭晓"],
        chapter_ids=[1, 2, 3],
        title="后文动态检索",
    )
    _insert_paragraphs(
        db_session,
        run_id,
        ["顾霜在当前章现身", "第二章没有目标内容", "第三章顾霜身份揭晓"],
        chapter_ids=[1, 2, 3],
    )
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=1,
        # 当前章（chapter 1）的段落边界：只有 paragraph_id=0
        current_first_paragraph_id=0,
        current_last_paragraph_id=0,
    )

    results = await service.search_text("顾霜", range_name="future")

    assert [(item.chapter_id, item.paragraph_id) for item in results] == [(3, 2)]
    assert "顾霜" in results[0].excerpt
    # read_text 按 paragraph_id 读目标段 + 默认上下文（前后各一段，换行分隔）
    assert service.read_text(2) == "第二章没有目标内容\n第三章顾霜身份揭晓"
    with pytest.raises(ValueError, match="原文段落不存在或跨 run"):
        service.read_text(999)


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
            description="顾霜持 Sword", confidence="high", setup_event_index=1
        ),
        setup_event_id="event-setup-1",
    )
    second_thread, second_hit = repository.sync(
        run_id=run_id,
        chapter_id=1,
        foreshadowing=BoundForeshadowing(
            description="顾霜持 sword", confidence="high", setup_event_index=1
        ),
        setup_event_id="event-setup-1",
    )
    db_session.commit()

    assert second_thread.setup_id == first_thread.setup_id
    assert first_hit is not None
    # 同章节同 thread 重复 sync 是纯 no-op：不重复写 hit、不制造假命中
    assert second_hit is None
    threads = list(
        db_session.execute(
            select(ForeshadowingThread).where(ForeshadowingThread.run_id == run_id)
        ).scalars()
    )
    assert len(threads) == 1
    hits = list(
        db_session.execute(
            select(ForeshadowingThreadHit).where(ForeshadowingThreadHit.run_id == run_id)
        ).scalars()
    )
    assert len(hits) == 1

    # 不同 setup_event_id 即使描述完全相同也各建一条线程
    third_thread, third_hit = repository.sync(
        run_id=run_id,
        chapter_id=1,
        foreshadowing=BoundForeshadowing(
            description="顾霜持 sword", confidence="high", setup_event_index=2
        ),
        setup_event_id="event-setup-2",
    )
    db_session.commit()
    assert third_thread.setup_id != first_thread.setup_id
    assert third_hit is not None and third_hit.is_new_setup is True
    threads = list(
        db_session.execute(
            select(ForeshadowingThread).where(ForeshadowingThread.run_id == run_id)
        ).scalars()
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
            description="顾霜承诺护佑山门", confidence="high", setup_event_index=1
        ),
        setup_event_id="event-护佑",
    )
    assert first_thread.last_chapter_id == 1
    assert first_hit is not None and first_hit.is_new_setup is True

    second_thread, second_hit = repository.sync(
        run_id=run_id,
        chapter_id=2,
        foreshadowing=BoundForeshadowing(
            description="顾霜承诺护佑山门", confidence="high", setup_event_index=1
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
            description="顾霜承诺护佑山门", confidence="high", setup_event_index=1
        ),
        setup_event_id="event-护佑",
    )
    # 旧 chunk（0）再次 sync：新 chunk 更小，不得推进 last_chapter_id
    thread, hit = repository.sync(
        run_id=run_id,
        chapter_id=1,
        foreshadowing=BoundForeshadowing(
            description="顾霜承诺护佑山门", confidence="high", setup_event_index=1
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
    rows = list(
        db_session.execute(
            select(DialogueRecord).where(DialogueRecord.run_id == run_id)
        ).scalars()
    )
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


def test_search_event_history_returns_events_within_chapter_boundary(db_session, monkeypatch) -> None:
    """2026-08-19 用于验证事件历史检索按章节边界过滤"""
    monkeypatch.setattr(settings.models.paragraph_embedding, "semantic_enabled", False)
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门。", "顾霜拔剑迎敌。"],
        chapter_ids=[1, 2],
        title="事件历史检索",
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
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        events=[
            {
                "description": "顾霜拔剑迎敌",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
            },
        ],
    )
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=2,
        current_first_paragraph_id=0,
        current_last_paragraph_id=0,
    )

    prior = service.search_event_history("顾霜", max_chapter_order=1)
    assert [item.description for item in prior] == ["顾霜进入山门"]
    assert prior[0].event_id == str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:1"))

    visible = service.search_event_history("顾霜", max_chapter_order=2)
    by_desc = {item.description: item for item in visible}
    assert set(by_desc) == {"顾霜进入山门", "顾霜拔剑迎敌"}
    assert len(visible) == 2
    latest_payoff = by_desc["顾霜拔剑迎敌"]
    assert latest_payoff.event_id == str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:2:1"))
    # Evidence 反序列化为 TextEvidence（含 64 位 hex 文本哈希）
    assert len(latest_payoff.evidence) == 1
    assert len(latest_payoff.evidence[0].text_hash) == 64


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

    assert service.search_event_history("不存在的关键词", max_chapter_order=1) == []
