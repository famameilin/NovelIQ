"标注、对话与事件原始记录查询，不判定角色完成或解释领域状态"

from __future__ import annotations

from sqlalchemy import Select, func, or_, select

from src.storage.models import (
    Agent,
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    DialogueRecord,
    EventParticipant,
    GraphEntity,
    GraphFact,
    NarrativeLink,
    Paragraph,
    SourceEvidence,
)
from src.storage.records.annotation import AnnotationRoleRecord as AnnotationRoleRecord
from src.storage.records.annotation import ChapterAnnotationRow as ChapterAnnotationRow
from src.storage.records.annotation import CharacterFactRow as CharacterFactRow
from src.storage.records.annotation import DialogueFactRow as DialogueFactRow
from src.storage.records.annotation import DialogueRecordRow as DialogueRecordRow
from src.storage.records.annotation import ForeshadowingEdgeRow as ForeshadowingEdgeRow
from src.storage.records.annotation import ForeshadowingTreeView as ForeshadowingTreeView
from src.storage.records.annotation import GraphFactRow as GraphFactRow
from src.storage.records.annotation import SavedAnnotationRecord as SavedAnnotationRecord
from src.storage.repositories.base import BaseRepository

#: graph_facts 封闭形状与旧内容类型的映射（目录穷举，不接受任意类别名）
FACT_SHAPE_BY_CONTENT_KIND = {
    "entity": "entity",
    "relation": "relation",
    "character_observation": "participant",
    "plotline": "plotline",
    "program_check": "program",
}


