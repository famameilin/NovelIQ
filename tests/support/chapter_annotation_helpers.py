"""章节正式标注与数据库图测试夹具（agent-semantic-v2 合同）"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.utils.identity import stable_digest
from src.fact_graph.schema import EntityInput, EntityType, RelationInput
from src.event_trees.models import BoundChapterAnnotation, BoundCharacterObservation, BoundDialogue, BoundEvent, ChapterMetricsInput, EventParticipantInput
from src.storage.db import get_session_factory
from src.storage.models import Chapter, Novel, Paragraph
from src.storage.repositories import ChapterRepository, RunRepository
from src.storage.text_units import Chunk as ChunkerChunk
from src.workflows.paragraphs import split_chunk_paragraphs


def create_run_with_chunks(
    session: Any,
    *,
    texts: list[str],
    chapter_ids: list[int] | None = None,
    title: str = "章节事实测试",
) -> tuple[str, str]:
    """2026-08-05 用于创建带真实章节身份的小说运行与原文章节"""
    novel_id = uuid.uuid4().hex[:8]
    run_id = str(uuid.uuid4())
    session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"tests/{novel_id}.txt",
            file_size=sum(len(text) for text in texts),
            title=title,
        )
    )
    session.commit()
    RunRepository(session).create_run(
        novel_id=novel_id,
        source_path="test",
        title=title,
        run_id=run_id,
    )
    resolved_chapter_ids = chapter_ids or [1] * len(texts)
    if len(resolved_chapter_ids) != len(texts):
        raise ValueError("chapter_ids 必须与 texts 等长")
    offset = 0
    chunks: list[ChunkerChunk] = []
    for chunk_index, (chapter_id, text_value) in enumerate(zip(resolved_chapter_ids, texts, strict=True)):
        chunks.append(
            ChunkerChunk(
                index=chunk_index,
                chapter_id=chapter_id,
                start=offset,
                end=offset + len(text_value),
                text=text_value,
            )
        )
        offset += len(text_value)
    # M9a-2：chunks 表合并进 chapters——正文切片经 ChapterRepository 落库
    # （缺失章节行以默认结构补建，见 insert_chapter_texts）
    ChapterRepository(session).insert_chapter_texts(run_id, chunks)
    session.commit()
    # 2026-08-14 二期：annotate 阶段要求段落事实源存在（章节段落边界查询），
    # helper 同步插入段落行（一次传入全部章节，paragraph_id 全局连续），
    # token_count 用简单切分填充
    from src.storage.repositories import ParagraphRepository

    spans = [replace(span, token_count=max(1, len(span.text) // 2)) for span in split_chunk_paragraphs(chunks)]
    if spans:
        ParagraphRepository(session).insert_paragraphs(run_id, spans)
        session.commit()
    return novel_id, run_id


def _entity_spec(
    name: str,
    entity_type: EntityType,
    tags: list[str] | None = None,
) -> dict[str, str | list[str]]:
    """2026-08-08 用于声明事实隐含的实体名称、大类与可选标签"""
    spec: dict[str, str | list[str]] = {"name": name, "entity_type": entity_type}
    if tags:
        spec["tags"] = tags
    return spec


def character_fact(
    *,
    chapter_id: int,
    name: str,
    action: str,
    role_function: str = "主体",
    emotion: int = 0,
) -> dict[str, Any]:
    """2026-08-11 用于构造章内人物观察输入测试值"""
    return {
        "chapter_id": chapter_id,
        "character": name,
        "role_function": role_function,
        "action": action,
        "emotion": emotion,
        "_entity_specs": [_entity_spec(name, "character")],
    }


def relation_fact(
    *,
    chapter_id: int,
    from_name: str,
    to_name: str,
    relation_type: str,
    from_entity_type: EntityType = "character",
    to_entity_type: EntityType = "character",
) -> dict[str, Any]:
    """2026-08-12 用于构造章内三字段关系边输入测试值（本章确认存在的边）"""
    return {
        "chapter_id": chapter_id,
        "from_entity": from_name,
        "to_entity": to_name,
        "relation_type": relation_type,
        "_entity_specs": [
            _entity_spec(from_name, from_entity_type),
            _entity_spec(to_name, to_entity_type),
        ],
    }


def dialogue_fact(
    *,
    chapter_id: int,
    content: str,
    speaker: str | None,
    tone: str | None = None,
    verdict: str = "dialogue",
) -> dict[str, Any]:
    """2026-08-11 用于构造按系统候选对齐的对话输入测试值"""
    return {
        "candidate_content": content,
        "verdict": verdict,
        "speaker": speaker,
        "tone": tone,
        "chapter_id": chapter_id,
        "_entity_specs": [_entity_spec(speaker, "character")] if speaker else [],
    }


def identity_relation_output(
    *,
    subject_name: str,
    object_name: str,
    effective_chapter_id: int = 0,
) -> dict[str, Any]:
    """2026-08-07 用于构造同一人物关系的测试标注项"""
    return relation_fact(
        chapter_id=effective_chapter_id,
        from_name=subject_name,
        to_name=object_name,
        relation_type="同一人物",
    )


def _register_entity(
    directory: dict[str, list[EntityInput]],
    *,
    name: str,
    entity_type: EntityType,
    tags: list[str] | None = None,
) -> None:
    """2026-08-11 用于把事实隐含实体注册到当前章实体目录"""
    for existing in directory["entities"]:
        if existing.name == name:
            return
    directory["entities"].append(
        EntityInput(
            name=name,
            entity_type=entity_type,
            tags=tags or [],
        )
    )


def make_bound_event(
    *,
    description: str,
    participants: list[dict[str, str]] | None = None,
    tree_id: str | None = None,
    node_id: str | None = None,
    parent_node_id: str | None = None,
    cause_role: str = "root",
    evidence_paragraph_id: int | None = None,
) -> BoundEvent:
    """构造带本章段落证据的正式事件"""
    return BoundEvent(
        node_id=node_id or str(uuid4()),
        tree_id=tree_id or f"tree-{uuid4()}",
        parent_node_id=parent_node_id,
        cause_role=cause_role,
        description=description,
        evidence_paragraph_id=evidence_paragraph_id,
        participants=[EventParticipantInput(entity=p["entity"], role=p["role"]) for p in (participants or [])],
    )


def persist_chapter_annotation(
    session: Any,
    *,
    run_id: str,
    chapter_id: int,
    emotional_valences: dict[int, int] | None = None,
    event_types: dict[int, str] | None = None,
    pivot_chapters: set[int] | None = None,
    cliffhanger_chapters: set[int] | None = None,
    characters: list[dict[str, Any]] | None = None,
    dialogues: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
    entity_attributes: dict[tuple[int, str], dict[str, Any]] | None = None,
    continuity_resolutions: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    foreshadowings: list[dict[str, Any]] | None = None,
) -> str:
    """通过 Agent 与三个域保存一份真实 solo work，供消费端回归读取"""
    chapter_row = session.execute(
        select(Chapter).where(Chapter.run_id == run_id, Chapter.chapter_id == chapter_id)
    ).scalar_one_or_none()
    if chapter_row is None or chapter_row.text is None:
        raise ValueError(f"章节没有原文: run_id={run_id} chapter_id={chapter_id}")
    chapter_text_by_id = {chapter_id: str(chapter_row.text)}
    paragraph_id = (
        session.execute(
            select(Paragraph.paragraph_id)
            .where(
                Paragraph.run_id == run_id,
                Paragraph.chapter_id == chapter_id,
            )
            .order_by(Paragraph.paragraph_id)
        )
        .scalars()
        .first()
    )
    candidate_by_content: dict[tuple[int, str], tuple[int, Any]] = {}
    for chapter_id, chapter_text in chapter_text_by_id.items():
        for candidate_index, candidate in enumerate(extract_dialogue_candidates(chapter_id, chapter_text), start=1):
            candidate_by_content[(chapter_id, candidate.content)] = candidate_index, candidate

    keys = list(chapter_text_by_id)
    directories = {key: {"entities": []} for key in keys}
    observations_by_chapter: dict[int, list[BoundCharacterObservation]] = {key: [] for key in keys}
    dialogues_by_chapter: dict[int, list[BoundDialogue]] = {key: [] for key in keys}
    relations_by_chapter: dict[int, list[RelationInput]] = {key: [] for key in keys}

    for fact in characters or []:
        chapter_id = int(fact["chapter_id"])
        if chapter_id not in chapter_text_by_id:
            raise ValueError(f"测试事实引用了非本章章节: {chapter_id}")
        for spec in fact.get("_entity_specs", []):
            _register_entity(
                directories[chapter_id],
                name=spec["name"],
                entity_type=spec["entity_type"],
                tags=spec.get("tags"),
            )
        observations_by_chapter[chapter_id].append(
            BoundCharacterObservation(
                character=fact["character"],
                role_function=fact["role_function"],
                action=fact["action"],
                emotion=fact["emotion"],
            )
        )

    for fact in relations or []:
        chapter_id = int(fact.get("chapter_id", -1))
        if chapter_id not in chapter_text_by_id:
            raise ValueError(f"测试事实引用了非本章章节: {chapter_id}")
        for spec in fact.get("_entity_specs", []):
            _register_entity(
                directories[chapter_id],
                name=spec["name"],
                entity_type=spec["entity_type"],
                tags=spec.get("tags"),
            )
        relations_by_chapter[chapter_id].append(
            RelationInput(
                from_entity=fact["from_entity"],
                to_entity=fact["to_entity"],
                relation_type=fact["relation_type"],
            )
        )

    for fact in dialogues or []:
        chapter_id = int(fact["chapter_id"])
        content = fact["candidate_content"]
        indexed_candidate = candidate_by_content.get((chapter_id, content))
        if indexed_candidate is None:
            raise ValueError(f"测试对话未出现在系统候选原文中: chapter_id={chapter_id} content={content!r}")
        candidate_index, candidate = indexed_candidate
        speaker = fact["speaker"]
        if speaker is not None:
            _register_entity(
                directories[chapter_id],
                name=speaker,
                entity_type="character",
            )
        dialogues_by_chapter[chapter_id].append(
            BoundDialogue(
                candidate_index=candidate_index,
                candidate_key=candidate.candidate_key,
                content=candidate.content,
                start=candidate.start,
                end=candidate.end,
                speaker=speaker,
                tone=fact["tone"],
                is_inner_monologue=fact.get("verdict", "dialogue") == "inner_monologue",
            )
        )

    for (chapter_id, entity_name), attributes in (entity_attributes or {}).items():
        if chapter_id not in chapter_text_by_id:
            raise ValueError(f"测试实体属性引用了非本章章节: {chapter_id}")
        registered = [entity for entity in directories[chapter_id]["entities"] if entity.name == entity_name]
        if registered:
            registered[0].attributes = dict(attributes)
        else:
            directories[chapter_id]["entities"].append(
                EntityInput(
                    name=entity_name,
                    entity_type="character",
                    attributes=dict(attributes),
                )
            )

    chapter_annotations: list[BoundChapterAnnotation] = []
    for chapter_id, _chapter_text in chapter_text_by_id.items():
        bound_events: list[BoundEvent] = []
        for event_spec in events or []:
            event_participants = [{"entity": p, "role": "主体"} for p in event_spec.get("participants", [])]
            for p in event_spec.get("participants", []):
                _register_entity(
                    directories[chapter_id],
                    name=p,
                    entity_type="character",
                )
            bound_event = make_bound_event(
                description=event_spec["description"],
                participants=event_participants,
                tree_id=event_spec.get("tree_id"),
                node_id=event_spec.get("node_id"),
                parent_node_id=event_spec.get("parent_node_id"),
                cause_role=event_spec.get("cause_role", "root"),
                evidence_paragraph_id=event_spec.get("evidence_paragraph_id", paragraph_id),
            )
            # 2026-09-13 伏笔即事件树：isforeshadowing=true 的章内事件即伏笔树根
            # （2026-09-14 伏笔属性收敛：expected_payoff_family 退役）
            if event_spec.get("isforeshadowing"):
                bound_event.is_foreshadow_setup = True
                bound_event.payoff_likelihood = event_spec.get("payoff_likelihood", "medium")
            bound_events.append(bound_event)
        # 2026-09-13 伏笔即事件树：setup_event_index（1 基）指向的章内事件即伏笔树根
        for fs_spec in foreshadowings or []:
            root_event = bound_events[int(fs_spec["setup_event_index"]) - 1]
            root_event.is_foreshadow_setup = True
            root_event.payoff_likelihood = fs_spec.get("payoff_likelihood", "medium")
        chapter_annotations.append(
            BoundChapterAnnotation(
                metrics=ChapterMetricsInput(
                    summary=f"章节 {chapter_id} 摘要",
                    emotional_valence=(emotional_valences or {}).get(chapter_id, 0),
                    narrative_function=(event_types or {}).get(chapter_id, "铺垫"),
                    pivot_moment=chapter_id in (pivot_chapters or set()),
                    cliffhanger=chapter_id in (cliffhanger_chapters or set()),
                ),
                character_observations=observations_by_chapter[chapter_id],
                dialogues=dialogues_by_chapter[chapter_id],
                events=bound_events,
            )
        )
    # 2026-09-04 单一写面：实体/关系不再是章标注字段，改为派生 FactGraph 操作日志
    # （在章循环之后收集，事件参与者登记的实体一并覆盖）
    entity_ops: list[dict[str, Any]] = []
    relation_assert_ops: list[dict[str, Any]] = []
    for chapter_id, _chapter_text in chapter_text_by_id.items():
        for entity in directories[chapter_id]["entities"]:
            entity_ops.append(
                {
                    "name": entity.name,
                    "entity_type": str(entity.entity_type),
                    "tags": list(entity.tags or []),
                    "description": entity.description,
                    "attributes": dict(entity.attributes or {}),
                    "chapter_id": chapter_id,
                }
            )
        for relation in relations_by_chapter[chapter_id]:
            relation_assert_ops.append(
                {
                    "from_entity": str(relation.from_entity),
                    "to_entity": str(relation.to_entity),
                    "relation_type": str(relation.relation_type),
                    "chapter_id": chapter_id,
                }
            )
    annotation_id = commit_test_annotation(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=chapter_annotations[0],
        entity_ops=entity_ops,
        relation_assert_ops=relation_assert_ops,
    )
    for resolution in continuity_resolutions or []:
        commit_test_relation_resolution(session, run_id=run_id, chapter_id=chapter_id, **resolution)
    return annotation_id


def commit_test_annotation(
    session: Any,
    *,
    run_id: str,
    chapter_id: int,
    annotation: BoundChapterAnnotation,
    entity_ops: list[dict[str, Any]] | None = None,
    relation_assert_ops: list[dict[str, Any]] | None = None,
) -> str:
    """夹具直接使用 work 和域保存接口，不构造旧冻结、命令或章收尾"""
    from src.agents.annotation.agent import AnnotationAgent, WorkExecution
    from src.agents.annotation.ledger import AnnotationToolLedger
    from src.agents.annotation.paragraphs import build_chapter_paragraph_info
    from src.agents.annotation.subagent_ir import SubagentAnnotation
    from src.agents.annotation.work import WorkReceipt, annotation_work_id
    from src.case_pool import CasePool
    from src.event_bus import EventBus
    from src.event_trees.trees import EventTrees
    from src.fact_graph.graph import FactGraph
    from src.storage.models import AnalysisOutput, AnnotationWork

    chapter = session.get(Chapter, (chapter_id, run_id))
    paragraphs = list(
        session.execute(
            select(Paragraph)
            .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
            .order_by(Paragraph.paragraph_index)
        ).scalars()
    )
    work_id = annotation_work_id(run_id, chapter_id, "solo")
    invocation = uuid4().hex
    payload = {
        "chapter_id": chapter_id,
        "chapter_sequence": chapter.sequence,
        "chapter_label": str(chapter.sequence),
        "chapter_text": chapter.text,
        "chapter_chars": len(chapter.text),
        "role": "solo",
        "paragraphs": paragraphs,
    }
    graph, trees, cases = FactGraph(run_scope=run_id), EventTrees(run_id), CasePool(run_id)
    agent = AnnotationAgent(
        EventBus(),
        run_id,
        get_session_factory(),
        novel_id="fixture",
        fact_graph=graph,
        event_trees=trees,
        case_pool=cases,
    )
    records = list(
        session.execute(select(AnalysisOutput).where(AnalysisOutput.run_id == run_id)).scalars()
    )
    graph.restore_storage(session, records)
    trees.restore_storage(session, records)
    graph.begin(work_id, invocation, chapter.sequence, "solo")
    graph.contributions[(work_id, invocation)]["entity_ops"] = entity_ops or []
    graph.contributions[(work_id, invocation)]["relation_assert_ops"] = relation_assert_ops or []
    graph._fold()
    trees.begin(work_id, invocation)
    trees.sync((work_id, invocation), chapter_id, annotation.events)
    cases.begin(work_id, invocation)
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=chapter_id,
        current_chapter_text=chapter.text,
        allow_future_context=False,
        graph=graph,
        paragraph_info=build_chapter_paragraph_info(paragraphs),
        work_id=work_id,
        invocation_id=invocation,
        role="solo",
    )
    ledger.metrics_payload = annotation.metrics
    ledger.bound_payloads = {
        key: getattr(annotation, key) for key in ("events", "dialogues", "character_observations", "paragraph_labels")
    }
    execution = WorkExecution(
        WorkReceipt(work_id, run_id, "annotation_agent", payload),
        invocation,
        ledger,
        SubagentAnnotation(role="solo"),
        finished=True,
    )
    agent.freeze(execution)
    session.add(
        AnnotationWork(
            work_id=work_id, run_id=run_id, chapter_id=chapter_id, role="solo", invocation_id=invocation, state="saved"
        )
    )
    session.flush()
    result = agent._save(execution, session)
    session.commit()
    agent.close()
    return result


def commit_test_relation_resolution(
    session: Any,
    *,
    run_id: str,
    chapter_id: int,
    from_entity: str,
    to_entity: str,
    relation_type: str,
    change_kind: str,
    reason: str,
) -> None:
    """关系历史夹具使用真实关系端点，不假定实体出现在第一章"""
    from src.storage.repositories import GraphRepository

    matches = []
    for relation in GraphRepository(session).fetch_latest_relations(run_id, active_only=False):
        if relation.relation_type != relation_type:
            continue
        names = relation.from_name, relation.to_name
        if names == (from_entity, to_entity) or (
            relation.directionality == "bidirectional" and names == (to_entity, from_entity)
        ):
            matches.append(relation)
    if len(matches) != 1:
        raise ValueError("关系历史夹具必须唯一定位已存在的关系")
    relation = matches[0]

    target = {
        "domain": "relation",
        "from_entity_id": relation.from_entity_id,
        "to_entity_id": relation.to_entity_id,
        "relation_type": relation_type,
    }
    resolution = {key: value for key, value in {**target, "change_kind": change_kind}.items() if key != "domain"}
    commit_test_resolution(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        target=target,
        resolution=resolution,
        issue_kind="关系变化",
        search_keys=[from_entity, to_entity],
        reason=reason,
    )


def commit_test_resolution(
    session: Any,
    *,
    run_id: str,
    chapter_id: int,
    target: dict[str, Any],
    resolution: dict[str, Any],
    issue_kind: str,
    search_keys: list[str],
    reason: str,
) -> None:
    """关系变化/明确事件连接夹具直接保存领域事实，案例不夹带结构化裁决"""
    from src.utils.identity import stable_uuid, text_digest
    from src.fact_graph.schema import RELATION_DEFINITIONS
    from src.fact_graph.graph import FactGraph
    from src.storage.models import (
        AnalysisOutput,
        AnnotationWork,
        EventEdge,
        EventNode,
        GraphFact,
    )
    from src.storage.repositories.graph.identity import relation_id

    work = session.execute(
        select(AnnotationWork).where(AnnotationWork.run_id == run_id, AnnotationWork.chapter_id == chapter_id)
    ).scalar_one()
    record = session.execute(
        select(AnalysisOutput).where(AnalysisOutput.work_id == work.work_id)
    ).scalar_one()
    paragraph = (
        session.execute(select(Paragraph).where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id))
        .scalars()
        .first()
    )
    evidence = [
        {
            "chapter_id": chapter_id,
            "paragraph_id": paragraph.paragraph_id,
            "char_start": 0,
            "char_end": len(paragraph.text),
            "text_hash": text_digest(paragraph.text),
        }
    ]
    if target["domain"] == "event":
        parent, child = (
            session.get(EventNode, resolution["root_event_id"]),
            session.get(EventNode, resolution["event_id"]),
        )
        edge_type = resolution["edge_type"]
        session.add(
            EventEdge(
                edge_id=stable_uuid(run_id, work.work_id, parent.event_id, child.event_id, edge_type),
                run_id=run_id,
                source_event_id=parent.event_id,
                target_event_id=child.event_id,
                source_chapter_id=parent.chapter_id,
                target_chapter_id=child.chapter_id,
                edge_type=edge_type,
                evidence=evidence,
                is_active=True,
                annotation_id=record.output_id,
                payload_path=f"fixture/{parent.event_id}/{child.event_id}",
                author_work_id=work.work_id,
                cause_role=None,
            )
        )
        session.flush()
        from src.event_trees.trees import EventTrees

        EventTrees(run_id).rebuild_storage(session)
    elif target["domain"] == "relation":
        from src.storage.models import GraphEntity

        left, right = (
            session.get(GraphEntity, target["from_entity_id"]),
            session.get(GraphEntity, target["to_entity_id"]),
        )
        identifier = relation_id(
            run_id,
            left.entity_id,
            right.entity_id,
            target["relation_type"],
            RELATION_DEFINITIONS[target["relation_type"]]["directionality"],
        )
        op = {
            "from_entity": left.canonical_name,
            "to_entity": right.canonical_name,
            "relation_type": target["relation_type"],
            "chapter_id": chapter_id,
            "change_kind": resolution["change_kind"],
            "reason": reason,
        }
        fact_id = stable_digest(run_id, chapter_id, op)
        session.add(
            GraphFact(
                run_id=run_id,
                chapter_id=chapter_id,
                fact_id=fact_id,
                fact_type="relation",
                subject_entity_id=left.entity_id,
                predicate="relation",
                object=None,
                value=op,
                participants=[],
                scope="book",
                assertion="asserted",
                confidence="high",
                content={"kind": "relation", "operation": op, "operation_order": 1000, "relation_id": identifier},
                effective_chapter_id=chapter_id,
                source_kind="annotation",
                annotation_id=record.output_id,
                payload_path=f"fixture/{fact_id}",
                author_work_id=work.work_id,
                evidence=evidence,
            )
        )
        session.flush()
        FactGraph(run_scope=run_id).rebuild_storage(session)
    else:
        raise ValueError("夹具必须指定当前领域有效端点")
    session.commit()


def commit_test_event_link(
    session: Any,
    *,
    run_id: str,
    chapter_id: int,
    source_event_id: str,
    target_event_id: str,
    edge_type: str = "causal",
) -> None:
    """跨树事件关联经当前连续性事务生成，不插入历史格式的因果边"""
    commit_test_resolution(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        target={"domain": "event", "event_id": target_event_id},
        resolution={"root_event_id": source_event_id, "event_id": target_event_id, "edge_type": edge_type},
        issue_kind="因果疑点",
        search_keys=[source_event_id, target_event_id],
        reason="原文确认事件关联",
    )


def confirm_test_work(session: Any, run_id: str, *, create_missing: bool = False) -> None:
    """只读查询夹具显式构造实际保存 work，不再设置发布 hash"""
    from src.storage.models import AnnotationWork

    saved = set(session.execute(select(AnnotationWork.chapter_id).where(AnnotationWork.run_id == run_id)).scalars())
    for chapter in session.execute(select(Chapter).where(Chapter.run_id == run_id)).scalars().all():
        paragraphs_exist = (
            session.execute(
                select(Paragraph.paragraph_id).where(
                    Paragraph.run_id == run_id, Paragraph.chapter_id == chapter.chapter_id
                )
            ).first()
            is not None
        )
        from src.storage.models import EventNode, GraphEntity

        graph_exists = (
            session.execute(select(GraphEntity.entity_id).where(GraphEntity.run_id == run_id)).first() is not None
        )
        event_exists = session.execute(select(EventNode.event_id).where(EventNode.run_id == run_id)).first() is not None
        if chapter.chapter_id not in saved and paragraphs_exist and (create_missing or graph_exists or event_exists):
            commit_test_annotation(
                session,
                run_id=run_id,
                chapter_id=chapter.chapter_id,
                annotation=BoundChapterAnnotation(
                    metrics=ChapterMetricsInput(
                        summary=chapter.text or "夹具", emotional_valence=0, narrative_function="铺垫"
                    ),
                    character_observations=[],
                    dialogues=[],
                    events=[],
                ),
            )
    session.commit()
