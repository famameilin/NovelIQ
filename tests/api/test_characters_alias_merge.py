"""角色页消歧合并测试"""

from __future__ import annotations

from src.api.services.results_queries.characters import _fetch_characters
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    identity_relation_output,
    persist_chapter_annotation,
    relation_fact,
)


def test_fetch_characters_merges_same_character_aliases(db_session) -> None:
    """2026-08-09 用于验证角色榜把同一人物别名归一到代表名"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["伯安与猴子同游"],
        title="角色榜消歧合并",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chapter_id=1, name="伯安", action="同游"),
            character_fact(chapter_id=1, name="贺重明", action="同游"),
            character_fact(chapter_id=1, name="猴子", action="同游"),
            character_fact(chapter_id=1, name="侯飞白", action="同游"),
        ],
        relations=[
            relation_fact(
                chapter_id=1,
                from_name="伯安",
                to_name="猴子",
                relation_type="友情",
            ),
            identity_relation_output(subject_name="伯安", object_name="贺重明", effective_chapter_id=1),
            identity_relation_output(subject_name="猴子", object_name="侯飞白", effective_chapter_id=1),
        ],
    )
    db_session.commit()

    from src.storage.repositories import AnnotationRepository

    result = _fetch_characters(
        run_id=run_id,
        annotation_repo=AnnotationRepository(db_session),
        limit=None,
    )

    # 代表名由 uuid5(entity_id) 字典序选举决定，随 run 随机；
    # 只断言每对别名收敛到唯一代表且出现次数合并
    assert len(result) == 2
    assert all(char.appearance_count == 2 for char in result)
    assert {char.name for char in result} <= {"伯安", "贺重明", "猴子", "侯飞白"}
    assert len({char.name for char in result} & {"伯安", "贺重明"}) == 1
    assert len({char.name for char in result} & {"猴子", "侯飞白"}) == 1


def test_fetch_characters_prefers_diagnosis_name_as_representative(db_session) -> None:
    """2026-08-09 用于验证角色榜代表名优先采用诊断命中名字"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["伯安与贺重明同游"],
        title="角色榜诊断命名对齐",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chapter_id=1, name="伯安", action="同游"),
            character_fact(chapter_id=1, name="贺重明", action="同游"),
        ],
        relations=[
            identity_relation_output(subject_name="伯安", object_name="贺重明", effective_chapter_id=1),
        ],
    )
    db_session.commit()

    from src.storage.repositories import AnnotationRepository

    result = _fetch_characters(
        run_id=run_id,
        annotation_repo=AnnotationRepository(db_session),
        limit=None,
        main_characters=["贺重明"],
    )
    assert {char.name for char in result} == {"贺重明"}
    assert result[0].appearance_count == 2


def test_fetch_characters_normalizes_diagnosis_keys_for_focus_scores(db_session) -> None:
    """2026-08-09 用于验证诊断别名名归一到代表名后聚焦评分正确匹配"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["伯安与贺重明同游"],
        title="角色榜聚焦评分对齐",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chapter_id=1, name="伯安", action="同游"),
            character_fact(chapter_id=1, name="贺重明", action="同游"),
        ],
        relations=[
            identity_relation_output(subject_name="伯安", object_name="贺重明", effective_chapter_id=1),
        ],
    )
    db_session.commit()

    from src.storage.repositories import AnnotationRepository

    result = _fetch_characters(
        run_id=run_id,
        annotation_repo=AnnotationRepository(db_session),
        limit=None,
        arc_scores={"贺重明": 9.0},
        main_characters=["贺重明"],
        focus_characters=["贺重明"],
    )
    protagonist = next(char for char in result if char.name == "贺重明")
    assert protagonist.is_focus_character is True
    assert protagonist.narrative_focus_score == 0.975
