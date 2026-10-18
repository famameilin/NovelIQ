"""Agent 侧章末来源汇集与引用核对，无模型调用、不改写来源节点"""

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.case_pool import CasePool
from src.fact_graph.evidence import EvidenceParagraph, evidence_for
from src.fact_graph.read.references import EntityReferenceProjection
from src.storage.models import (
    BookCase,
    CaseEntry,
    Chapter,
    ChapterAnnotation,
    DeclarationParticipant,
    DialogueRecord,
    EventDeclaration,
    Execution,
    GraphEntity,
    GraphFact,
    Paragraph,
    SourceEvidence,
    WorkItem,
)
from src.storage.repositories.graph.repository import GraphRepository
from src.utils.identity import stable_digest
from src.work.policy import completed_chapters

RULE_VERSION = "chapter-entity-consolidation-2026-10-14"
PROGRAM_CODE = "chapter_consolidation"


def discard_chapter_receipts(session: Session, run_id: str, chapter_ids: set[int]) -> None:
    """整章废弃时撤销章末核对凭据（来源集合已失效，重建不得被旧回执阻挡）

    凭据是由该章 work 产物派生的程序回执：声明被废弃后，来源摘要不再有效，
    必须连同其事实与程序支持条目一起清除，重建章才能生成新回执。
    """
    from sqlalchemy import delete

    if not chapter_ids:
        return
    receipts = list(
        session.scalars(
            select(WorkItem.work_id).where(
                WorkItem.program_run_id == run_id,
                WorkItem.program_chapter_id.in_(sorted(chapter_ids)),
                WorkItem.program_code == PROGRAM_CODE,
            )
        )
    )
    if not receipts:
        return
    supported_cases = list(
        session.scalars(
            select(CaseEntry.case_id).where(
                CaseEntry.program_work_id.in_(receipts), CaseEntry.case_id.is_not(None)
            )
        )
    )
    session.execute(delete(CaseEntry).where(CaseEntry.program_work_id.in_(receipts)))
    session.execute(delete(GraphFact).where(GraphFact.program_work_id.in_(receipts)))
    session.execute(delete(WorkItem).where(WorkItem.work_id.in_(receipts)))
    # 凭据只支持本章退场案例：目标（实体/关系）随原料废弃，案例行不留下悬空正式目标
    if supported_cases:
        session.execute(delete(BookCase).where(BookCase.case_id.in_(supported_cases)))
    session.flush()

CHARACTER_REASONS = {
    "identity_assertion_conflict",
    "representative_ambiguous",
    "dangling_participant",
    "unreferenced_entity",
}

REASONS = {
    "identity_assertion_conflict": "身份断言分歧",
    "representative_ambiguous": "代表判不定",
    "dangling_relation": "关系悬空",
    "dangling_participant": "参与者未登记",
    "root_unreachable": "过程无根",
    "unreferenced_entity": "实体无引用",
}


def case_description(issue: dict[str, Any]) -> str:
    """完整节点键、原因和主段号优先；超长正文名称明确标示截短，完整证据保存在结论中"""
    paragraphs = sorted({item["paragraph_id"] for item in issue["evidence"] if "paragraph_id" in item})
    suffix = f"；类={issue['entity_type']}；码={REASONS[issue['reason']]}；段={paragraphs[0] if paragraphs else '无'}"
    prefix = f"节点={issue['node_id']}；名="
    available = 100 - len(prefix) - len(suffix)
    if available < 2:
        raise ValueError(f"章末案例定位超过描述长度: {issue['node_id']}")
    name = " ".join(str(issue["name"]).split())
    if len(name) > available:
        name = name[: available - 1] + "…"
    return prefix + name + suffix


def eligible_chapters(session: Session, run_id: str) -> set[int]:
    """只恢复启用本步骤后保存的章；历史完成章不通过新程序追溯补写"""
    return {
        int(chapter_id)
        for chapter_id, version in session.execute(
            select(ChapterAnnotation.chapter_id, ChapterAnnotation.chapter_consolidation_version).where(
                ChapterAnnotation.run_id == run_id
            )
        )
        if version == RULE_VERSION
    }


