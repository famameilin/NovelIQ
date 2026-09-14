"""章节 Agent 连续性查询仓储测试"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.agents.annotation.schema import (
    BoundDialogue,
    CaseSearchResult,
    PendingCase,
)
from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.config import settings
from src.preprocess.tokenize import tokenize
from src.storage.models import (
    Chapter,
    DialogueRecord,
)
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


def _create_case(
    db_session,
    *,
    run_id: str,
    annotation_id: str,
    case_type: str,
    keys: list[str],
    description: str,
    target_key: str,
    chunk_id: int = 1,
) -> str:
    """2026-09-11 用于批量造案例行并返回 id（检索制测试的准备口）

    2026-09-13 登记即进池后案例行 id 就是 target_key，而 id 是全库主键：
    传入的 target_key 一律加 uuid 后缀，避免跨用例复用同一字面量时撞主键。
    """
    row = CasePoolRepository(db_session).create_case(
        run_id=run_id,
        annotation_id=annotation_id,
        pending_case=PendingCase(
            type=case_type,
            keys=keys,
            description=description,
            chunk_id=chunk_id,
            target_key=f"{target_key}-{uuid4().hex[:8]}",
            target_ref={"kind": case_type, "chunk_id": chunk_id},
        ),
    )
    db_session.commit()
    return row.id


def test_search_pool_case_type_enumeration_and_summary(db_session) -> None:
    """2026-09-11 案例改检索制：case_type 枚举不依赖关键词，回执带池内规模与类型分布

    案例不再注入正文，无正文词汇可锚定的案例（如 entity_alias）只能靠枚举检索；
    pool 汇报未被隐藏的 active 规模与类型分布，供模型判断是否还有未展示案例。
    """
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"], title="案例枚举")
    annotation_id = persist_chapter_annotation(db_session, run_id=run_id, chapter_id=1)
    first_alias = _create_case(
        db_session,
        run_id=run_id,
        annotation_id=annotation_id,
        case_type="entity_alias",
        keys=["同一人物"],
        description="疑似同一人物：顾霜 与 顾老",
        target_key="target-alias-1",
    )
    second_alias = _create_case(
        db_session,
        run_id=run_id,
        annotation_id=annotation_id,
        case_type="entity_alias",
        keys=["同一人物"],
        description="疑似同一人物：顾霜 与 顾母",
        target_key="target-alias-2",
    )
    suspicion = _create_case(
        db_session,
        run_id=run_id,
        annotation_id=annotation_id,
        case_type="伏笔疑点",
        keys=["玉戒尺"],
        description="玉戒尺异动待察",
        target_key="target-thread-1",
    )
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=1,
        current_first_paragraph_id=0,
        current_last_paragraph_id=0,
    )

    everything = service.search_pool(None, hidden_case_ids=set(), case_type="all")
    only_alias = service.search_pool(None, hidden_case_ids=set(), case_type="entity_alias")
    hidden_first = service.search_pool(None, hidden_case_ids={first_alias}, case_type="all")

    assert {item.id for item in everything.results} == {first_alias, second_alias, suspicion}
    # 枚举按最新创建优先（同为 entity_alias，后建的排在前面）
    assert [item.id for item in only_alias.results] == [second_alias, first_alias]
    assert all(item.created_chapter == 1 for item in everything.results)
    assert everything.pool.active_total == 3
    assert everything.pool.by_type == {"entity_alias": 2, "伏笔疑点": 1}
    assert everything.truncated is False
    # 隐藏（已解决）案例不计入枚举，也不计入池规模
    assert {item.id for item in hidden_first.results} == {second_alias, suspicion}
    assert hidden_first.pool.active_total == 2
    assert hidden_first.pool.by_type == {"entity_alias": 1, "伏笔疑点": 1}


def test_search_pool_enumeration_marks_truncation_at_limit(db_session) -> None:
    """2026-09-11 枚举超过 limit 时只返回前 limit 条并标记 truncated"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"], title="案例枚举截断")
    annotation_id = persist_chapter_annotation(db_session, run_id=run_id, chapter_id=1)
    for index in range(3):
        _create_case(
            db_session,
            run_id=run_id,
            annotation_id=annotation_id,
            case_type="entity_alias",
            keys=["同一人物"],
            description=f"疑似同一人物：第{index}对",
            target_key=f"target-alias-{index}",
        )
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=1,
        current_first_paragraph_id=0,
        current_last_paragraph_id=0,
    )

    limited = service.search_pool(None, hidden_case_ids=set(), case_type="entity_alias", limit=2)

    assert len(limited.results) == 2
    assert limited.truncated is True
    assert limited.pool.active_total == 3


