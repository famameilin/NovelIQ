"""图验证器孤儿别名检测测试"""

from __future__ import annotations

from src.workflows.graph_verifier import build_alias_pending_cases, detect_alias_suspicions
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    identity_relation_output,
    persist_chapter_annotation,
    relation_fact,
)


def test_detect_alias_suspicions_finds_orphan_pair(db_session) -> None:
    """2026-08-09 用于验证验证器检出删姓别名且共享邻居的孤儿角色对"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["伯安与玩伴同游", "贺伯安与玩伴同游"],
        chapter_ids=[1, 2],
        title="图验证器孤儿检测",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="伯安", action="同游"),
            character_fact(chunk_id=1, name="猴子", action="同游"),
            character_fact(chunk_id=1, name="算盘", action="同游"),
        ],
        relations=[
            relation_fact(chunk_id=1, from_name="伯安", to_name="猴子", relation_type="友情"),
            relation_fact(chunk_id=1, from_name="伯安", to_name="算盘", relation_type="友情"),
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[
            character_fact(chunk_id=2, name="贺伯安", action="同游"),
            character_fact(chunk_id=2, name="猴子", action="同游"),
            character_fact(chunk_id=2, name="算盘", action="同游"),
        ],
        relations=[
            relation_fact(chunk_id=2, from_name="贺伯安", to_name="猴子", relation_type="友情"),
            relation_fact(chunk_id=2, from_name="贺伯安", to_name="算盘", relation_type="友情"),
        ],
    )
    db_session.commit()

    from sqlalchemy import select

    from src.storage.models import GraphVersion

    graph_version = (
        db_session.execute(
            select(GraphVersion)
            .where(GraphVersion.run_id == run_id)
            .order_by(GraphVersion.chapter_order.desc())
        )
        .scalars()
        .first()
    )
    pairs = {
        (item.name_a, item.name_b)
        for item in detect_alias_suspicions(db_session, graph_version=graph_version)
    }
    assert ("贺伯安", "伯安") in pairs or ("伯安", "贺伯安") in pairs


def test_detect_alias_suspicions_skips_merged_pairs(db_session) -> None:
    """2026-08-09 用于验证已用同一人物边归并的角色对不再重复疑似"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["伯安与侯飞白同游"],
        title="图验证器归并跳过",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="伯安", action="同游"),
            character_fact(chunk_id=1, name="猴子", action="同游"),
            character_fact(chunk_id=1, name="侯飞白", action="同游"),
        ],
        relations=[
            relation_fact(chunk_id=1, from_name="伯安", to_name="猴子", relation_type="友情"),
            identity_relation_output(subject_name="猴子", object_name="侯飞白", effective_chapter_id=1),
        ],
    )
    db_session.commit()

    from sqlalchemy import select

    from src.storage.models import GraphVersion

    graph_version = (
        db_session.execute(
            select(GraphVersion)
            .where(GraphVersion.run_id == run_id)
            .order_by(GraphVersion.chapter_order.desc())
        )
        .scalars()
        .first()
    )
    pairs = {
        (item.name_a, item.name_b)
        for item in detect_alias_suspicions(db_session, graph_version=graph_version)
    }
    assert pairs == set()


def test_build_alias_pending_cases_target_ref_carries_chunk_id(db_session) -> None:
    """2026-08-11 用于验证别名案例的 target_ref 携带 anchor chunk_id（解决落库依赖）"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["伯安与玩伴同游", "贺伯安与玩伴同游"],
        chapter_ids=[1, 2],
        title="图验证器别名案例 chunk_id",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="伯安", action="同游"),
            character_fact(chunk_id=1, name="猴子", action="同游"),
            character_fact(chunk_id=1, name="算盘", action="同游"),
        ],
        relations=[
            relation_fact(chunk_id=1, from_name="伯安", to_name="猴子", relation_type="友情"),
            relation_fact(chunk_id=1, from_name="伯安", to_name="算盘", relation_type="友情"),
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[
            character_fact(chunk_id=2, name="贺伯安", action="同游"),
            character_fact(chunk_id=2, name="猴子", action="同游"),
            character_fact(chunk_id=2, name="算盘", action="同游"),
        ],
        relations=[
            relation_fact(chunk_id=2, from_name="贺伯安", to_name="猴子", relation_type="友情"),
            relation_fact(chunk_id=2, from_name="贺伯安", to_name="算盘", relation_type="友情"),
        ],
    )
    db_session.commit()

    from sqlalchemy import select

    from src.storage.models import GraphVersion

    graph_version = (
        db_session.execute(
            select(GraphVersion)
            .where(GraphVersion.run_id == run_id)
            .order_by(GraphVersion.chapter_order.desc())
        )
        .scalars()
        .first()
    )
    pending_cases = build_alias_pending_cases(
        db_session,
        run_id=run_id,
        graph_version=graph_version,
        existing_target_keys=set(),
    )
    assert pending_cases
    for pending_case in pending_cases:
        assert pending_case.target_ref.get("chunk_id") == pending_case.chunk_id
