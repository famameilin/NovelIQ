from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.agents.annotation.schema import ResolvedCase
from src.storage.repositories import GraphRepository, RunRepository, StatsRepository
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)
from tests.support.graph_snapshot_helpers import insert_focus_contract_cloud_analysis


@dataclass(frozen=True)
class TimelineContractScenario:
    novel_id: str
    run_id: str
    task_id: str
    hero_name: str
    rival_name: str
    organization_name: str


# 2026-08-07 用于按章节图最终持久化合同提交时间轴测试标注
def persist_timeline_chapter(
    session: Any,
    *,
    run_id: str,
    chapter_id: int,
    emotional_valences: dict[int, str] | None = None,
    event_types: dict[int, str] | None = None,
    pivot_chunks: set[int] | None = None,
    cliffhanger_chunks: set[int] | None = None,
    characters: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
    resolved_cases: list[Any] | None = None,
) -> str:
    """2026-08-07 用于写入当前章节标注与唯一章节图版本"""
    return persist_chapter_annotation(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        emotional_valences=emotional_valences,
        event_types=event_types,
        pivot_chunks=pivot_chunks,
        cliffhanger_chunks=cliffhanger_chunks,
        characters=characters,
        relations=relations,
        resolved_cases=resolved_cases,
    )


def create_timeline_contract_scenario(db_session: Any) -> TimelineContractScenario:
    """2026-08-06 用于通过章节标注与数据库图持久化构造时间轴共享场景"""
    hero_name = "顾承渊"
    rival_name = "苏映雪"
    organization_name = "天衡宗"
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[
            "顾承渊初入江湖。",
            "苏映雪现身与他同行。",
            "顾承渊与苏映雪结盟，同时受天衡宗招揽。",
            "苏映雪完成使命后离开。",
            "顾承渊最终与苏映雪决裂，独自前行。",
        ],
        chapter_ids=[1, 2, 3, 4, 5],
        title="Timeline Contract",
    )
    run_repo = RunRepository(db_session)
    run_repo.update_run_status(run_id, "completed")

    stats_repo = StatsRepository(db_session)
    for chunk_id, summary in enumerate(
        [
            "顾承渊登场",
            "苏映雪现身",
            "顾承渊与苏映雪结盟",
            "苏映雪离场",
            "顾承渊独自前行",
        ]
    ):
        stats_repo.insert_chunk_summary(run_id, chunk_id, summary)

    stats_repo.insert_chunk_curve(
        run_id,
        [
            (0, 0.10, 0.02, 0.08, 0.08, 0.20, 0.15),
            (1, 0.08, 0.05, 0.03, 0.03, 0.35, 0.30),
            (2, 0.03, 0.22, -0.19, -0.17, 0.95, 0.95),
            (3, 0.04, 0.12, -0.08, -0.07, 0.55, 0.45),
            (4, 0.02, 0.05, -0.03, -0.03, 0.10, 0.10),
        ],
    )

    # 2026-08-14 段落化：导出核心结果走段落曲线，场景同步插入段落曲线行
    # （每段一行，与 5 个 chunk 一一对应）
    from src.storage.repositories.paragraph_repository import (
        ParagraphCurveRow,
        ParagraphRepository,
    )

    ParagraphRepository(db_session).insert_paragraph_curves(
        run_id,
        [
            ParagraphCurveRow(
                paragraph_id=0,
                pos_density=0.10,
                neg_density=0.02,
                net_density=0.08,
                smoothed_net_density=0.08,
                surface_tension=0.6,
                smoothed_surface_tension=0.6,
            ),
            ParagraphCurveRow(
                paragraph_id=1,
                pos_density=0.08,
                neg_density=0.05,
                net_density=0.03,
                smoothed_net_density=0.03,
                surface_tension=0.7,
                smoothed_surface_tension=0.7,
            ),
            ParagraphCurveRow(
                paragraph_id=2,
                pos_density=0.03,
                neg_density=0.22,
                net_density=-0.19,
                smoothed_net_density=-0.17,
                surface_tension=0.9,
                smoothed_surface_tension=0.9,
            ),
            ParagraphCurveRow(
                paragraph_id=3,
                pos_density=0.04,
                neg_density=0.12,
                net_density=-0.08,
                smoothed_net_density=-0.07,
                surface_tension=0.5,
                smoothed_surface_tension=0.5,
            ),
            ParagraphCurveRow(
                paragraph_id=4,
                pos_density=0.02,
                neg_density=0.05,
                net_density=-0.03,
                smoothed_net_density=-0.03,
                surface_tension=0.4,
                smoothed_surface_tension=0.4,
            ),
        ],
    )

    persist_timeline_chapter(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[character_fact(chunk_id=0, name=hero_name, action="初入江湖")],
    )
    persist_timeline_chapter(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[
            character_fact(
                chunk_id=1,
                name=rival_name,
                action="现身",
                role_function="帮助者",
                chapter_id=2,
            )
        ],
    )
    persist_timeline_chapter(
        db_session,
        run_id=run_id,
        chapter_id=3,
        emotional_valences={2: "strong_negative"},
        event_types={2: "冲突"},
        pivot_chunks={2},
        cliffhanger_chunks={2},
        characters=[
            character_fact(
                chunk_id=2,
                name=hero_name,
                action="结盟",
                emotion="strong_negative",
                chapter_id=3,
            ),
            character_fact(
                chunk_id=2,
                name=rival_name,
                action="回应",
                role_function="帮助者",
                chapter_id=3,
            ),
        ],
        relations=[
            relation_fact(
                chunk_id=2,
                from_name=hero_name,
                to_name=rival_name,
                relation_type="盟友",
                chapter_id=3,
            ),
            relation_fact(
                chunk_id=2,
                from_name=hero_name,
                to_name=organization_name,
                to_entity_type="organization",
                relation_type="隶属",
                chapter_id=3,
            ),
        ],
    )
    chapter_three_snapshot = GraphRepository(db_session).fetch_snapshot(run_id, chapter_id=3)
    assert chapter_three_snapshot is not None
    assert any(
        relation.from_name == hero_name
        and relation.to_name == rival_name
        and relation.relation_type == "盟友"
        for relation in chapter_three_snapshot.relations
    )
    persist_timeline_chapter(
        db_session,
        run_id=run_id,
        chapter_id=4,
        emotional_valences={3: "mild_negative"},
        event_types={3: "转折"},
        characters=[
            character_fact(
                chunk_id=3,
                name=rival_name,
                action="离开",
                role_function="帮助者",
                emotion="mild_negative",
                chapter_id=4,
            )
        ],
    )
    persist_timeline_chapter(
        db_session,
        run_id=run_id,
        chapter_id=5,
        characters=[character_fact(chunk_id=4, name=hero_name, action="独行", chapter_id=5)],
        resolved_cases=[
            ResolvedCase(
                case_id="case-break",
                action="fact",
                type="relation_change",
                reason="决裂",
                target_key="target-break",
                target_ref={"kind": "relation_change", "chunk_id": 4},
                from_entity=hero_name,
                to_entity=rival_name,
                relation_type="盟友",
                change_kind="break",
            )
        ],
    )

    insert_focus_contract_cloud_analysis(
        db_session,
        novel_id=novel_id,
        run_id=run_id,
        focus_characters=[hero_name],
        main_characters=[hero_name, rival_name],
        core_cast=[hero_name, rival_name, organization_name],
        topic_labels=["结盟与决裂"],
    )

    return TimelineContractScenario(
        novel_id=novel_id,
        run_id=run_id,
        task_id=run_id[:8],
        hero_name=hero_name,
        rival_name=rival_name,
        organization_name=organization_name,
    )