class AnnotationRepository(BaseRepository[ChapterAnnotation]):
    def fetch_chapter_sequence_map(self, run_id: str) -> dict[int, int]:
        rows = self.session.execute(select(Chapter.chapter_id, Chapter.sequence).where(Chapter.run_id == run_id)).all()
        return {int(row.chapter_id): int(row.sequence) for row in rows}

    def fetch_chapter_ids(self, run_id: str) -> set[int]:
        return set(self.session.scalars(select(Chapter.chapter_id).where(Chapter.run_id == run_id).distinct()))

    def run_execution_ids(self, run_id: str) -> Select:
        "本运行的真实执行：整轮 session 行与直接携带 run 的调用行"
        return select(Agent.id).where(or_(Agent.run_id == run_id, Agent.run_id == run_id))

    def fetch_saved_outputs(self, run_id: str) -> list[SavedAnnotationRecord]:
        "本运行已正式保存的章节标注：行存在即保存事实，章号/角色取记录自身列"
        statement = (
            select(ChapterAnnotation)
            .where(ChapterAnnotation.run_id == run_id)
            .order_by(ChapterAnnotation.chapter_id, ChapterAnnotation.role, ChapterAnnotation.record_id)
        )
        return [
            SavedAnnotationRecord(
                record_id=str(annotation.record_id),
                chapter_id=int(annotation.chapter_id),
                role=str(annotation.role) if annotation.role is not None else None,
                agent_id=str(annotation.agent_id),
                # 结构/事件角色没有章级指标时各列为空：按模型可空合同原样投影，不强行转型
                summary=None if annotation.summary is None else str(annotation.summary),
                emotional_valence=None if annotation.emotional_valence is None else int(annotation.emotional_valence),
                narrative_function=None
                if annotation.narrative_function is None
                else str(annotation.narrative_function),
                pivot_moment=None if annotation.pivot_moment is None else bool(annotation.pivot_moment),
                cliffhanger=None if annotation.cliffhanger is None else bool(annotation.cliffhanger),
                created_at=annotation.created_at,
                saved_at=annotation.saved_at,
            )
            for annotation in self.session.scalars(statement)
        ]

    def fetch_role_records(self, run_id: str) -> list[AnnotationRoleRecord]:
        "本运行的章内标注角色：state 由正式标注记录的存在性表达，执行号取产物行自身"
        rows = self.session.execute(
            select(ChapterAnnotation)
            .where(ChapterAnnotation.run_id == run_id, ChapterAnnotation.role.is_not(None))
            .order_by(ChapterAnnotation.chapter_id, ChapterAnnotation.role, ChapterAnnotation.record_id)
        ).scalars()
        return [
            AnnotationRoleRecord(
                run_id=run_id,
                chapter_id=int(row.chapter_id),
                role=str(row.role),
                invocation_id=str(row.agent_id),
                state="saved",
                saved_at=row.saved_at,
            )
            for row in rows
        ]

    def fetch_entities_by_id(self, run_id: str) -> dict[str, GraphEntity]:
        return {
            str(row.entity_id): row
            for row in self.session.scalars(select(GraphEntity).where(GraphEntity.run_id == run_id))
        }

    def fetch_dialogue_records(self, run_id: str) -> list[DialogueRecordRow]:
        "本运行对话记录：run/章是创建时自落归属，内容按章节区间精确切片"
        statement = (
            select(
                DialogueRecord,
                Chapter.sequence.label("chapter_sequence"),
                func.substr(
                    Chapter.text,
                    DialogueRecord.start_char + 1,
                    DialogueRecord.end_char - DialogueRecord.start_char,
                ).label("content"),
            )
            .join(
                Chapter,
                (Chapter.run_id == DialogueRecord.run_id) & (Chapter.chapter_id == DialogueRecord.chapter_id),
            )
            .where(DialogueRecord.run_id == run_id)
            .order_by(
                Chapter.sequence,
                DialogueRecord.chapter_id,
                DialogueRecord.start_char,
                DialogueRecord.dialogue_id,
            )
        )
        return [
            DialogueRecordRow(
                dialogue_id=str(record.dialogue_id),
                chapter_id=int(record.chapter_id),
                candidate_key=str(record.candidate_key),
                start_char=int(record.start_char),
                end_char=int(record.end_char),
                content="" if content is None else str(content),
                speaker_entity_id=str(record.speaker_entity_id) if record.speaker_entity_id is not None else None,
                tone=str(record.tone) if record.tone is not None else None,
                is_inner_monologue=bool(record.is_inner_monologue),
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record, _sequence, content in self.session.execute(statement).all()
        ]

    def _annotation_event_statement(self, run_id: str) -> Select:
        "本运行的章级事件：记录自身带运行归属（agent_annotations.run_id）"
        return (
            select(CompleteEvent)
            .join(ChapterAnnotation, ChapterAnnotation.record_id == CompleteEvent.annotation_record_id)
            .where(ChapterAnnotation.run_id == run_id)
        )

    def fetch_foreshadowing_roots(self, run_id: str, *, ordered: bool = False) -> list[CompleteEvent]:
        statement = self._annotation_event_statement(run_id).where(CompleteEvent.is_foreshadowing_root.is_(True))
        if ordered:
            statement = statement.join(
                Chapter,
                (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id),
            ).order_by(Chapter.sequence, CompleteEvent.event_id)
        else:
            statement = statement.order_by(CompleteEvent.event_id)
        return list(self.session.scalars(statement))

    def _semantic_foreshadowing_links(self, run_id: str) -> list[NarrativeLink]:
        "本运行的伏笔语义链路：两端都是完整事件，真实生产者取本运行执行"
        return list(
            self.session.scalars(
                select(NarrativeLink)
                .where(
                    NarrativeLink.producer_agent_id.in_(self.run_execution_ids(run_id)),
                    NarrativeLink.relation_type == "foreshadowing",
                    NarrativeLink.semantic_source_event_id.is_not(None),
                    NarrativeLink.semantic_target_event_id.is_not(None),
                )
                .order_by(NarrativeLink.link_id)
            )
        )

    def _event_chapter_ids(self, run_id: str, event_ids: set[str]) -> dict[str, int]:
        "完整事件的来源章：由该事件自身证据的段落所属章节投影（最早章序为定位章）"
        if not event_ids:
            return {}
        statement = (
            select(SourceEvidence.complete_event_id, Chapter.chapter_id, Chapter.sequence)
            .join(Paragraph, (Paragraph.run_id == run_id) & (Paragraph.paragraph_id == SourceEvidence.paragraph_id))
            .join(Chapter, (Chapter.run_id == run_id) & (Chapter.chapter_id == Paragraph.chapter_id))
            .where(SourceEvidence.complete_event_id.in_(list(event_ids)))
        )
        best: dict[str, tuple[int, int]] = {}
        for event_id, chapter_id, sequence in self.session.execute(statement).all():
            key = str(event_id)
            current = best.get(key)
            if current is None or int(sequence) < current[0]:
                best[key] = (int(sequence), int(chapter_id))
        return {event_id: value[1] for event_id, value in best.items()}

    def fetch_foreshadowing_edges(self, run_id: str, *, ordered: bool = False) -> list[ForeshadowingEdgeRow]:
        "伏笔语义链路读投影；ordered 时按目标事件来源章序排序（无证据章的链路排后）"
        links = self._semantic_foreshadowing_links(run_id)
        event_ids = {str(row.semantic_source_event_id) for row in links} | {
            str(row.semantic_target_event_id) for row in links
        }
        chapter_ids = self._event_chapter_ids(run_id, event_ids)
        rows = [
            ForeshadowingEdgeRow(
                edge_id=str(link.link_id),
                edge_type="foreshadowing",
                source_event_id=str(link.semantic_source_event_id),
                target_event_id=str(link.semantic_target_event_id),
                source_chapter_id=chapter_ids.get(str(link.semantic_source_event_id)),
                target_chapter_id=chapter_ids.get(str(link.semantic_target_event_id)),
                is_active=None if link.is_active is None else bool(link.is_active),
                expired_at=link.expired_at,
            )
            for link in links
        ]
        if ordered:
            sequence_map = self.fetch_chapter_sequence_map(run_id)
            rows.sort(
                key=lambda row: (
                    sequence_map.get(row.target_chapter_id, 0) if row.target_chapter_id is not None else 0,
                    row.edge_id,
                )
            )
        return rows

    def fetch_event_records(self, run_id: str, event_ids: set[str]) -> list[CompleteEvent]:
        if not event_ids:
            return []
        return list(
            self.session.scalars(
                self._annotation_event_statement(run_id)
                .where(CompleteEvent.event_id.in_(event_ids))
                .order_by(CompleteEvent.event_id)
            )
        )

    def fetch_foreshadowing_edge_counts(self, run_id: str) -> dict[str, int]:
        statement = (
            select(NarrativeLink.semantic_source_event_id, func.count().label("edge_count"))
            .where(
                NarrativeLink.producer_agent_id.in_(self.run_execution_ids(run_id)),
                NarrativeLink.relation_type == "foreshadowing",
                NarrativeLink.semantic_source_event_id.is_not(None),
            )
            .group_by(NarrativeLink.semantic_source_event_id)
        )
        return {str(row.semantic_source_event_id): int(row.edge_count) for row in self.session.execute(statement)}

    def _fact_chapter_projection(self, run_id: str):
        "事实所属章节：写入时自落的有效章节列（领域读不推导、不回退 AUDIT 表）"
        return GraphFact.effective_chapter_id

    def fetch_graph_facts(self, run_id: str, *, content_kind: str) -> list[GraphFactRow]:
        "本运行指定形状的正式图贡献事实（旧内容类型名映射到冻结形状列）"
        shape = FACT_SHAPE_BY_CONTENT_KIND.get(content_kind)
        if shape is None:
            raise ValueError(f"未知的图事实内容类型: {content_kind}")
        if shape == "entity":
            shape_filter = GraphFact.entity_id.is_not(None)
            producer_filter = GraphFact.direct_producer_agent_id.in_(self.run_execution_ids(run_id))
        elif shape == "relation":
            shape_filter = GraphFact.relation_id.is_not(None)
            producer_filter = GraphFact.direct_producer_agent_id.in_(self.run_execution_ids(run_id))
        elif shape == "plotline":
            shape_filter = GraphFact.plotline_subject_id.is_not(None)
            producer_filter = GraphFact.direct_producer_agent_id.in_(self.run_execution_ids(run_id))
        elif shape == "participant":
            shape_filter = GraphFact.participant_id.is_not(None)
            producer_filter = GraphFact.participant_id.in_(
                select(EventParticipant.participant_id).where(
                    EventParticipant.event_id.in_(self._run_annotation_event_ids(run_id))
                )
            )
        else:
            raise ValueError(f"图事实形状 {shape} 尚无读取实现")
        statement = (
            select(
                GraphFact,
                self._fact_chapter_projection(run_id).label("chapter_id"),
                Chapter.sequence.label("chapter_sequence"),
            )
            .join(
                Chapter,
                (Chapter.run_id == run_id) & (Chapter.chapter_id == self._fact_chapter_projection(run_id)),
                isouter=True,
            )
            .where(shape_filter, producer_filter)
            .order_by(Chapter.sequence, GraphFact.operation_order, GraphFact.graph_fact_id)
        )
        rows = [
            GraphFactRow(
                fact=fact,
                chapter_id=None if chapter_id is None else int(chapter_id),
                operation_order=None if fact.operation_order is None else int(fact.operation_order),
            )
            for fact, chapter_id, _sequence in self.session.execute(statement).all()
        ]
        if shape == "participant":
            return self._attach_participant_observations(run_id, rows)
        return rows

    def _run_annotation_event_ids(self, run_id: str):
        "本运行章级事件的 id 选择器（记录自身带运行归属）"
        return (
            select(CompleteEvent.event_id)
            .join(ChapterAnnotation, ChapterAnnotation.record_id == CompleteEvent.annotation_record_id)
            .where(ChapterAnnotation.run_id == run_id)
        )

    def _attach_participant_observations(self, run_id: str, rows: list[GraphFactRow]) -> list[GraphFactRow]:
        "人物动态观测：实体/角色/动作/情绪从事件的参与者行读取（不复制三态值）"
        participant_ids = [row.fact.participant_id for row in rows if row.fact.participant_id is not None]
        if not participant_ids:
            return rows
        participant_statement = (
            select(
                EventParticipant.participant_id,
                EventParticipant.entity_id,
                GraphEntity.canonical_name,
                GraphEntity.entity_type,
                EventParticipant.role,
                EventParticipant.narrative_role,
                EventParticipant.action,
                EventParticipant.emotion,
            )
            .join(GraphEntity, GraphEntity.entity_id == EventParticipant.entity_id)
            .where(EventParticipant.participant_id.in_(participant_ids))
        )
        participants = {str(row.participant_id): row for row in self.session.execute(participant_statement).all()}
        chapter_by_participant = self._participant_chapter_ids(run_id, set(participants))
        result: list[GraphFactRow] = []
        for row in rows:
            participant = participants.get(str(row.fact.participant_id))
            if participant is None:
                result.append(row)
                continue
            result.append(
                GraphFactRow(
                    fact=row.fact,
                    chapter_id=chapter_by_participant.get(str(row.fact.participant_id), row.chapter_id),
                    operation_order=row.operation_order,
                    participant_entity_id=str(participant.entity_id),
                    participant_entity_name=str(participant.canonical_name),
                    participant_entity_type=str(participant.entity_type),
                    participant_role=str(participant.role),
                    participant_narrative_role=(
                        str(participant.narrative_role) if participant.narrative_role is not None else None
                    ),
                    participant_action=str(participant.action) if participant.action is not None else None,
                    participant_emotion=(int(participant.emotion) if participant.emotion is not None else None),
                )
            )
        return result

    def _participant_chapter_ids(self, run_id: str, participant_ids: set[str]) -> dict[str, int]:
        "参与者所属章节：事件→来源记录（记录自身带运行归属），不按当前章替代"
        if not participant_ids:
            return {}
        statement = (
            select(EventParticipant.participant_id, ChapterAnnotation.chapter_id)
            .join(CompleteEvent, CompleteEvent.event_id == EventParticipant.event_id)
            .join(ChapterAnnotation, ChapterAnnotation.record_id == CompleteEvent.annotation_record_id)
            .where(
                EventParticipant.participant_id.in_(list(participant_ids)),
                ChapterAnnotation.run_id == run_id,
            )
        )
        return {
            str(participant_id): int(chapter_id)
            for participant_id, chapter_id in self.session.execute(statement).all()
            if chapter_id is not None
        }