def test_search_pool_keyword_hit_marks_truncation_and_keeps_summary(db_session) -> None:
    """2026-09-11 关键词检索命中达到 limit 时同样标记 truncated，池规模不受影响"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"], title="案例关键词截断")
    annotation_id = persist_chapter_annotation(db_session, run_id=run_id, chapter_id=1)
    for index in range(3):
        _create_case(
            db_session,
            run_id=run_id,
            annotation_id=annotation_id,
            case_type="伏笔疑点",
            keys=["玉戒尺"],
            description=f"玉戒尺异动第{index}次",
            target_key=f"target-thread-{index}",
        )
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=1,
        current_first_paragraph_id=0,
        current_last_paragraph_id=0,
    )

    limited = service.search_pool("玉戒尺", hidden_case_ids=set(), limit=2)

    assert len(limited.results) == 2
    assert limited.truncated is True
    assert limited.pool.active_total == 3
    assert limited.pool.by_type == {"伏笔疑点": 3}


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


def _persist_plot_tree(db_session, run_id: str) -> str:
    """2026-09-04 用于在第 1 章落一棵根+子两节点的事件树（子节点含赤羽炽尾鸡），返回根节点 id

    event_id 是全局主键，节点 id 必须每个用例唯一，否则跨用例插入冲突被跳过。
    """
    root_node_id = f"evt-plot-root-{uuid4().hex[:8]}"
    tree_id = f"tree-plot-{uuid4().hex[:8]}"
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "伯安与发小在假山密谋偷灵兽",
                "participants": ["伯安"],
                "node_id": root_node_id,
                "tree_id": tree_id,
                "cause_role": "root",
            },
            {
                "description": "伯安提议偷赤羽炽尾鸡",
                "participants": ["伯安"],
                "tree_id": tree_id,
                "parent_node_id": root_node_id,
                "cause_role": "main",
            },
        ],
    )
    return root_node_id


@pytest.mark.parametrize(
    ("query", "expected_descriptions"),
    [
        pytest.param("赤羽炽尾鸡", ["伯安与发小在假山密谋偷灵兽"], id="子节点词命中返回树根"),
        pytest.param("偷%鸡", ["伯安与发小在假山密谋偷灵兽"], id="百分号通配符命中子节点"),
        pytest.param("赤羽_尾鸡", ["伯安与发小在假山密谋偷灵兽"], id="下划线通配符命中子节点"),
        pytest.param("伯安 偷鸡", ["伯安与发小在假山密谋偷灵兽"], id="多词任一命中即返回"),
        pytest.param("偷鸡", [], id="无词项命中返回空"),
    ],
)
def test_search_event_history_recall_surface_and_wildcards(
    db_session,
    monkeypatch,
    query: str,
    expected_descriptions: list[str],
) -> None:
    """2026-09-04 用于验证召回面扩到树内任意节点且词项支持 %/_ 通配符与多词 OR"""
    monkeypatch.setattr(settings.models.paragraph_embedding, "semantic_enabled", False)
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["第一章。", "第二章。"],
        chapter_ids=[1, 2],
        title="事件树召回面",
    )
    root_node_id = _persist_plot_tree(db_session, run_id)
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=2,
        current_first_paragraph_id=1,
        current_last_paragraph_id=1,
    )

    results = service.search_event_history(query)

    assert [item.description for item in results] == expected_descriptions
    if expected_descriptions:
        assert results[0].root_node_id == root_node_id


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
        db_session,
        run_id=run_id,
        current_chapter_id=2,
        current_first_paragraph_id=1,
        current_last_paragraph_id=1,
    )

    wildcard = await service.search_text("偷%鸡", range_name="previous", limit=8)
    multi = await service.search_text("伯安 风雪", range_name="all", limit=8)
    miss = await service.search_text("不存在词", range_name="previous", limit=8)

    assert any("赤羽炽尾鸡" in item.content for item in wildcard)
    assert {item.chapter_id for item in multi} == {1, 2}
    assert miss == []


def test_search_pool_includes_pending_cases_from_same_chunk(db_session) -> None:
    """2026-09-13 登记即进池：本 chunk 内 push_case 登记的待建案例当章即可检索到

    待建案例的池行要到本章收尾才落库，检索面不因此缺席：与池内案例走同一套
    关键词/枚举语义，并一并计入池规模与类型分布。用例数据取自 run 1b388eb3
    第 2 章实况——模型登记"误建关系"案例后按关键词反复检索却全零命中。
    """
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["贺铮误认林立果为子"], title="待建案例检索")
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=1,
        current_first_paragraph_id=0,
        current_last_paragraph_id=0,
    )
    pending = CaseSearchResult(
        id="pending-target-1",
        type="关系修正",
        chunk_id=1,
        created_chapter=1,
        keys=["贺铮", "林立果", "家族"],
        description="误建关系：二人并非父子，需解除该边",
    )

    by_keyword = service.search_pool("林立果", hidden_case_ids=set(), pending_cases=[pending])
    by_type = service.search_pool(None, hidden_case_ids=set(), case_type="all", pending_cases=[pending])
    other_type = service.search_pool(
        None,
        hidden_case_ids=set(),
        case_type="entity_alias",
        pending_cases=[pending],
    )
    hidden = service.search_pool(
        "林立果",
        hidden_case_ids={pending.id},
        pending_cases=[pending],
    )

    assert [item.id for item in by_keyword.results] == [pending.id]
    assert by_keyword.pool.active_total == 1
    assert by_keyword.pool.by_type == {"关系修正": 1}
    # 枚举（case_type=all）同样能看到待建案例，类型不匹配时按类型过滤掉
    assert [item.id for item in by_type.results] == [pending.id]
    assert other_type.results == []
    # 已解决（隐藏）的待建案例不再出现在检索面，也不计入池规模
    assert hidden.results == []
    assert hidden.pool.active_total == 0
    assert hidden.pool.by_type == {}
