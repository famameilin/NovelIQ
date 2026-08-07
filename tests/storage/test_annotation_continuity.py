"""章节 Agent 连续性查询仓储测试"""

from __future__ import annotations

import pytest

from src.agents.annotation.schema import CaseSearchResult, EvidenceList, PushedCase, TextEvidence
from src.config import settings
from src.storage.repositories.annotation.continuity import (
    CasePoolRepository,
    DatabaseAnnotationQueryService,
)
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
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
        pushed_case=PushedCase(
            keys=["顾霜"],
            description="真实身份悬而未决",
            type="dialogue_speaker",
            chunkid=0,
            target_key="target-case-1",
            target_anchor={
                "chunk_id": 0,
                "start": 0,
                "end": 2,
                "text": "顾霜",
            },
            target_ref={
                "kind": "dialogue",
                "item_ref": "dialogue_1",
                "chunk_id": 0,
                "start": 0,
                "end": 2,
                "text": "顾霜",
                "fact_id": "fact-dialogue-1",
                "fact_revision": 1,
            },
        ),
        evidence=EvidenceList(root=[TextEvidence(reason="本章没有揭示身份", chunk_id=0)]),
    )
    db_session.commit()
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=1,
        current_first_chunk_id=0,
        current_last_chunk_id=0,
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


def test_graph_search_returns_nodes_edges_and_properties(db_session) -> None:
    """2026-08-06 用于验证 Agent search 返回图节点边和完整属性"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["霜姐即顾霜", "第二章继续调查"],
        chapter_ids=[1, 2],
        title="图结构查询",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="霜姐", action="身份显露"),
            character_fact(chunk_id=0, name="顾霜", action="身份确认"),
        ],
        relations=[
            relation_fact(
                chunk_id=0,
                from_name="霜姐",
                to_name="顾霜",
                relation_type="同一人物",
                directionality="bidirectional",
                relation_semantics="same_character",
                representative_endpoint="object",
            )
        ],
    )
    db_session.commit()
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=2,
        current_first_chunk_id=1,
        current_last_chunk_id=1,
    )

    graph_result = service.search_graph("霜姐")

    assert graph_result is not None
    assert graph_result.graph_version_id == service.previous_graph_version.graph_version_id
    assert {entity.name for entity in graph_result.entities} == {"顾霜", "霜姐"}
    assert len(graph_result.relations) == 1
    assert graph_result.relations[0].relation_semantics == "same_character"
    assert graph_result.relations[0].attributes["representative_entity_id"] in {
        entity.existing_entity_id for entity in graph_result.entities if entity.name == "顾霜"
    }


@pytest.mark.asyncio
async def test_text_search_returns_only_matching_later_chunks(db_session, monkeypatch) -> None:
    """2026-08-06 用于验证后文搜索只返回当前位置之后的匹配章节与 chunk"""
    monkeypatch.setattr(settings.text_retrieval, "semantic_enabled", False)
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜在当前章现身", "第二章没有目标内容", "第三章顾霜身份揭晓"],
        chapter_ids=[1, 2, 3],
        title="后文动态检索",
    )
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=1,
        current_first_chunk_id=0,
        current_last_chunk_id=0,
    )

    results = await service.search_text("顾霜", range_name="future")

    assert [(item.chapter_id, item.chunk_id) for item in results] == [(3, 2)]
    assert "顾霜" in results[0].excerpt
    assert service.read_text(2) == "第三章顾霜身份揭晓"
    with pytest.raises(ValueError, match="原文 chunk 不存在或跨 run"):
        service.read_text(999)


def test_graph_search_uses_nearest_completed_chapter_order_instead_of_id_math(db_session) -> None:
    """2026-08-07 用于验证非连续 chapter_id 仍读取最近已完成章节图版本"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["第十章已完成", "第二十章未完成", "第三十章当前输入"],
        chapter_ids=[10, 20, 30],
        title="非连续章节顺序",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=10,
        characters=[character_fact(chunk_id=0, name="顾霜", action="现身")],
    )
    db_session.commit()

    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=30,
        current_first_chunk_id=2,
        current_last_chunk_id=2,
    )

    assert service.previous_graph_version is not None
    assert service.previous_graph_version.chapter_id == 10
