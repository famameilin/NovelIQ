"""章节正式标注与数据库图测试夹具

写面合同（与 src/agents/annotation/agent.py 的 _save 一致）：
- 真实尝试 = agent 的 invocation 形状（run_id/章/角色 + attempt_number + status）
- 正式产物 = agent_annotations 头（自带 run/章/角色）+ 五组件同事务（事件声明、
  事实图、对话与逐段情绪、案例）
- 队列票据身份（annotation_work_id）只是内存对象，不落 work_items 行
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.output_models import BoundChapterAnnotation
from src.event_trees.models import BoundEvent, EventParticipantInput
from src.fact_graph.inputs import BoundRelationInput, ChapterMetricsInput, EntityInput
from src.fact_graph.outputs import BoundCharacterObservation, BoundDialogue
from src.fact_graph.vocabulary import EntityType
from src.storage import new_id
from src.storage.db import get_session_factory
from src.storage.models import (
    Agent,
    Chapter,
    ChapterAnnotation,
    Novel,
    Paragraph,
)
from src.storage.models.base import naive_utcnow
from src.storage.repositories import ChapterRepository, RunRepository
from src.text_processing.models import Chunk as ChunkerChunk
from src.text_processing.paragraphs import split_chunk_paragraphs
from src.work.annotation_work import annotation_work_id
from tests.support.storage_fixtures import fixture_id, natural_record, storage_factory, storage_for, uuid7


@dataclass(frozen=True, slots=True)
class _SavedWorkRecord:
    """已保存标注的真实执行复读身份：执行号与正式产物号同源，供域重建读取"""

    agent_id: str
    record_id: str
    chapter_id: int
    role: str
    sequence: int

    @property
    def invocation_id(self) -> str:
        return self.agent_id

    @property
    def output_id(self) -> str:
        return self.record_id


def create_run_with_chunks(
    session: Any,
    *,
    texts: list[str],
    chapter_ids: list[int] | None = None,
    title: str = "章节事实测试",
) -> tuple[str, str]:
    """创建带真实章节身份的小说运行与原文章节"""
    novel_id = new_id()
    run_id = new_id()
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
    RunRepository(session).create_run(novel_id=novel_id, run_id=run_id)
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
    # -2：chunks 表合并进 chapters——正文切片经 ChapterRepository 落库
    # （缺失章节行以默认结构补建，见 insert_chapter_texts）
    ChapterRepository(session).insert_chapter_texts(run_id, chunks)
    session.commit()
    # 二期：annotate 阶段要求段落事实源存在（章节段落边界查询），
    # helper 同步插入段落行（一次传入全部章节，paragraph_id 全局连续），
    # token_count 用简单切分填充
    from src.storage.repositories import ParagraphRepository

    spans = [replace(span, token_count=max(1, len(span.text) // 2)) for span in split_chunk_paragraphs(chunks)]
    if spans:
        ParagraphRepository(session).insert_paragraphs(run_id, spans)
        session.commit()
    return novel_id, run_id


def _saved_work_records(session: Any, run_id: str) -> list[_SavedWorkRecord]:
    """按正式关系复读本 run 已保存标注（章末核对与域重建共用读取身份）"""
    rows = session.execute(
        select(
            ChapterAnnotation.agent_id,
            ChapterAnnotation.record_id,
            ChapterAnnotation.chapter_id,
            ChapterAnnotation.role,
            Chapter.sequence,
        )
        .join(Agent, Agent.id == ChapterAnnotation.agent_id)
        .join(
            Chapter,
            (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id),
        )
        .where(ChapterAnnotation.run_id == run_id)
        .order_by(Chapter.sequence, ChapterAnnotation.role, ChapterAnnotation.record_id)
    ).all()
    return [
        _SavedWorkRecord(
            agent_id=str(agent_id),
            record_id=str(record_id),
            chapter_id=int(chapter_id),
            role=str(role),
            sequence=int(sequence),
        )
        for agent_id, record_id, chapter_id, role, sequence in rows
    ]


def _create_work_identity(session: Any, *, run_id: str, chapter_id: int, role: str = "annotation") -> tuple[str, str]:
    """登记 agent 的真实尝试，返回 (队列票据 work_id, invocation_id)

    票据身份只是内存对象：正式产物 record_id 与对话/树记录键都按它铸造，
    agent 行只落真实归属（run/章/角色）。
    """
    work_id = annotation_work_id(run_id, chapter_id, role)
    invocation = new_id()
    session.add(Agent(id=invocation, run_id=run_id, type=role, status="running"))
    session.flush()
    return work_id, invocation


def _finish_execution(session: Any, invocation: str) -> None:
    """真实尝试在当前事务内收口为成功终态（失败尝试不写正式产物）"""
    execution = session.get(Agent, invocation)
    if execution is not None:
        execution.status = "success"
        execution.finished_at = naive_utcnow()
    session.flush()


def _work_execution_of_chapter(session: Any, run_id: str, chapter_id: int) -> str:
    """按章取本 run 已保存标注的真实执行（优先整章 annotation，其次长章三工位）"""
    records = [record for record in _saved_work_records(session, run_id) if record.chapter_id == chapter_id]
    if not records:
        raise ValueError(f"章节没有已保存标注的真实执行: run_id={run_id} chapter_id={chapter_id}")
    preference = {"annotation": 0, "metric": 1, "entity": 2, "event": 3}
    record = min(records, key=lambda item: (preference.get(item.role, 9), item.record_id))
    return record.agent_id


def _entity_spec(
    name: str,
    entity_type: EntityType,
    tags: list[str] | None = None,
) -> dict[str, str | list[str]]:
    """声明事实隐含的实体名称、大类与可选标签"""
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
    """构造章内人物观察输入测试值"""
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
    """构造章内三字段关系边输入测试值（本章确认存在的边）"""
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
    """构造按系统候选对齐的对话输入测试值"""
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
    """构造同一人物关系的测试标注项"""
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
    """把事实隐含实体注册到当前章实体目录"""
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
    title: str | None = None,
    problem: str = "明确事件问题",
    summary: str | None = None,
    event_type: str = "行动",
    status: str = "ongoing",
    progress: str | None = None,
) -> BoundEvent:
    """构造带本章段落证据的正式事件"""
    node_id = node_id or new_id()
    return BoundEvent(
        node_id=node_id,
        tree_id=tree_id or f"tree-{uuid7()}",
        parent_node_id=parent_node_id,
        cause_role=cause_role,
        description=description,
        evidence_paragraph_id=evidence_paragraph_id,
        participants=[EventParticipantInput(entity=p["entity"], role=p["role"]) for p in participants or []],
        title=title if title is not None else description,
        problem=problem,
        summary=summary if summary is not None else description,
        event_type=event_type,
        status=status,
        progress=progress,
        event_id=node_id,
        from_chapter_id=1,
        to_chapter_id=1,
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
    """通过 Agent 与三个域保存一份真实整章标注（annotation 角色），供消费端回归读取"""
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
    relations_by_chapter: dict[int, list[BoundRelationInput]] = {key: [] for key in keys}

    for fact in characters or []:
        chapter_id = int(fact["chapter_id"])
        if chapter_id not in chapter_text_by_id:
            raise ValueError(f"测试事实引用了非本章章节: {chapter_id}")
        # 本形参只落观测载荷：3NF 后人物观测的可读行需要带三态的声明参与者，
        # 需要读面人物行请用 character_observation_helpers.persist_observed_characters
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
            BoundRelationInput(
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
        # 实体不再存任意属性列，只有 description/representative 是显式字段；
        # 其余测试键不落库（夹具保留形参以维持调用面）
        merged = dict(attributes)
        description = merged.pop("description", None)
        representative = merged.pop("representative", None)
        registered = [entity for entity in directories[chapter_id]["entities"] if entity.name == entity_name]
        if registered:
            if description is not None:
                registered[0].description = description
            if representative is not None:
                registered[0].representative = representative
        else:
            directories[chapter_id]["entities"].append(
                EntityInput(
                    name=entity_name,
                    entity_type="character",
                    description=description,
                    representative=representative,
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
                title=event_spec.get("title"),
                problem=event_spec.get("problem", "明确事件问题"),
                summary=event_spec.get("summary"),
                event_type=event_spec.get("event_type", "行动"),
                status=event_spec.get("status", "ongoing"),
                progress=event_spec.get("progress"),
            )
            # 伏笔即事件树：isforeshadowing=true 的章内事件即伏笔树根
            if event_spec.get("isforeshadowing"):
                bound_event.is_foreshadow_setup = True
                bound_event.payoff_likelihood = event_spec.get("payoff_likelihood", "medium")
            bound_events.append(bound_event)
        # 伏笔即事件树：setup_event_index（1 基）指向的章内事件即伏笔树根
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
    # 单一写面：实体/关系不再是章标注字段，改为派生 FactGraph 操作日志
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
                    "representative": entity.representative,
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
    from src.agents.annotation.agent_ir import AgentAnnotation
    from src.agents.annotation.ledger import AnnotationToolLedger
    from src.agents.annotation.paragraphs import build_chapter_paragraph_info
    from src.case_pool import CasePool
    from src.event_bus import EventBus
    from src.event_trees.trees import EventTrees
    from src.fact_graph.graph import FactGraph
    from src.work.annotation_work import WorkReceipt

    # chapters 主键顺序为 (run_id, chapter_id)
    chapter = natural_record(session, Chapter, {"run_id": run_id, "chapter_id": chapter_id})
    # local_end_char/global 坐标/char_count 是读取投影，不是段落列；
    # 夹具按生产派发口径组装段落事实（与 annotate 的 _load_work 同形）
    from types import SimpleNamespace

    from src.storage.repositories import ParagraphRepository

    paragraphs = [
        SimpleNamespace(
            chapter_id=row.chapter_id,
            paragraph_id=row.paragraph_id,
            local_start_char=row.local_start_char,
            local_end_char=row.local_end_char,
            text=row.text,
        )
        for row in ParagraphRepository(session).fetch_paragraph_rows_batch(run_id, chapter_id=chapter_id, limit=None)
    ]
    work_id, invocation = _create_work_identity(session, run_id=run_id, chapter_id=chapter_id, role="annotation")
    payload = {
        "chapter_id": chapter_id,
        "chapter_sequence": chapter.sequence,
        "chapter_label": str(chapter.sequence),
        "chapter_text": chapter.text,
        "chapter_chars": len(chapter.text),
        "role": "annotation",
        "paragraphs": paragraphs,
    }
    graph, trees, cases = FactGraph(run_scope=run_id), EventTrees(run_id), CasePool(run_id)
    agent = AnnotationAgent(
        EventBus(),
        run_id,
        storage_factory(get_session_factory()),
        novel_id=fixture_id(__name__, "fixture"),
        fact_graph=graph,
        event_trees=trees,
        case_pool=cases,
    )
    records = _saved_work_records(session, run_id)
    graph.restore_storage(storage_for(session), records)
    trees.restore_storage(storage_for(session), records)
    graph.begin(invocation, chapter.sequence, "annotation")
    graph.contributions[invocation]["entity_ops"] = entity_ops or []
    graph.contributions[invocation]["relation_assert_ops"] = relation_assert_ops or []
    graph._fold()
    # 身份=规范名+实体大类：夹具的历史操作与参与者以登记名给出，
    # 冻结前按图登记把端点/参与者翻成实体身份键（生产面存的就是复合键）
    name_to_key = {display: key for key, display in graph.entity_names.items()}

    def _to_key(name: str) -> str:
        return name_to_key.get(name, name)

    for op in graph.contributions[invocation]["relation_assert_ops"]:
        op["from_entity"] = _to_key(str(op["from_entity"]))
        op["to_entity"] = _to_key(str(op["to_entity"]))
    graph._fold()
    for event in annotation.events:
        for participant in event.participants:
            participant.entity = _to_key(participant.entity)
    trees.begin(invocation)
    trees.sync(invocation, chapter_id, annotation.events)
    cases.begin(invocation)
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=chapter_id,
        current_chapter_text=chapter.text,
        allow_future_context=False,
        graph=graph,
        paragraph_info=build_chapter_paragraph_info(paragraphs),
        work_id=work_id,
        invocation_id=invocation,
        role="annotation",
    )
    ledger.metrics_payload = annotation.metrics
    ledger.events.bound_payloads["events"] = annotation.events
    # 标注只保存过程；消费者需要的完整事件通过诊断夹具另行建立
    ledger.events.bound_payloads["character_observations"] = annotation.character_observations
    ledger.dialogue.bound_payloads["dialogues"] = annotation.dialogues
    ledger.metrics.bound_payloads["paragraph_labels"] = annotation.paragraph_labels
    execution = WorkExecution(
        WorkReceipt(work_id, run_id, "annotation_agent", payload),
        invocation,
        ledger,
        AgentAnnotation(role="annotation"),
        finished=True,
    )
    agent.freeze(execution)
    result = agent._save(execution, storage_for(session))
    _finish_execution(session, invocation)
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
    from src.storage.models import GraphEntity, GraphFact, GraphRelation, NarrativeLink, SourceEvidence

    invocation = _work_execution_of_chapter(session, run_id, chapter_id)
    paragraph = (
        session.execute(select(Paragraph).where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id))
        .scalars()
        .first()
    )
    if target["domain"] == "event":
        # 章级声明之间的显式关联是 narrative_links 的语义/因果形状（声明端点）
        link_type = str(resolution["edge_type"])
        source_id = str(resolution["root_event_id"])
        target_id = str(resolution["event_id"])
        link_id = fixture_id(run_id, invocation, source_id, target_id, link_type)
        session.add(
            NarrativeLink(
                link_id=link_id,
                producer_agent_id=invocation,
                reason=reason,
                semantic_source_event_id=source_id,
                semantic_target_event_id=target_id,
                relation_type=link_type,
                source_operation_local_key=f"fixture-link/{link_id}"[:128],
            )
        )
        session.flush()
        session.add(
            SourceEvidence(
                evidence_id=new_id(),
                narrative_link_id=link_id,
                ordinal=0,
                paragraph_id=int(paragraph.paragraph_id),
                start_char=0,
                end_char=len(paragraph.text),
            )
        )
        session.flush()
    elif target["domain"] == "relation":
        from src.fact_graph.vocabulary import RELATION_DEFINITIONS
        from tests.support.storage_fixtures import relation_id

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
        relation = session.get(GraphRelation, identifier)
        if relation is None:
            raise ValueError(f"关系历史夹具必须引用已存在的关系: relation_id={identifier}")
        fact = GraphFact(
            direct_producer_agent_id=invocation,
            operation_order=1000,
            relation_id=relation.relation_id,
            relation_change_kind=str(resolution["change_kind"]),
            reason=reason,
        )
        session.add(fact)
        session.flush()
        session.add(
            SourceEvidence(
                evidence_id=new_id(),
                graph_fact_id=fact.graph_fact_id,
                ordinal=0,
                paragraph_id=int(paragraph.paragraph_id),
                start_char=0,
                end_char=len(paragraph.text),
            )
        )
        session.flush()
        from src.fact_graph.graph import FactGraph

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
    """跨树事件关联经当前声明候选关系事务生成，不插入历史格式的因果边"""
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
    """只读查询夹具显式构造实际保存标注，不再设置发布 hash"""
    from src.storage.models import CompleteEvent, GraphEntity

    saved = {
        int(chapter_id)
        for chapter_id in session.execute(
            select(ChapterAnnotation.chapter_id)
            .join(Agent, Agent.id == ChapterAnnotation.agent_id)
            .where(ChapterAnnotation.run_id == run_id)
        ).scalars()
    }
    for chapter in session.execute(select(Chapter).where(Chapter.run_id == run_id)).scalars().all():
        paragraphs_exist = (
            session.execute(
                select(Paragraph.paragraph_id).where(
                    Paragraph.run_id == run_id, Paragraph.chapter_id == chapter.chapter_id
                )
            ).first()
            is not None
        )
        graph_exists = (
            session.execute(select(GraphEntity.entity_id).where(GraphEntity.run_id == run_id)).first() is not None
        )
        event_exists = (
            session.execute(
                select(CompleteEvent.event_id)
                .join(ChapterAnnotation, ChapterAnnotation.record_id == CompleteEvent.annotation_record_id)
                .where(ChapterAnnotation.run_id == run_id)
            ).first()
            is not None
        )
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
