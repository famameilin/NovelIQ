"""时间轴与剧情推进场景夹具（2026-10-16 全库 3NF 新写面）

夹具按冻结 35 表的正式关系写入，读取一律走正式读面（plotline/timeline 读面）：
- 标注来源链：work_items(标注) → executions(真实调用) → chapter_annotations
- 章级声明：event_declarations + declaration_participants + source_evidence
- 图谱事实：graph_facts 的实体/关系/人物动态观测三种形状 + source_evidence
- 章张力：paragraph_features 的 tension_z 正式观测，展示值由读面 sigmoid 投影

新契约下人物动态观测只能挂在声明的参与者上，故每章为本章 characters 观测建立
一条承载声明；events 参数中的章内事件各自建立声明。场景不发布诊断：公布的运行
不允许存在未绑定的声明，时间轴/剧情推进读面本身也不依赖诊断报告。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from src.agents.annotation.chapter_consolidation import RULE_VERSION
from src.event_trees.read.organization import CONTRACT_VERSION
from src.fact_graph.identity import relation_id
from src.fact_graph.vocabulary import RELATION_DEFINITIONS
from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    DeclarationParticipant,
    EventDeclaration,
    EventForeshadowingAction,
    Execution,
    GraphEntity,
    GraphFact,
    GraphRelation,
    Paragraph,
    SourceEvidence,
    WorkItem,
)
from src.utils.identity import stable_uuid
from src.work.annotation_work import annotation_work_id
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    relation_fact,
)
from tests.support.run_records import set_run_status

__all__ = [
    "TimelineContractScenario",
    "create_timeline_contract_scenario",
    "create_chapter_annotation_source",
    "declaration_id_for_event",
    "entity_id_for",
    "graph_change_names",
    "graph_change_tuples",
    "index_by_node_id",
    "nodes_for_anchor_chapter",
    "persist_timeline_chapter",
    "save_event_declaration",
]


@dataclass(frozen=True)
class TimelineContractScenario:
    novel_id: str
    run_id: str
    task_id: str
    hero_name: str
    rival_name: str
    organization_name: str


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def entity_id_for(run_id: str, name: str, entity_type: str = "character") -> str:
    """实体身份的正式铸造口径（与图谱写面同一 run+规范名+大类规则）"""
    from src.fact_graph.graph import entity_key, entity_uuid

    return entity_uuid(run_id, entity_key(name, entity_type))


def _register_entity(session: Any, run_id: str, name: str, entity_type: str = "character") -> str:
    identifier = entity_id_for(run_id, name, entity_type)
    if session.get(GraphEntity, identifier) is None:
        session.add(GraphEntity(entity_id=identifier, run_id=run_id, canonical_name=name, entity_type=entity_type))
        session.flush()
    return identifier


def _chapter_paragraphs(session: Any, run_id: str, chapter_id: int) -> list[Paragraph]:
    return list(
        session.scalars(
            select(Paragraph)
            .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
            .order_by(Paragraph.paragraph_id)
        )
    )


def create_chapter_annotation_source(
    session: Any,
    *,
    run_id: str,
    chapter_id: int,
    role: str = "solo",
    summary: str | None = None,
    emotional_valence: int | None = None,
    narrative_function: str | None = None,
    pivot_moment: bool | None = None,
    cliffhanger: bool | None = None,
) -> tuple[str, str, str]:
    """建立一章的正式标注来源链（work → 真实调用 → 记录），返回三元身份"""
    chapter = session.scalar(select(Chapter).where(Chapter.run_id == run_id, Chapter.chapter_id == chapter_id))
    if chapter is None or chapter.text is None:
        raise ValueError(f"章节没有原文: run_id={run_id} chapter_id={chapter_id}")
    work_id = annotation_work_id(run_id, chapter_id, role)
    execution_id, record_id = str(uuid4()), str(uuid4())
    if session.get(WorkItem, work_id) is None:
        session.add(
            WorkItem(
                work_id=work_id,
                role=role,
                annotation_run_id=run_id,
                annotation_chapter_id=chapter_id,
            )
        )
        session.flush()
    session.add(
        Execution(
            execution_id=execution_id,
            work_id=work_id,
            attempt_number=1,
            started_at=_utcnow(),
            status="success",
        )
    )
    session.flush()
    session.add(
        ChapterAnnotation(
            record_id=record_id,
            execution_id=execution_id,
            contract_version=CONTRACT_VERSION,
            chapter_consolidation_version=RULE_VERSION,
            summary=summary if summary is not None else f"章节 {chapter_id} 摘要",
            emotional_valence=emotional_valence,
            narrative_function=narrative_function,
            pivot_moment=pivot_moment,
            cliffhanger=cliffhanger,
        )
    )
    session.flush()
    return record_id, work_id, execution_id


def declaration_id_for_event(run_id: str, work_id: str, node_key: str, *, tree_key: str | None = None) -> str:
    """事件声明的正式铸造口径（与标注写面的节点身份规则同一编码）"""
    return stable_uuid(run_id, work_id, "event_node", tree_key or node_key, node_key)


def save_event_declaration(
    session: Any,
    *,
    run_id: str,
    record_id: str,
    chapter_id: int,
    local_key: str,
    title: str,
    problem: str,
    summary: str,
    event_type: str = "行动",
    status: str = "ongoing",
    progress: str | None = None,
    is_foreshadowing_root: bool = False,
    payoff_likelihood: str | None = None,
    evidence_paragraph_id: int | None = None,
    participants: list[dict[str, Any]] | None = None,
    declaration_id: str | None = None,
) -> str:
    """按正式声明形状写入章级声明、声明参与者与原文证据，返回声明身份

    participants 每项给 name/entity_type/role 与可选的叙事功能、动作与情绪；
    三态至少一项非空时随参与者同事务写一行人物动态观测事实（人物动态观测的
    唯一来源是声明参与者，不另存第二份状态）。参与实体同时登记一章的实体引用
    事实，读取侧的实体投影据此解析名字与大类（与标注写面的实体登记同一口径）。
    """
    paragraphs = _chapter_paragraphs(session, run_id, chapter_id)
    if not paragraphs:
        raise ValueError(f"章节没有段落: run_id={run_id} chapter_id={chapter_id}")
    paragraph = next((row for row in paragraphs if row.paragraph_id == evidence_paragraph_id), paragraphs[0])
    execution_id = session.scalar(
        select(ChapterAnnotation.execution_id).where(ChapterAnnotation.record_id == record_id)
    )
    if execution_id is None:
        raise ValueError(f"声明必须引用本 run 已保存的标注记录: record_id={record_id}")
    identifier = declaration_id or stable_uuid(run_id, record_id, "declaration", local_key)
    session.add(
        EventDeclaration(
            declaration_id=identifier,
            record_id=record_id,
            local_key=local_key[:255],
            title=title,
            problem=problem,
            summary=summary,
            event_type=event_type,
            status=status,
            progress=progress,
            is_foreshadowing_root=is_foreshadowing_root,
            payoff_likelihood=payoff_likelihood,
        )
    )
    registered: set[str] = set()
    for ordinal, item in enumerate(participants or []):
        name = str(item["name"])
        entity_type = str(item.get("entity_type") or "character")
        entity_id = _register_entity(session, run_id, name, entity_type)
        participant_id = stable_uuid("declaration_participant", identifier, str(ordinal))
        narrative_role = item.get("narrative_role") or item.get("role_function")
        action = item.get("action")
        emotion = item.get("emotion")
        session.add(
            DeclarationParticipant(
                participant_id=participant_id,
                declaration_id=identifier,
                participant_ordinal=ordinal,
                entity_id=entity_id,
                role=str(item.get("role") or "主体"),
                narrative_role=None if narrative_role is None else str(narrative_role),
                action=None if action is None else str(action),
                emotion=None if emotion is None else str(emotion),
            )
        )
        if narrative_role or action or emotion:
            # 观测事实自身携带原文证据：与生产写入面同路径（人物维度取源不靠声明回退）
            fact = GraphFact(participant_id=participant_id)
            session.add(fact)
            session.flush()
            _write_fact_evidence(session, int(fact.graph_fact_id), paragraph)
        if entity_id not in registered:
            registered.add(entity_id)
            _write_entity_reference(
                session,
                execution_id=execution_id,
                paragraph=paragraph,
                entity_id=entity_id,
            )
    session.add(
        SourceEvidence(
            evidence_id=str(uuid4()),
            ordinal=0,
            paragraph_id=paragraph.paragraph_id,
            start_char=0,
            end_char=len(paragraph.text),
            declaration_id=identifier,
        )
    )
    if is_foreshadowing_root:
        # 与生产 freeze_actions 同形：伏笔树根在标注保存时即写 setup 动作（证据挂动作所有者列）
        operation = f"setup/{identifier}"
        action_id = stable_uuid(run_id, execution_id, operation)
        session.add(
            EventForeshadowingAction(
                action_id=action_id,
                producer_execution_id=execution_id,
                source_operation_local_key=operation[:128],
                operation_order=0,
                action_type="setup",
                source_declaration_id=identifier,
                target_declaration_id=identifier,
            )
        )
        session.add(
            SourceEvidence(
                evidence_id=str(uuid4()),
                ordinal=0,
                paragraph_id=paragraph.paragraph_id,
                start_char=0,
                end_char=len(paragraph.text),
                foreshadow_action_id=action_id,
            )
        )
    session.flush()
    return identifier


def _write_fact_evidence(session: Any, fact_id: int, paragraph: Paragraph) -> None:
    session.add(
        SourceEvidence(
            evidence_id=str(uuid4()),
            ordinal=0,
            paragraph_id=paragraph.paragraph_id,
            start_char=0,
            end_char=len(paragraph.text),
            graph_fact_id=fact_id,
        )
    )


def _next_operation_order(session: Any, execution_id: str) -> int:
    """同一真实执行内的下一个操作序号（事实序是执行内显式顺序，不猜时间）"""
    from sqlalchemy import func

    current = session.scalar(
        select(func.max(GraphFact.operation_order)).where(GraphFact.direct_producer_execution_id == execution_id)
    )
    return 0 if current is None else int(current) + 1


def _write_entity_reference(
    session: Any,
    *,
    execution_id: str,
    paragraph: Paragraph,
    entity_id: str,
) -> None:
    """章内实体引用事实：只登记身份与出现章，不提交描述/代表标记/标签（omit）"""
    fact = GraphFact(
        direct_producer_execution_id=execution_id,
        entity_id=entity_id,
        operation_order=_next_operation_order(session, execution_id),
    )
    session.add(fact)
    session.flush()
    _write_fact_evidence(session, int(fact.graph_fact_id), paragraph)


def _write_relation_change(
    session: Any,
    *,
    run_id: str,
    execution_id: str,
    paragraph: Paragraph,
    from_name: str,
    to_name: str,
    relation_type: str,
    change_kind: str = "assert",
    from_entity_type: str = "character",
    to_entity_type: str = "character",
    reason: str | None = None,
) -> str:
    """关系事实：端点、变化类型与理由按关系形状落 graph_facts，证据进 source_evidence"""
    definition = RELATION_DEFINITIONS.get(relation_type)
    if definition is None:
        raise ValueError(f"关系类型不在版本化合同内: {relation_type}")
    from_entity_id = _register_entity(session, run_id, from_name, from_entity_type)
    to_entity_id = _register_entity(session, run_id, to_name, to_entity_type)
    identifier = relation_id(run_id, from_entity_id, to_entity_id, relation_type, str(definition["directionality"]))
    if session.get(GraphRelation, identifier) is None:
        session.add(
            GraphRelation(
                relation_id=identifier,
                from_entity_id=from_entity_id,
                to_entity_id=to_entity_id,
                relation_type=relation_type,
            )
        )
        session.flush()
    fact = GraphFact(
        direct_producer_execution_id=execution_id,
        relation_id=identifier,
        operation_order=_next_operation_order(session, execution_id),
        relation_change_kind=change_kind,
        reason=reason,
    )
    session.add(fact)
    session.flush()
    _write_fact_evidence(session, int(fact.graph_fact_id), paragraph)
    return identifier


def persist_timeline_chapter(
    session: Any,
    *,
    run_id: str,
    chapter_id: int,
    emotional_valences: dict[int, int] | None = None,
    event_types: dict[int, str] | None = None,
    pivot_chapters: set[int] | None = None,
    cliffhanger_chapters: set[int] | None = None,
    characters: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
    continuity_resolutions: list[Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> str:
    """写入一章的正式标注来源、章级声明与图谱事实，返回标注记录 id

    characters 提供本章人物动态观测（挂在本章承载声明的参与者上）；relations
    提供本章确认的关系事实；continuity_resolutions 提供关系变化（break 落为
    关系撤回事实）；events 提供章内事件声明，tree_id/cause_role 等旧结构列在
    新契约里是读投影，不再作为写入输入。
    """
    record_id, work_id, execution_id = create_chapter_annotation_source(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        summary=f"章节 {chapter_id} 摘要",
        emotional_valence=(emotional_valences or {}).get(chapter_id),
        narrative_function=(event_types or {}).get(chapter_id),
        pivot_moment=chapter_id in (pivot_chapters or set()),
        cliffhanger=chapter_id in (cliffhanger_chapters or set()),
    )
    paragraphs = _chapter_paragraphs(session, run_id, chapter_id)
    if not paragraphs:
        raise ValueError(f"章节没有段落: run_id={run_id} chapter_id={chapter_id}")
    first_paragraph = paragraphs[0]
    observations = [
        {
            "name": fact["character"],
            "entity_type": "character",
            "role": "主体",
            "narrative_role": fact.get("role_function"),
            "action": fact.get("action"),
            "emotion": fact.get("emotion") or None,
        }
        for fact in characters or []
    ]
    if observations:
        save_event_declaration(
            session,
            run_id=run_id,
            record_id=record_id,
            chapter_id=chapter_id,
            local_key=f"chapter-observations/{chapter_id}",
            title=f"第{chapter_id}章人物动态",
            problem=f"第{chapter_id}章人物动态",
            summary=first_paragraph.text,
            participants=observations,
        )
    for index, spec in enumerate(events or []):
        node_key = str(spec.get("node_id") or f"event-{index + 1}")
        save_event_declaration(
            session,
            run_id=run_id,
            record_id=record_id,
            chapter_id=chapter_id,
            local_key=node_key,
            declaration_id=declaration_id_for_event(
                run_id, work_id, node_key, tree_key=str(spec.get("tree_id") or node_key)
            ),
            title=str(spec.get("title") or spec["description"]),
            problem=str(spec.get("problem") or "明确事件问题"),
            summary=str(spec.get("summary") or spec["description"]),
            event_type=str(spec.get("event_type") or "行动"),
            status=str(spec.get("status") or "ongoing"),
            progress=spec.get("progress"),
            is_foreshadowing_root=bool(spec.get("isforeshadowing")),
            payoff_likelihood=spec.get("payoff_likelihood"),
            evidence_paragraph_id=spec.get("evidence_paragraph_id") or first_paragraph.paragraph_id,
            participants=[
                {"name": name, "entity_type": "character", "role": "主体"} for name in spec.get("participants", [])
            ],
        )
    for fact in relations or []:
        _write_relation_change(
            session,
            run_id=run_id,
            execution_id=execution_id,
            paragraph=first_paragraph,
            from_name=str(fact["from_entity"]),
            to_name=str(fact["to_entity"]),
            relation_type=str(fact["relation_type"]),
            change_kind=str(fact.get("change_kind") or "assert"),
            from_entity_type=str(fact.get("from_entity_type") or "character"),
            to_entity_type=str(fact.get("to_entity_type") or "character"),
            reason=fact.get("reason"),
        )
    for resolution in continuity_resolutions or []:
        _write_relation_change(
            session,
            run_id=run_id,
            execution_id=execution_id,
            paragraph=first_paragraph,
            from_name=str(resolution["from_entity"]),
            to_name=str(resolution["to_entity"]),
            relation_type=str(resolution["relation_type"]),
            change_kind=str(resolution.get("change_kind") or "break"),
            reason=str(resolution.get("reason") or "关系变化"),
        )
    session.flush()
    return record_id


def _tension_z(display_value: float) -> float:
    """展示张力值的正式 z 观测：读面按 sigmoid 投影还原同值"""
    clipped = min(max(display_value, 1e-6), 1 - 1e-6)
    return math.log(clipped / (1 - clipped))


def create_timeline_contract_scenario(
    db_session: Any,
    *,
    events_by_chapter: dict[int, list[dict[str, Any]]] | None = None,
    final_relations: list[dict[str, Any]] | None = None,
) -> TimelineContractScenario:
    """通过章节标注正式来源与数据库图持久化构造时间轴共享场景"""
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
    set_run_status(db_session, run_id, "completed")

    # 章张力：旧曲线的逐段展示值按张力 z 正式观测写入，读面 sigmoid 还原同值
    from src.storage.repositories.paragraph import insert_paragraph_tension_observations

    display_tensions = [0.6, 0.7, 0.9, 0.5, 0.4]
    paragraphs_by_chapter: dict[int, list[Paragraph]] = {}
    for chapter_id in (1, 2, 3, 4, 5):
        paragraphs_by_chapter[chapter_id] = _chapter_paragraphs(db_session, run_id, chapter_id)
    insert_paragraph_tension_observations(
        db_session,
        run_id,
        [
            (paragraphs_by_chapter[chapter_id][0].paragraph_id, _tension_z(display_tensions[chapter_id - 1]))
            for chapter_id in (1, 2, 3, 4, 5)
        ],
    )

    persist_timeline_chapter(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[character_fact(chapter_id=1, name=hero_name, action="初入江湖")],
        events=(events_by_chapter or {}).get(1),
    )
    persist_timeline_chapter(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[character_fact(chapter_id=2, name=rival_name, action="现身", role_function="帮助者")],
        events=(events_by_chapter or {}).get(2),
    )
    persist_timeline_chapter(
        db_session,
        run_id=run_id,
        chapter_id=3,
        emotional_valences={3: -2},
        event_types={3: "冲突"},
        pivot_chapters={3},
        cliffhanger_chapters={3},
        characters=[
            character_fact(chapter_id=3, name=hero_name, action="结盟", emotion=-2),
            character_fact(chapter_id=3, name=rival_name, action="回应", role_function="帮助者"),
        ],
        relations=[
            relation_fact(
                chapter_id=3,
                from_name=hero_name,
                to_name=rival_name,
                relation_type="盟友",
            ),
            relation_fact(
                chapter_id=3,
                from_name=hero_name,
                to_name=organization_name,
                to_entity_type="organization",
                relation_type="隶属",
            ),
        ],
    )
    chapter_three_ally = db_session.scalar(
        select(GraphRelation).where(
            GraphRelation.from_entity_id == entity_id_for(run_id, hero_name),
            GraphRelation.to_entity_id == entity_id_for(run_id, rival_name),
            GraphRelation.relation_type == "盟友",
        )
    )
    assert chapter_three_ally is not None
    persist_timeline_chapter(
        db_session,
        run_id=run_id,
        chapter_id=4,
        emotional_valences={4: -1},
        event_types={4: "转折"},
        characters=[
            character_fact(
                chapter_id=4,
                name=rival_name,
                action="离开",
                role_function="帮助者",
                emotion=-1,
            )
        ],
    )
    persist_timeline_chapter(
        db_session,
        run_id=run_id,
        chapter_id=5,
        characters=[character_fact(chapter_id=5, name=hero_name, action="独行")],
        relations=final_relations,
        continuity_resolutions=[
            {
                "reason": "决裂",
                "from_entity": hero_name,
                "to_entity": rival_name,
                "relation_type": "盟友",
                "change_kind": "break",
            }
        ],
    )
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


def nodes_for_anchor_chapter(items: list[Any], anchor_chapter_id: int) -> list[Any]:
    matched: list[Any] = []
    for item in items:
        current_anchor = int(item["anchor_chapter_id"]) if isinstance(item, dict) else int(item.anchor_chapter_id)
        if current_anchor == anchor_chapter_id:
            matched.append(item)
    return matched


def graph_change_tuples(graph_changes: list[Any] | None) -> set[tuple[str, str, str]]:
    """提取关系变化的端点与变化类型"""
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


def graph_change_names(graph_changes: list[Any] | None) -> set[str]:
    """提取关系变化涉及的实体名称"""
    if not graph_changes:
        return set()
    names: set[str] = set()
    for item in graph_changes:
        if isinstance(item, dict):
            names.update({str(item["from_char"]), str(item["to_char"])})
        else:
            names.update({str(item.from_char), str(item.to_char)})
    return names
