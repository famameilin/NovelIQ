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


def _army_relations(chunk_id: int, names: list[str]) -> list[dict]:
    """2026-09-13 用于构造"每个角色都隶属贺家军"的组织枢纽边（隶属：character → organization）"""
    return [
        relation_fact(
            chunk_id=chunk_id,
            from_name=name,
            to_name="贺家军",
            relation_type="隶属",
            to_entity_type="organization",
        )
        for name in names
    ]


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

    from src.storage.repositories.graph import GraphRepository

    chapter_boundary = GraphRepository(db_session).resolve_chapter_boundary(run_id)
    assert chapter_boundary is not None
    pairs = {
        (item.name_a, item.name_b) for item in detect_alias_suspicions(db_session, chapter_boundary=chapter_boundary)
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

    from src.storage.repositories.graph import GraphRepository

    chapter_boundary = GraphRepository(db_session).resolve_chapter_boundary(run_id)
    assert chapter_boundary is not None
    pairs = {
        (item.name_a, item.name_b) for item in detect_alias_suspicions(db_session, chapter_boundary=chapter_boundary)
    }
    assert pairs == set()


def test_detect_alias_suspicions_ignores_hub_neighbors(db_session) -> None:
    """2026-09-13 全角色都挂在枢纽节点上的图不再产出别名对（run c80105cc 假阳性根因）

    实测形状：贺老爷/侯飞白/林立果/褚大山 两两共享的邻居恰好是「贺伯安（主角）+
    贺家军（组织）」。旧规则（邻居含组织、按个数算重叠）在这个形状下把 6 对全判成
    疑似同一人物、全部为假，且到 run 死时仍 active，每章被 search_graph 回执反复
    点名。新规则下它们既不满足"共享**角色**邻居 ≥2"（只剩主角一个角色邻居），
    也不满足按度数加权的重合度阈值。
    """
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["贺府众人随军"],
        title="图验证器枢纽邻居",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="贺伯安", action="随军"),
            character_fact(chunk_id=1, name="贺老爷", action="随军"),
            character_fact(chunk_id=1, name="侯飞白", action="随军"),
            character_fact(chunk_id=1, name="林立果", action="随军"),
            character_fact(chunk_id=1, name="褚大山", action="随军"),
        ],
        relations=[
            # 每个角色都连主角（角色枢纽）与贺家军（组织枢纽）：旧规则下两两重合
            relation_fact(chunk_id=1, from_name="贺老爷", to_name="贺伯安", relation_type="家族"),
            relation_fact(chunk_id=1, from_name="侯飞白", to_name="贺伯安", relation_type="友情"),
            relation_fact(chunk_id=1, from_name="林立果", to_name="贺伯安", relation_type="友情"),
            relation_fact(chunk_id=1, from_name="褚大山", to_name="贺伯安", relation_type="友情"),
            *_army_relations(1, ["贺伯安", "贺老爷", "侯飞白", "林立果", "褚大山"]),
        ],
    )
    db_session.commit()

    from src.storage.repositories.graph import GraphRepository

    chapter_boundary = GraphRepository(db_session).resolve_chapter_boundary(run_id)
    assert chapter_boundary is not None
    assert detect_alias_suspicions(db_session, chapter_boundary=chapter_boundary) == []


def test_detect_alias_suspicions_excludes_pairs_with_direct_relation(db_session) -> None:
    """2026-09-13 两端已有直接关系的对不可能是同一个人：只排除该对，同图其他对照常检出

    反空转：同一张图里另放一对"共享两个独有邻居"的角色（真别名形状），
    证明排除是有选择性的，不是整图静默。
    """
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["赵兰英与柳婉儿同席", "侯飞白与林立果偷鸡"],
        chapter_ids=[1, 2],
        title="图验证器直接关系排除",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=1, name="赵兰英", action="同席"),
            character_fact(chunk_id=1, name="柳婉儿", action="同席"),
            character_fact(chunk_id=1, name="周凤兰", action="同席"),
            character_fact(chunk_id=1, name="贺伯安", action="同席"),
        ],
        relations=[
            relation_fact(chunk_id=1, from_name="赵兰英", to_name="周凤兰", relation_type="家族"),
            relation_fact(chunk_id=1, from_name="柳婉儿", to_name="周凤兰", relation_type="家族"),
            relation_fact(chunk_id=1, from_name="赵兰英", to_name="贺伯安", relation_type="家族"),
            relation_fact(chunk_id=1, from_name="柳婉儿", to_name="贺伯安", relation_type="家族"),
            # 两端已有直接边：图上已按两个人处理，不再进疑似
            relation_fact(chunk_id=1, from_name="赵兰英", to_name="柳婉儿", relation_type="家族"),
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[
            character_fact(chunk_id=2, name="侯飞白", action="偷鸡"),
            character_fact(chunk_id=2, name="林立果", action="偷鸡"),
            character_fact(chunk_id=2, name="猴子", action="偷鸡"),
            character_fact(chunk_id=2, name="算盘", action="偷鸡"),
        ],
        relations=[
            relation_fact(chunk_id=2, from_name="侯飞白", to_name="猴子", relation_type="友情"),
            relation_fact(chunk_id=2, from_name="林立果", to_name="猴子", relation_type="友情"),
            relation_fact(chunk_id=2, from_name="侯飞白", to_name="算盘", relation_type="友情"),
            relation_fact(chunk_id=2, from_name="林立果", to_name="算盘", relation_type="友情"),
        ],
    )
    db_session.commit()

    from src.storage.repositories.graph import GraphRepository

    chapter_boundary = GraphRepository(db_session).resolve_chapter_boundary(run_id)
    assert chapter_boundary is not None
    pairs = {
        frozenset((item.name_a, item.name_b))
        for item in detect_alias_suspicions(db_session, chapter_boundary=chapter_boundary)
    }
    assert frozenset(("赵兰英", "柳婉儿")) not in pairs
    assert frozenset(("侯飞白", "林立果")) in pairs


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

    from src.storage.repositories.graph import GraphRepository

    chapter_boundary = GraphRepository(db_session).resolve_chapter_boundary(run_id)
    assert chapter_boundary is not None
    pending_cases = build_alias_pending_cases(
        db_session,
        run_id=run_id,
        chapter_boundary=chapter_boundary,
        existing_target_keys=set(),
    )
    assert pending_cases
    for pending_case in pending_cases:
        assert pending_case.target_ref.get("chunk_id") == pending_case.chunk_id
