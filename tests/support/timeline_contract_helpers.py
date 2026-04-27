from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.chunking.chunker import Chunk
from src.models.local.schema import CharacterSnapshot, ChunkAnnotation
from src.storage.models import Novel
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    GraphRepository,
    RunRepository,
    StatsRepository,
)


@dataclass(frozen=True)
class TimelineContractScenario:
    novel_id: str
    run_id: str
    task_id: str
    hero_name: str
    rival_name: str
    organization_name: str


def create_timeline_contract_scenario(db_session: Any) -> TimelineContractScenario:
    """Create a minimal authority-backed timeline scenario shared by API/export tests."""

    novel_id = uuid.uuid4().hex[:8]
    hero_name = "顾承渊"
    rival_name = "苏映雪"
    organization_name = "天衡宗"

    db_session.add(
        Novel(
            novel_id=novel_id,
            filename="timeline-contract.txt",
            file_path="tests/timeline-contract.txt",
            title="Timeline Contract",
            file_size=128,
            upload_time=datetime.now(),
        )
    )
    db_session.commit()

    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(
        novel_id=novel_id,
        source_path="test",
        title="Timeline Contract",
    )
    run_repo.update_run_status(run_id, "completed")

    chunk_repo = ChunkRepository(db_session)
    stats_repo = StatsRepository(db_session)
    annotation_repo = AnnotationRepository(db_session)
    graph_repo = GraphRepository(db_session)

    chunks = [
        Chunk(index=0, text="顾承渊初入江湖。", start=0, end=8),
        Chunk(index=1, text="苏映雪现身与他同行。", start=9, end=20),
        Chunk(index=2, text="顾承渊与苏映雪结盟，同时受天衡宗招揽。", start=21, end=42),
        Chunk(index=3, text="苏映雪完成使命后离开。", start=43, end=56),
        Chunk(index=4, text="顾承渊最终与苏映雪决裂，独自前行。", start=57, end=74),
    ]
    chunk_repo.insert_chunks(run_id, chunks)

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

    annotations = [
        ChunkAnnotation(
            emotional_valence="neutral",
            event_type="铺垫",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[
                CharacterSnapshot(
                    name=hero_name,
                    role_function="主体",
                    action="初入江湖",
                    action_type="移动",
                    emotion_score="neutral",
                )
            ],
        ),
        ChunkAnnotation(
            emotional_valence="neutral",
            event_type="铺垫",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[
                CharacterSnapshot(
                    name=rival_name,
                    role_function="帮助者",
                    action="现身",
                    action_type="移动",
                    emotion_score="neutral",
                )
            ],
        ),
        ChunkAnnotation(
            emotional_valence="strong_negative",
            event_type="冲突",
            pivot_moment=True,
            cliffhanger=True,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[
                CharacterSnapshot(
                    name=hero_name,
                    role_function="主体",
                    action="结盟",
                    action_type="决策",
                    emotion_score="strong_negative",
                ),
                CharacterSnapshot(
                    name=rival_name,
                    role_function="帮助者",
                    action="回应",
                    action_type="决策",
                    emotion_score="neutral",
                ),
            ],
        ),
        ChunkAnnotation(
            emotional_valence="mild_negative",
            event_type="转折",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[
                CharacterSnapshot(
                    name=rival_name,
                    role_function="帮助者",
                    action="离开",
                    action_type="移动",
                    emotion_score="mild_negative",
                )
            ],
        ),
        ChunkAnnotation(
            emotional_valence="neutral",
            event_type="铺垫",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[
                CharacterSnapshot(
                    name=hero_name,
                    role_function="主体",
                    action="独行",
                    action_type="移动",
                    emotion_score="neutral",
                )
            ],
        ),
    ]
    for chunk_id, annotation in enumerate(annotations):
        annotation_repo.insert_chunk_annotation(run_id, chunk_id, annotation)

    hero = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name=hero_name,
        entity_type="character",
        first_seen_chunk=0,
        last_seen_chunk=4,
        primary_role_function="protagonist",
    )
    rival = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name=rival_name,
        entity_type="character",
        first_seen_chunk=1,
        last_seen_chunk=3,
        primary_role_function="ally",
    )
    sect = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name=organization_name,
        entity_type="organization",
        first_seen_chunk=0,
        last_seen_chunk=4,
    )

    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=2,
        evidence="二人正式结盟",
        confidence=0.91,
        source_relation_row_id=21001,
        directionality="directed",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=sect.entity_id,
        relation_type="归属",
        change_type="新建",
        chunk_id=2,
        evidence="顾承渊受天衡宗招揽",
        confidence=0.97,
        source_relation_row_id=21002,
        directionality="directed",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="盟友",
        change_type="断裂",
        chunk_id=4,
        evidence="两人最终决裂",
        confidence=0.63,
        source_relation_row_id=21003,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, rival.entity_id)
    graph_repo.refresh_current_relation(run_id, hero.entity_id, sect.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, rival.entity_id, sect.entity_id])
    db_session.commit()

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
