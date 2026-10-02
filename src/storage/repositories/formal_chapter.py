"""章节正式结果的不可变提交和原文证据登记"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.agents.annotation.fact_graph import mention_uuid
from src.agents.annotation.identity import exact_digest, stable_digest, stable_uuid, text_digest
from src.agents.annotation.schema import AgentRunResult, SourceReference
from src.storage.models import (
    AgentWorkItem,
    CaseHead,
    Chapter,
    ChapterAnnotationRecord,
    ContinuityCase,
    FormalArtifact,
    Paragraph,
    ProjectionWorkItem,
    SemanticCommand,
    SourceManifest,
    TextEvidenceRecord,
)
from src.storage.repositories.pipeline_resolution import bind_case_target, bind_record_target
from src.storage.repositories.pipeline_work import (
    ImmutableWorkConflict,
    PipelineWorkRepository,
    WorkReceipt,
    append_outbox,
)


def _formal_commands(result: AgentRunResult) -> list[tuple[str, str, dict[str, Any], int | None]]:
    """模型输出转成稳定的局部命令；相同载荷的重复调用只保留一条"""
    commands: dict[str, tuple[str, str, dict[str, Any], int | None]] = {}
    for operation in result.entity_ops:
        name = str(operation["name"])
        payload = dict(operation)
        payload["entity_id"] = mention_uuid(result.run_id, result.chapter_id, name)
        key = stable_digest("entity_mention", name, payload, fold_text=True)
        commands[key] = ("entity_mention", f"entity:{payload['entity_id']}", payload, None)
    for operation in result.relation_assert_ops:
        payload = dict(operation)
        payload["from_entity_id"] = mention_uuid(result.run_id, result.chapter_id, operation["from_entity"])
        payload["to_entity_id"] = mention_uuid(result.run_id, result.chapter_id, operation["to_entity"])
        relation_key = stable_digest(
            payload["from_entity_id"], payload["to_entity_id"], operation["relation_type"], fold_text=True
        )
        key = stable_digest("local_relation", payload, fold_text=True)
        commands[key] = ("local_relation", f"relation:{relation_key}", payload, None)
    for event in result.annotation.events:
        payload = event.model_dump(mode="json")
        for participant in payload["participants"]:
            participant["entity_id"] = mention_uuid(result.run_id, result.chapter_id, participant["entity"])
        key = stable_digest("event", event.node_id, payload)
        commands[key] = ("event", f"event_tree:{event.tree_id}", payload, event.evidence_paragraph_id)
    for dialogue in result.annotation.dialogues:
        payload = dialogue.model_dump(mode="json")
        payload["speaker_entity_id"] = (
            mention_uuid(result.run_id, result.chapter_id, dialogue.speaker) if dialogue.speaker else None
        )
        key = stable_digest("dialogue", dialogue.candidate_key, payload)
        commands[key] = ("dialogue", f"dialogue:{dialogue.candidate_key}", payload, None)
    for observation in result.annotation.character_observations:
        payload = observation.model_dump(mode="json")
        payload["entity_id"] = mention_uuid(result.run_id, result.chapter_id, observation.character)
        key = stable_digest("character_observation", payload)
        commands[key] = ("character_observation", f"entity:{payload['entity_id']}",
                         payload, None)
    payload = result.annotation.metrics.model_dump(mode="json")
    key = stable_digest("chapter_metrics", payload)
    commands[key] = ("chapter_metrics", f"chapter:{result.chapter_id}", payload, None)
    for label in result.annotation.paragraph_labels:
        payload = label.model_dump(mode="json")
        key = stable_digest("paragraph_label", payload)
        commands[key] = ("paragraph_label", f"paragraph:{label.paragraph_id}", payload, label.paragraph_id)
    for record, references in result.audit.source_anchors.items():
        target = bind_record_target(record, result)
        for reference in references:
            payload = {"object": target, "source": reference.model_dump(mode="json")}
            key = stable_digest("object_anchor", payload)
            commands[key] = ("object_anchor", f"anchor:{key}", payload, None)
    for link in result.cross_chapter_links:
        if link.source.chapter_id != result.chapter_id or (
            link.source not in result.audit.source_anchors.get(link.record_id, [])
        ):
            raise ValueError("跨章关联必须绑定本章已登记的对象与原文")
        payload = {**link.model_dump(mode="json"), "source_object": bind_record_target(link.record_id, result)}
        key = stable_digest("cross_chapter_link", payload)
        commands[key] = ("cross_chapter_link", f"link:{key}", payload, None)
    return [commands[key] for key in sorted(commands)]


class FormalChapterRepository:
    """正式章节和其派生命令在一条短事务中提交，失败不留下半个章节"""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory
        self._source_paragraph_hashes: dict[str, tuple[str, dict[str, str]]] = {}

    def _paragraph_hashes(self, session: Session, source_hash: str, run_id: str) -> dict[str, str]:
        """不可变 manifest 每个 Worker 只装载一次，避免逐章传输全书哈希形成平方开销"""
        if source_hash not in self._source_paragraph_hashes:
            row = session.execute(select(SourceManifest.run_id, SourceManifest.paragraph_hashes).where(
                SourceManifest.source_manifest_hash == source_hash,
            )).one_or_none()
            if row is None:
                raise ValueError("正式工作没有匹配的原文快照")
            self._source_paragraph_hashes[source_hash] = row.run_id, dict(row.paragraph_hashes)
        source_run, hashes = self._source_paragraph_hashes[source_hash]
        if source_run != run_id:
            raise ValueError("正式工作原文快照不属于本 run")
        return hashes

    def commit(self, receipt: WorkReceipt, result: AgentRunResult) -> str:
        """校验来源和租约后提交；既有不同 payload 触发不可变冲突"""
        if receipt.work_kind != "formal_current" or result.run_id != receipt.run_id:
            raise ValueError("正式工作回执与结果不匹配")
        chapter_id = int(receipt.payload["chapter_id"])
        if result.chapter_id != chapter_id:
            raise ValueError("正式结果的 chapter_id 与工作输入不一致")
        expected_source_hash = str(receipt.payload["source_manifest_hash"])
        if expected_source_hash != receipt.cutoff_hash:
            raise ValueError("工作来源 manifest 与 cutoff 不一致")
        result_hash = exact_digest(result.model_dump(mode="json"))
        annotation_id = stable_uuid(receipt.run_id, chapter_id, expected_source_hash)

        with self.session_factory() as session, session.begin():
            submitted = session.get(AgentWorkItem, receipt.work_id)
            if submitted is not None and submitted.state == "submitted":
                existing = session.get(ChapterAnnotationRecord, annotation_id)
                if (existing is None or existing.payload_hash != result_hash
                        or existing.formal_work_id != receipt.work_id):
                    raise ImmutableWorkConflict(f"正式章节重投递载荷冲突: chapter_id={chapter_id}")
                return existing.annotation_id
            PipelineWorkRepository.lock_owned_work(session, receipt)
            chapter = session.get(Chapter, (chapter_id, receipt.run_id))
            if chapter is None or chapter.text is None:
                raise ValueError(f"正式来源章节不存在: chapter_id={chapter_id}")
            if text_digest(chapter.text) != receipt.payload["chapter_text_hash"]:
                raise ImmutableWorkConflict(f"正式章节正文在工作期间发生变化: chapter_id={chapter_id}")

            current = list(
                session.execute(
                    select(Paragraph)
                    .where(Paragraph.run_id == receipt.run_id, Paragraph.chapter_id == chapter_id)
                    .order_by(Paragraph.paragraph_index)
                ).scalars()
            )
            if not current:
                raise ValueError(f"正式章节没有原文段落: chapter_id={chapter_id}")
            paragraph_manifest = [
                (row.paragraph_id, row.local_start_char, row.local_end_char, text_digest(row.text))
                for row in current
            ]
            if stable_digest(paragraph_manifest) != receipt.payload["paragraph_manifest_hash"]:
                raise ImmutableWorkConflict(f"正式章节段落在工作期间发生变化: chapter_id={chapter_id}")

            existing = session.execute(
                select(ChapterAnnotationRecord).where(
                    ChapterAnnotationRecord.run_id == receipt.run_id,
                    ChapterAnnotationRecord.chapter_id == chapter_id,
                ).with_for_update()
            ).scalar_one_or_none()
            if existing is not None:
                if (
                    existing.payload_hash != result_hash
                    or existing.source_manifest_hash != expected_source_hash
                    or existing.formal_work_id != receipt.work_id
                ):
                    raise ImmutableWorkConflict(f"正式章节不可变冲突: chapter_id={chapter_id}")
                PipelineWorkRepository.mark_submitted(session, receipt)
                return existing.annotation_id

            source_ids = {row.paragraph_id for row in current}
            source_ids.update(result.audit.authorized_text_paragraph_ids)
            paragraphs = list(
                session.execute(
                    select(Paragraph).where(
                        Paragraph.run_id == receipt.run_id,
                        Paragraph.paragraph_id.in_(sorted(source_ids)),
                    )
                    .order_by(Paragraph.paragraph_id)
                ).scalars()
            )
            if {row.paragraph_id for row in paragraphs} != source_ids:
                raise ValueError("正式结果引用的原文段落不存在")
            expected_paragraphs = self._paragraph_hashes(session, expected_source_hash, receipt.run_id)
            for row in paragraphs:
                expected_hash = expected_paragraphs.get(str(row.paragraph_id))
                if expected_hash != text_digest(row.text):
                    raise ImmutableWorkConflict(f"原文证据已变化: paragraph_id={row.paragraph_id}")
            evidence_by_paragraph: dict[int, str] = {}
            for row in paragraphs:
                if not row.text:
                    raise ValueError(f"空原文不能登记 TextEvidence: paragraph_id={row.paragraph_id}")
                evidence_id = stable_digest(
                    receipt.run_id, row.paragraph_id, 0, len(row.text), expected_source_hash
                )
                evidence_by_paragraph[row.paragraph_id] = evidence_id
                session.execute(
                    insert(TextEvidenceRecord).values(
                        evidence_id=evidence_id,
                        run_id=receipt.run_id,
                        chapter_id=row.chapter_id,
                        paragraph_id=row.paragraph_id,
                        char_start=0,
                        char_end=len(row.text),
                        text_hash=text_digest(row.text),
                        source_manifest_hash=expected_source_hash,
                    ).on_conflict_do_nothing(index_elements=[TextEvidenceRecord.evidence_id])
                )
            paragraph_by_id = {row.paragraph_id: row for row in paragraphs}

            def exact_evidence(reference: SourceReference) -> str:
                """精确区间必须已实际读取，且仍属于同一原文快照"""
                row = paragraph_by_id.get(reference.paragraph_id)
                if row is None or row.chapter_id != reference.chapter_id:
                    raise ValueError("精确原文引用不属于已授权段落")
                if not 0 <= reference.char_start < reference.char_end <= len(row.text):
                    raise ValueError("精确原文引用超出段落")
                if text_digest(row.text[reference.char_start:reference.char_end]) != reference.text_hash:
                    raise ValueError("精确原文引用哈希不匹配")
                identifier = stable_digest(receipt.run_id, reference.paragraph_id,
                                           reference.char_start, reference.char_end, expected_source_hash)
                session.execute(insert(TextEvidenceRecord).values(
                    evidence_id=identifier, run_id=receipt.run_id, chapter_id=row.chapter_id,
                    paragraph_id=row.paragraph_id, char_start=reference.char_start, char_end=reference.char_end,
                    text_hash=reference.text_hash, source_manifest_hash=expected_source_hash,
                ).on_conflict_do_nothing(index_elements=[TextEvidenceRecord.evidence_id]))
                return identifier

            for references in result.audit.source_anchors.values():
                for reference in references:
                    if reference.chapter_id != chapter_id:
                        raise ValueError("对象原文锚点只能属于本章")
                    exact_evidence(reference)
            current_evidence = [evidence_by_paragraph[row.paragraph_id] for row in current]
            if not current_evidence:
                raise ValueError("正式章节必须包含本章原文证据")
            other_evidence = [
                evidence_by_paragraph[row.paragraph_id] for row in paragraphs if row.chapter_id != chapter_id
            ]
            all_evidence = sorted({*current_evidence, *other_evidence})

            session.add(
                ChapterAnnotationRecord(
                    annotation_id=annotation_id,
                    run_id=receipt.run_id,
                    chapter_id=chapter_id,
                    payload=result.annotation.model_dump(mode="json"),
                    formal_work_id=receipt.work_id,
                    payload_hash=result_hash,
                    source_manifest_hash=expected_source_hash,
                )
            )
            session.flush()
            session.add(FormalArtifact(annotation_id=annotation_id, result=result.model_dump(mode="json")))
            sequence = int(receipt.payload["chapter_sequence"])
            projections: list[ProjectionWorkItem] = []
            for kind, partition, payload, anchor_id in _formal_commands(result):
                if anchor_id is not None and anchor_id not in {row.paragraph_id for row in current}:
                    raise ValueError("正式事件和段落标签必须锚定本章原文")
                if anchor_id is not None and anchor_id not in evidence_by_paragraph:
                    raise ValueError(f"事件证据段落未授权: paragraph_id={anchor_id}")
                if kind == "object_anchor":
                    command_evidence = [exact_evidence(SourceReference.model_validate(payload["source"]))]
                elif kind == "cross_chapter_link":
                    command_evidence = [exact_evidence(SourceReference.model_validate(payload[field]))
                                        for field in ("source", "target")]
                else:
                    command_evidence = (
                        [evidence_by_paragraph[anchor_id], *other_evidence]
                        if anchor_id is not None else all_evidence
                    )
                payload_hash = stable_digest(payload)
                command_path = stable_digest(kind, partition, payload_hash)
                command_id = stable_digest(receipt.work_id, command_path, payload_hash)
                session.add(
                    SemanticCommand(
                        command_id=command_id,
                        run_id=receipt.run_id,
                        origin_annotation_id=annotation_id,
                        origin_chapter_id=chapter_id,
                        origin_chapter_sequence=sequence,
                        command_path=command_path,
                        command_kind=kind,
                        partition_key=partition,
                        effective_document_position={"chapter_sequence": sequence, "paragraph_id": anchor_id},
                        payload=payload,
                        payload_hash=payload_hash,
                        evidence_ids=sorted(set(command_evidence)),
                        independence_keys=[f"chapter:{chapter_id}"],
                        author_work_id=receipt.work_id,
                    )
                )
                projections.append(
                    ProjectionWorkItem(
                        projection_id=stable_digest(command_id, partition),
                        run_id=receipt.run_id,
                        command_id=command_id,
                        partition_key=partition,
                    )
                )
            session.flush()
            session.add_all(projections)

            for seed in result.pushed_cases:
                if seed.chapter_id != chapter_id:
                    raise ValueError("CaseSeed 必须归属当前正式章节")
                case_key = stable_digest(receipt.run_id, seed.type, seed.target_ref, fold_text=True)
                if seed.target_key != case_key:
                    raise ValueError("CaseSeed 稳定键与目标不一致")
                case_id = case_key
                target = bind_case_target(seed, result)
                inserted_case = session.execute(
                    insert(ContinuityCase)
                    .values(
                        case_id=case_id,
                        run_id=receipt.run_id,
                        case_key=case_key,
                        issue_kind=seed.type,
                        description=seed.description,
                        search_keys=list(seed.keys),
                        target_ref=target,
                        source_evidence=sorted({exact_evidence(SourceReference.model_validate(value))
                                                for value in seed.target_ref.get("source_refs", [])}) or all_evidence,
                        originating_annotation_id=annotation_id,
                        originating_chapter_id=chapter_id,
                    )
                    .on_conflict_do_nothing(index_elements=[ContinuityCase.case_id])
                    .returning(ContinuityCase.case_id)
                ).scalar_one_or_none()
                prior = session.get(ContinuityCase, case_id)
                if prior is None or prior.target_ref != target or prior.issue_kind != seed.type:
                    raise ImmutableWorkConflict(f"CaseSeed 目标冲突: case_id={case_id}")
                if inserted_case is not None:
                    session.flush()
                    session.add(CaseHead(case_id=case_id, state_hash=stable_digest("pending", case_key)))

            PipelineWorkRepository.mark_submitted(session, receipt)
            append_outbox(
                session,
                run_id=receipt.run_id,
                work_id=receipt.work_id,
                attempt_epoch=receipt.attempt_epoch,
                chapter_id=chapter_id,
                event_type="formal_chapter_committed",
                payload={"annotation_id": annotation_id, "payload_hash": result_hash},
                cutoff_hash=receipt.cutoff_hash,
            )
        return annotation_id