def case_spec(item: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """章末案例显式归类：人物悬置归 character、关系悬空归 relation、其余按事件处理

    payload 携带定位键与首段事实证据，处置方不必再解析描述文本。
    """
    paragraphs = sorted(
        {
            (entry["chapter_id"], entry["paragraph_id"])
            for entry in item["evidence"]
            if "chapter_id" in entry and "paragraph_id" in entry
        }
    )
    reason = item["reason"]
    payload: dict[str, Any] = {
        "node_id": item["node_id"],
        "name": item["name"],
        "entity_type": item["entity_type"],
        "reason": reason,
    }
    if paragraphs:
        payload["chapter_id"], payload["paragraph_id"] = paragraphs[0]
    description = case_description(item)
    if reason == "dangling_relation":
        return "relation", description, payload
    if reason in CHARACTER_REASONS:
        return "character", description, payload
    payload["event_id"] = item["node_id"]
    return "event", description, payload


def consolidate_chapter(
    session: Session, run_id: str, chapter_id: int, cases: CasePool, *, recheck: bool = False
) -> dict[str, Any]:
    """在调用方短事务中保存一次来源绑定的结论；案例、回执和完成凭据一起提交

    回执不保存结论 JSON：来源摘要以 program_invocation_key（chapter:{章}:{digest}）
    冻结，sources/identity_mapping/support/issues 由正式贡献按本规则版本投影。
    recheck 供池排空后的按序收尾使用：整体重算，结果与既有回执一致则当作既有回执不动，
    不一致才废弃旧回执重落——并发完成序反转时早跑的核对看不到更早章未保存的引用，
    会把实体误判成孤立，收尾重算负责清掉这类误报。
    """
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{run_id}"})
    chapter_records = list(
        session.scalars(
            select(ChapterAnnotation)
            .where(ChapterAnnotation.run_id == run_id, ChapterAnnotation.chapter_id == chapter_id)
            .order_by(ChapterAnnotation.role, ChapterAnnotation.record_id)
        )
    )
    states = [
        SimpleNamespace(chapter_id=chapter_id, state="saved", role=str(record.role))
        for record in chapter_records
    ]
    if chapter_id not in completed_chapters(states):
        raise ValueError(f"章末核对缺少必需角色的有效保存产物: chapter_id={chapter_id}")
    if not all(record.chapter_consolidation_version == RULE_VERSION for record in chapter_records):
        return {"status": "historical", "chapter_id": chapter_id}
    sources = [
        {"execution_id": str(record.execution_id), "output_id": str(record.record_id)}
        for record in chapter_records
    ]
    digest = stable_digest(run_id, chapter_id, RULE_VERSION, sources)
    previous = session.scalar(
        select(WorkItem).where(
            WorkItem.program_run_id == run_id,
            WorkItem.program_chapter_id == chapter_id,
            WorkItem.program_code == PROGRAM_CODE,
        )
    )
    if previous is not None:
        if previous.program_invocation_key != f"chapter:{chapter_id}:{digest}":
            raise ValueError(f"章末凭据与有效来源集合不同，不能覆盖: chapter_id={chapter_id}")
        if not recheck:
            return {"status": "existing", "chapter_id": chapter_id, "fact_id": digest}
        # 重算要替换旧回执：先把旧行从会话身份图里摘掉，替换时按同一 author 重新插入
        session.expunge(previous)
    repo = GraphRepository(session)
    boundary = repo.resolve_chapter_boundary(run_id, chapter_id=chapter_id)
    if boundary is None:
        raise ValueError(f"章末缺少正式章节边界: chapter_id={chapter_id}")
    projection = EntityReferenceProjection.load(session, run_id, boundary=boundary)
    chapters = {
        row.chapter_id: row.sequence for row in session.scalars(select(Chapter).where(Chapter.run_id == run_id))
    }
    sequence = chapters[chapter_id]
    # 全书可见保存产物（含本章）作为身份与支持的有效边界
    visible: dict[str, ChapterAnnotation] = {}
    for record in session.scalars(select(ChapterAnnotation).where(ChapterAnnotation.run_id == run_id)):
        if chapters.get(int(record.chapter_id), 0) <= sequence:
            visible[str(record.record_id)] = record
    valid_executions = {str(record.execution_id) for record in visible.values()}
    fact_rows = list(
        session.execute(
            select(GraphFact, Execution.chapter_id)
            .join(Execution, Execution.execution_id == GraphFact.direct_producer_execution_id)
            .where(GraphFact.direct_producer_execution_id.in_(valid_executions))
        )
    )
    fact_chapter: dict[int, int | None] = {}
    for fact, execution_chapter in fact_rows:
        if fact.effective_chapter_id is not None:
            fact_chapter[int(fact.graph_fact_id)] = int(fact.effective_chapter_id)
        elif execution_chapter is not None:
            fact_chapter[int(fact.graph_fact_id)] = int(execution_chapter)
        else:
            fact_chapter[int(fact.graph_fact_id)] = None
    fact_evidence: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if fact_chapter:
        for evidence in session.scalars(
            select(SourceEvidence).where(SourceEvidence.graph_fact_id.in_(list(fact_chapter)))
        ):
            fact_id = cast(int, evidence.graph_fact_id)
            fact_evidence[fact_id].append(
                {
                    "chapter_id": fact_chapter[fact_id],
                    "paragraph_id": int(evidence.paragraph_id),
                    "char_start": int(evidence.start_char),
                    "char_end": int(evidence.end_char),
                }
            )
    records_by_record = {str(record.record_id): record for record in visible.values()}

    def record_chapter(record_id: str) -> int | None:
        record = records_by_record.get(str(record_id))
        return int(record.chapter_id) if record is not None else None

    declarations = list(
        session.scalars(select(EventDeclaration).where(EventDeclaration.record_id.in_(list(records_by_record))))
    )
    declaration_chapter = {str(row.declaration_id): record_chapter(str(row.record_id)) for row in declarations}
    declaration_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    participants_by_declaration: dict[str, list[DeclarationParticipant]] = defaultdict(list)
    if declarations:
        declaration_ids = [str(row.declaration_id) for row in declarations]
        for evidence in session.scalars(
            select(SourceEvidence).where(SourceEvidence.declaration_id.in_(declaration_ids))
        ):
            declaration_evidence[str(evidence.declaration_id)].append(
                {
                    "chapter_id": declaration_chapter.get(str(evidence.declaration_id)),
                    "paragraph_id": int(evidence.paragraph_id),
                    "char_start": int(evidence.start_char),
                    "char_end": int(evidence.end_char),
                }
            )
        for participant in session.scalars(
            select(DeclarationParticipant).where(DeclarationParticipant.declaration_id.in_(declaration_ids))
        ):
            participants_by_declaration[str(participant.declaration_id)].append(participant)
    dialogues = list(
        session.scalars(
            select(DialogueRecord).where(DialogueRecord.creation_execution_id.in_(valid_executions))
        )
    )
    paragraph_rows = list(
        session.scalars(
            select(Paragraph)
            .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
            .order_by(Paragraph.paragraph_index)
        )
    )
    chapter_evidence = evidence_for(
        tuple(
            EvidenceParagraph(
                row.chapter_id,
                row.paragraph_id,
                row.text,
                row.local_start_char,
                row.local_start_char + len(row.text),
            )
            for row in paragraph_rows
        )
    )
    if not chapter_evidence:
        raise ValueError(f"章末凭据缺少原文证据: chapter_id={chapter_id}")
    entity_ids: set[str] = set()
    evidence_by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    touched: set[str] = set()
    for fact in fact_rows:
        fact_obj = fact[0]
        if fact_obj.entity_id is None:
            continue
        entity_ids.add(str(fact_obj.entity_id))
        evidence_by_entity[str(fact_obj.entity_id)].extend(fact_evidence.get(int(fact_obj.graph_fact_id), []))
        if fact_chapter.get(int(fact_obj.graph_fact_id)) == chapter_id:
            touched.add(str(fact_obj.entity_id))
    lookup_ids = set(entity_ids)
    lookup_ids.update(
        str(participant.entity_id)
        for participants in participants_by_declaration.values()
        for participant in participants
    )
    entity_names: dict[str, GraphEntity] = {}
    if lookup_ids:
        entity_names = {
            str(row.entity_id): row
            for row in session.scalars(select(GraphEntity).where(GraphEntity.entity_id.in_(lookup_ids)))
        }

    def entity_label(identifier: str) -> tuple[str, str]:
        row = entity_names.get(identifier)
        return (str(row.canonical_name), str(row.entity_type)) if row is not None else (identifier, "")

    issues: list[dict[str, Any]] = []

    def issue(node_id: str, name: str, entity_type: str, reason: str, evidence: list[dict[str, Any]]) -> None:
        issues.append(
            {
                "node_id": node_id,
                "name": name,
                "entity_type": entity_type,
                "reason": reason,
                "evidence": evidence or chapter_evidence,
            }
        )

    for identifier, reason in sorted(projection.resolution.conflicts.items()):
        if identifier in touched:
            entity = projection.entities[identifier]
            issue(identifier, entity.name, entity.entity_type, reason, evidence_by_entity[identifier])
    referenced: set[str] = set()
    for relation in repo.fetch_relation_snapshots(boundary, active_only=False):
        endpoints = (relation.from_entity_id, relation.to_entity_id)
        referenced.update(endpoints)
        if relation.chapter_id == chapter_id and any(endpoint not in projection.entities for endpoint in endpoints):
            issue(
                relation.relation_id,
                f"{relation.from_name}/{relation.to_name}",
                "relation",
                "dangling_relation",
                [
                    item
                    for fact in fact_rows
                    if str(fact[0].relation_id or "") == relation.relation_id
                    for item in fact_evidence.get(int(fact[0].graph_fact_id), [])
                ],
            )
    for declaration in declarations:
        node_evidence = declaration_evidence.get(str(declaration.declaration_id), [])
        for participant in participants_by_declaration.get(str(declaration.declaration_id), []):
            identifier = str(participant.entity_id)
            referenced.add(identifier)
            if declaration_chapter.get(str(declaration.declaration_id)) == chapter_id:
                name, entity_type = entity_label(identifier)
                if identifier not in projection.entities:
                    issue(identifier, name, entity_type, "dangling_participant", node_evidence)
    for dialogue in dialogues:
        if dialogue.speaker_entity_id:
            referenced.add(str(dialogue.speaker_entity_id))
    # 正式别名分量有任意有效引用即已接上，不能把保留的别名源节点判成孤立
    referenced = {projection.resolution.resolve_entity_id(identifier) or identifier for identifier in referenced}
    for identifier in sorted(touched):
        representative = projection.resolution.resolve_entity_id(identifier) or identifier
        if representative not in referenced and identifier in projection.entities:
            entity = projection.entities[identifier]
            issue(identifier, entity.name, entity.entity_type, "unreferenced_entity", evidence_by_entity[identifier])
    author = f"chapter:{chapter_id}:{digest[:16]}"
    if previous is not None:
        existing = set(
            session.scalars(
                select(BookCase.description)
                .join(CaseEntry, CaseEntry.case_id == BookCase.case_id)
                .where(CaseEntry.program_work_id == author)
            )
        )
        if existing == {case_description(item) for item in issues}:
            return {"status": "existing", "chapter_id": chapter_id, "fact_id": digest}
        discard_chapter_receipts(session, run_id, {chapter_id})
    program_work = WorkItem(
        work_id=author,
        program_run_id=run_id,
        program_chapter_id=chapter_id,
        program_code=PROGRAM_CODE,
        program_invocation_key=f"chapter:{chapter_id}:{digest}",
    )
    session.add(program_work)
    session.flush()
    session.add(GraphFact(program_work_id=author))
    session.flush()
    case_ids = cases.save_pending(session, [case_spec(item) for item in issues], author=author)
    return {
        "status": "saved",
        "chapter_id": chapter_id,
        "fact_id": digest,
        "author": author,
        "case_ids": case_ids,
        "issues": len(issues),
    }
