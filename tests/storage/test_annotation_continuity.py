"""章节 Agent 连续性查询仓储测试"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.agents.annotation.schema import CasePayload, CaseSearchResult, Evidence, GraphSearchResult
from src.storage.models import ChapterAnnotationRecord, GraphEntity
from src.storage.repositories.annotation.continuity import (
    CasePoolRepository,
    DatabaseAnnotationQueryService,
)
from src.storage.repositories.graph import persist_completion_graph
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    identity_relation_output,
    persist_chapter_annotation,
)


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
        payload=CasePayload(
            keys=["顾霜"],
            description="真实身份悬而未决",
        ),
        evidence=Evidence(reason="本章没有揭示身份", chapterid=1),
    )
    db_session.commit()
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_last_chunk_id=0,
    )

    key_matches = [
        item
        for item in service.search_continuity("顾霜", hidden_case_ids=set()).results
        if isinstance(item, CaseSearchResult)
    ]
    description_matches = [
        item
        for item in service.search_continuity("身份悬而未决", hidden_case_ids=set()).results
        if isinstance(item, CaseSearchResult)
    ]

    assert [item.id for item in key_matches] == [row.id]
    assert [item.id for item in description_matches] == [row.id]
    assert [item.id for item in service.fetch_active_cases([row.id])] == [row.id]


def test_graph_search_returns_nodes_edges_and_properties(db_session) -> None:
    """2026-08-06 用于验证 Agent search 返回图节点边和完整属性"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门"],
        title="图结构查询",
    )
    annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[character_fact(chunk_id=0, name="顾霜", action="进入山门")],
    )
    annotation = db_session.get(ChapterAnnotationRecord, annotation_id)
    assert annotation is not None
    persist_completion_graph(
        db_session,
        annotation=annotation,
        fact_outputs=[
            identity_relation_output(
                subject_name="霜姐",
                object_name="顾霜",
                representative_endpoint="object",
            )
        ],
    )
    db_session.commit()
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_last_chunk_id=0,
    )

    graph_results = [
        item
        for item in service.search_continuity("霜姐", hidden_case_ids=set()).results
        if isinstance(item, GraphSearchResult)
    ]

    assert graph_results
    assert any(
        node.label == "霜姐"
        for item in graph_results
        for node in item.matched_nodes
    )
    assert any(
        edge.properties.get("relation_semantics") == "same_character"
        for item in graph_results
        for edge in item.matched_edges
    )
    entity_rows = list(
        db_session.execute(
            select(GraphEntity)
            .where(GraphEntity.run_id == run_id)
            .order_by(GraphEntity.entity_id)
        )
        .scalars()
        .all()
    )
    assert {row.canonical_name for row in entity_rows} == {"顾霜", "霜姐"}
    assert [row.canonical_name for row in entity_rows if row.is_representative] == ["顾霜"]


def test_after_search_returns_only_matching_later_chunks(db_session) -> None:
    """2026-08-06 用于验证后文搜索只返回当前位置之后的匹配章节与 chunk"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜在当前章现身", "第二章没有目标内容", "第三章顾霜身份揭晓"],
        chapter_ids=[1, 2, 3],
        title="后文动态检索",
    )
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_last_chunk_id=0,
    )

    results = service.search_after("顾霜")

    assert [(item.chapter_id, item.chunk_id) for item in results] == [(3, 2)]
    assert "顾霜" in results[0].excerpt
    assert service.read_after_chunk(chapter_id=3, chunk_id=2) == "第三章顾霜身份揭晓"
    with pytest.raises(ValueError, match="after chunk 不存在"):
        service.read_after_chunk(chapter_id=1, chunk_id=0)