def index_by_node_id(items: list[Any]) -> dict[str, Any]:
    return {str(item["node_id"]) if isinstance(item, dict) else str(item.node_id): item for item in items}


def nodes_for_anchor_chunk(items: list[Any], anchor_chunk_id: int) -> list[Any]:
    matched: list[Any] = []
    for item in items:
        current_anchor = int(item["anchor_chunk_id"]) if isinstance(item, dict) else int(item.anchor_chunk_id)
        if current_anchor == anchor_chunk_id:
            matched.append(item)
    return matched


# 2026-08-07 用于提取关系章节图变化的端点与变化类型
def graph_change_tuples(graph_changes: list[Any] | None) -> set[tuple[str, str, str]]:
    """2026-08-07 用于提取关系章节图变化的端点与变化类型"""
    if not graph_changes:
        return set()
    tuples: set[tuple[str, str, str]] = set()
    for item in graph_changes:
        if isinstance(item, dict):
            tuples.add(
                (
                    str(item["from_char"]),
                    str(item["to_char"]),
                    str(item["relation_change_kind"]),
                )
            )
        else:
            tuples.add((str(item.from_char), str(item.to_char), str(item.relation_change_kind)))
    return tuples


# 2026-08-07 用于提取关系章节图变化涉及的实体名称
def graph_change_names(graph_changes: list[Any] | None) -> set[str]:
    """2026-08-07 用于提取关系章节图变化涉及的实体名称"""
    if not graph_changes:
        return set()
    names: set[str] = set()
    for item in graph_changes:
        if isinstance(item, dict):
            names.update({str(item["from_char"]), str(item["to_char"])})
        else:
            names.update({str(item.from_char), str(item.to_char)})
    return names
