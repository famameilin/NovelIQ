from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.storage.repositories import RunRepository, StatsRepository
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


def create_timeline_contract_scenario(db_session: Any) -> TimelineContractScenario:
    """2026-08-05 用于通过章节标注与生产图投影构造时间轴共享场景"""
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

    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[character_fact(chunk_id=0, name=hero_name, action="初入江湖")],
    )
    persist_chapter_annotation(
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
    persist_chapter_annotation(
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
                evidence_reason="二人正式结盟",
                chapter_id=3,
            ),
            relation_fact(
                chunk_id=2,
                from_name=hero_name,
                to_name=organization_name,
                to_entity_type="organization",
                relation_type="归属",
                evidence_reason="顾承渊受天衡宗招揽",
                chapter_id=3,
            ),
        ],
    )
    persist_chapter_annotation(
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
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=5,
        characters=[character_fact(chunk_id=4, name=hero_name, action="独行", chapter_id=5)],
        relations=[
            relation_fact(
                chunk_id=4,
                from_name=hero_name,
                to_name=rival_name,
                relation_type="盟友",
                evidence_reason="两人最终决裂",
                change_kind="break",
                confidence="medium",
                chapter_id=5,
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


def relation_event_tuples(relation_events: list[Any] | None) -> set[tuple[str, str, str]]:
    if not relation_events:
        return set()
    tuples: set[tuple[str, str, str]] = set()
    for item in relation_events:
        if isinstance(item, dict):
            tuples.add((str(item["from_char"]), str(item["to_char"]), str(item["change_type"])))
        else:
            tuples.add((str(item.from_char), str(item.to_char), str(item.change_type)))
    return tuples


def relation_event_names(relation_events: list[Any] | None) -> set[str]:
    if not relation_events:
        return set()
    names: set[str] = set()
    for item in relation_events:
        if isinstance(item, dict):
            names.update({str(item["from_char"]), str(item["to_char"])})
        else:
            names.update({str(item.from_char), str(item.to_char)})
    return names
