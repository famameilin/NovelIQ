"""Agent 侧章末来源汇集与引用核对，无模型调用、不改写来源节点"""

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace
from typing import Any

from src.case_pool import CasePool
from src.fact_graph.evidence import EvidenceParagraph, evidence_for
from src.fact_graph.read.references import EntityReferenceProjection
from src.fact_graph.read.storage_projection import graph_projection
from src.storage import Storage
from src.storage.records.models import ChapterAnnotationRecord as ChapterAnnotation
from src.storage.records.models import DeclarationParticipantRecord as DeclarationParticipant
from src.storage.records.models import GraphEntityRecord as GraphEntity
from src.utils.identity import stable_digest
from src.work.policy import completed_chapters

PROGRAM_CODE = "chapter_consolidation"
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
    "用普通文字说明待核查问题，不嵌入目标或原文坐标"
    name = " ".join(str(issue["name"]).split())
    problem = {
        "identity_assertion_conflict": "身份判断存在分歧，请核查",
        "representative_ambiguous": "代表身份不明确，请核查",
        "dangling_relation": "关系端点尚未确认，请核查",
        "dangling_participant": "参与者尚未登记，请核查",
        "root_unreachable": "事件过程缺少起点，请核查",
        "unreferenced_entity": "实体尚无正式引用，请核查",
    }[issue["reason"]]
    return f"{name[: 100 - len(problem) - 1]}：{problem}"


def eligible_chapters(session: Storage, run_id: str) -> set[int]:
    "读取当前运行已保存的章节"
    return {
        int(_stored_row_1.chapter_id)
        for _stored_row_1 in session.reads.agents_annotation_chapter_consolidation_eligible_chapters_1(run_id)
    }


def case_spec(item: dict[str, Any]) -> tuple[str, str]:
    "按问题所属领域登记普通文字案例"
    kind = (
        "relation"
        if item["reason"] == "dangling_relation"
        else "character"
        if item["reason"] in CHARACTER_REASONS
        else "event"
    )
    return kind, case_description(item)


