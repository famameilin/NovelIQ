"""章内人物观测的正式写链夹具：观测三态随事件参与者落账

后人物动态观测的唯一事实源是「声明的参与者行」（declaration_participants
三态列 + 参与者观测事实行）。共享的 `persist_chapter_annotation` 不产出带三态的
事件参与者，`characters=[...]` 只会落成不可读的观测载荷；需要可读人物观测行
（别名归并、标签页、时间轴人物维度）的测试用本模块的 `persist_observed_characters`
——它驱动同一标注域保存链，把每个观测作为带三态的参与者进入声明。
"""

from __future__ import annotations

from typing import Any

from src.agents.annotation.output_models import BoundChapterAnnotation
from src.event_trees.models import BoundEvent, EventParticipantInput
from src.fact_graph.inputs import ChapterMetricsInput
from src.fact_graph.outputs import BoundCharacterObservation
from src.storage import new_id
from tests.support.chapter_annotation_helpers import commit_test_annotation
from tests.support.event_tree_fixtures import first_paragraph


def persist_observed_characters(
    session: Any,
    *,
    run_id: str,
    chapter_id: int,
    characters: list[dict[str, Any]],
    relations: list[dict[str, Any]] | None = None,
) -> str:
    """写入章内人物观测（`character_fact` 形状）并返回标注记录 id

    `characters` / `relations` 沿用 `character_fact` / `relation_fact` /
    `identity_relation_output` 的构造面；观测的三态（叙事角色/动作/情绪）
    作为声明的参与者三态进入正式事实，不另存旧观测载荷。
    """
    paragraph = first_paragraph(session, run_id, chapter_id=chapter_id)
    entity_types: dict[str, str] = {}
    for fact in [*characters, *(relations or [])]:
        for spec in fact.get("_entity_specs", []):
            entity_types.setdefault(str(spec["name"]), str(spec["entity_type"]))
    entity_ops = [
        {
            "name": name,
            "entity_type": entity_type,
            "tags": [],
            "description": None,
            "representative": None,
            "chapter_id": chapter_id,
        }
        for name, entity_type in entity_types.items()
    ]
    relation_assert_ops = [
        {
            "from_entity": str(fact["from_entity"]),
            "to_entity": str(fact["to_entity"]),
            "relation_type": str(fact["relation_type"]),
            "chapter_id": int(fact.get("chapter_id", chapter_id)),
        }
        for fact in relations or []
    ]
    observations = [
        BoundCharacterObservation(
            character=str(fact["character"]),
            role_function=str(fact["role_function"]),
            action=str(fact["action"]),
            emotion=int(fact["emotion"]),
        )
        for fact in characters
    ]
    events: list[BoundEvent] = []
    for observation in observations:
        node_id = new_id()
        events.append(
            BoundEvent(
                declaration_id=node_id,
                title=f"{observation.character}{observation.action}",
                problem="能否完成本项行动",
                summary=f"{observation.character}{observation.action}",
                event_type="行动",
                status="ongoing",
                progress=None,
                node_id=node_id,
                tree_id=f"tree-{node_id[:8]}",
                parent_node_id=None,
                cause_role="root",
                description=f"{observation.character}{observation.action}",
                evidence_paragraph_id=int(paragraph.paragraph_id),
                participants=[
                    EventParticipantInput(
                        entity=observation.character,
                        role=observation.role_function,
                        narrative_role=observation.role_function,
                        action=observation.action,
                        emotion=observation.emotion,
                    )
                ],
            )
        )
    annotation = BoundChapterAnnotation(
        metrics=ChapterMetricsInput(
            summary=f"章节 {chapter_id} 摘要",
            emotional_valence=0,
            narrative_function="铺垫",
            pivot_moment=False,
            cliffhanger=False,
        ),
        character_observations=observations,
        dialogues=[],
        events=events,
    )
    return commit_test_annotation(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
        entity_ops=entity_ops,
        relation_assert_ops=relation_assert_ops,
    )