def consolidate_chapter(
    session: Storage, run_id: str, chapter_id: int, cases: CasePool, *, recheck: bool = False
) -> dict[str, Any]:
    """在调用方短事务中保存一次来源绑定的结论；案例、回执和完成凭据一起提交

    回执不保存结论 JSON：来源摘要以 program_invocation_key（chapter:{章}:{digest}）
    冻结，sources/identity_mapping/support/issues 由正式贡献投影。
    """
    chapter_records = list(
        session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_4(chapter_id, run_id)
    )
    states = [
        SimpleNamespace(chapter_id=chapter_id, state="saved", role=str(record.role)) for record in chapter_records
    ]
    if chapter_id not in completed_chapters(states):
        raise ValueError(f"章末核对缺少必需角色的有效保存产物: chapter_id={chapter_id}")
    sources = [{"agent_id": str(record.agent_id), "output_id": str(record.record_id)} for record in chapter_records]
    digest = stable_digest(run_id, chapter_id, sources)
    previous = session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_2(chapter_id, run_id)
    if previous is not None:
        if previous.consolidation_digest == f"chapter:{chapter_id}:{digest}" and not recheck:
            return {"status": "existing", "chapter_id": chapter_id, "fact_id": digest}
        if previous.consolidation_digest != f"chapter:{chapter_id}:{digest}":
            raise ValueError(f"章末凭据与有效来源集合不同，不能覆盖: chapter_id={chapter_id}")
    repo = graph_projection(session.graph)
    boundary = repo.resolve_chapter_boundary(run_id, chapter_id=chapter_id)
    if boundary is None:
        raise ValueError(f"章末缺少正式章节边界: chapter_id={chapter_id}")
    projection = EntityReferenceProjection.load(session, run_id, boundary=boundary)
    chapters = {
        row.chapter_id: row.sequence
        for row in session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_12(run_id)
    }
    sequence = chapters[chapter_id]
    visible: dict[str, ChapterAnnotation] = {}
    for record in session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_3(run_id):
        if chapters.get(int(record.chapter_id), 0) <= sequence:
            visible[str(record.record_id)] = record
    valid_executions = {str(record.agent_id) for record in visible.values()}
    fact_rows = list(session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_5(valid_executions))
    fact_chapter: dict[str, int | None] = {}
    for _stored_row_2 in fact_rows:
        fact = _stored_row_2.GraphFact
        execution_chapter = _stored_row_2.chapter_id
        if fact.effective_chapter_id is not None:
            fact_chapter[str(fact.graph_fact_id)] = int(fact.effective_chapter_id)
        elif execution_chapter is not None:
            fact_chapter[str(fact.graph_fact_id)] = int(execution_chapter)
        else:
            fact_chapter[str(fact.graph_fact_id)] = None
    fact_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if fact_chapter:
        for evidence in session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_6(fact_chapter):
            fact_id = str(evidence.graph_fact_id)
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

    declarations = list(session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_7(records_by_record))
    declaration_chapter = {str(row.declaration_id): record_chapter(str(row.record_id)) for row in declarations}
    declaration_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    participants_by_declaration: dict[str, list[DeclarationParticipant]] = defaultdict(list)
    if declarations:
        declaration_ids = [str(row.declaration_id) for row in declarations]
        for evidence in session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_8(declaration_ids):
            declaration_evidence[str(evidence.declaration_id)].append(
                {
                    "chapter_id": declaration_chapter.get(str(evidence.declaration_id)),
                    "paragraph_id": int(evidence.paragraph_id),
                    "char_start": int(evidence.start_char),
                    "char_end": int(evidence.end_char),
                }
            )
        for participant in session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_9(declaration_ids):
            participants_by_declaration[str(participant.declaration_id)].append(participant)
    dialogues = list(session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_10(valid_executions))
    paragraph_rows = list(
        session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_11(chapter_id, run_id)
    )
    chapter_evidence = evidence_for(
        tuple(
            EvidenceParagraph(
                row.chapter_id, row.paragraph_id, row.text, row.local_start_char, row.local_start_char + len(row.text)
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
        fact_obj = fact.GraphFact
        if fact_obj.entity_id is None:
            continue
        entity_ids.add(str(fact_obj.entity_id))
        evidence_by_entity[str(fact_obj.entity_id)].extend(fact_evidence.get(str(fact_obj.graph_fact_id), []))
        if fact_chapter.get(str(fact_obj.graph_fact_id)) == chapter_id:
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
            for row in session.reads.agents_annotation_chapter_consolidation_consolidate_chapter_14(lookup_ids)
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
                    if str(fact.GraphFact.relation_id or "") == relation.relation_id
                    for item in fact_evidence.get(str(fact.GraphFact.graph_fact_id), [])
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
    referenced = {projection.resolution.resolve_entity_id(identifier) or identifier for identifier in referenced}
    for identifier in sorted(touched):
        representative = projection.resolution.resolve_entity_id(identifier) or identifier
        if representative not in referenced and identifier in projection.entities:
            entity = projection.entities[identifier]
            issue(identifier, entity.name, entity.entity_type, "unreferenced_entity", evidence_by_entity[identifier])
    import json

    from src.storage import new_id
    from src.storage.records.cases import CaseSave

    author = new_id()
    cases.begin(author)
    registered = [
        cases.register_case(case_type=kind, description=description, author=author)
        for kind, description in map(case_spec, issues)
    ]
    frozen_cases = CaseSave(
        run_id,
        None,
        json.dumps(
            {
                "created_case_ids": [item["case_id"] for item in registered],
                "registrations": {item["case_id"]: item for item in registered},
                "promises": [],
            },
            ensure_ascii=False,
        ),
    )
    return session.annotations.consolidate(
        {
            "recheck": recheck,
            "run_id": run_id,
            "chapter_id": chapter_id,
            "sources": sources,
            "program_code": PROGRAM_CODE,
            "program_key": f"chapter:{chapter_id}:{digest}",
            "digest": digest,
            "author": author,
            "cases": frozen_cases,
        }
    )
