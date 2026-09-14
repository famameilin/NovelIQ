"""
章节标注最新读侧仓储门面
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import func, select

from src.agents.annotation.schema import BoundChapterAnnotation
from src.models.local.character_reference_policy import is_global_character_surface_name
from src.storage.models import (
    Chapter,
    ChapterAnnotationRecord,
    DialogueRecord,
    EventEdge,
    EventNode,
    GraphFact,
)
from src.storage.repositories.base import BaseRepository

# 2026-09-14 伏笔 confidence 并轨三档（high/medium/low 等差基分），PayoffLikelihood 二值枚举退役
_EXPECTATION_BASE_SCORE_BY_PAYOFF = {"high": 0.62, "medium": 0.38, "low": 0.14}
_EXPECTATION_STATUS_BONUS = {"open": -0.07, "reinforced": 0.03, "likely_paid_off": 0.28}
_EXPECTATION_STRENGTH_BONUS = {"high": 0.03, "medium": 0.0, "low": -0.05}
_EXPECTATION_STATUS_WEIGHT = {"open": 0.75, "reinforced": 1.0, "likely_paid_off": 1.2}
_EXPECTATION_STRENGTH_WEIGHT = {"high": 0.05, "medium": 0.0, "low": -0.05}


@dataclass(frozen=True)
class ChapterAnnotationRow:
    """2026-08-05 用于向 章节消费者暴露章节 segment 的具名读模型"""

    chapter_id: int
    emotional_valence: int
    event_type: str
    pivot_moment: bool
    cliffhanger: bool
    has_foreshadowing: bool | None = None
    is_strong_setup: bool | None = None
    foreshadowing_desc: str | None = None
    why_unresolved_now: str | None = None
    payoff_likelihood: str | None = None
    # 2026-09-13 伏笔入森林：非埋设章挂树时指向伏笔树根（埋设事件 id）
    foreshadowing_root_event_id: str | None = None
    # 2026-09-05 A1：冻结时系统覆盖告警（旧 payload 无此字段时为空）
    coverage_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CharacterFactRow:
    """2026-08-05 用于向人物与聚合消费者暴露数据库图人物事实"""

    chapter_id: int
    name: str
    surface_name: str
    reference_kind: str
    reference_slot: str | None
    resolved_global_name: str
    global_skip_reason: str | None
    role_function: str
    action: str
    emotion_score: str


@dataclass(frozen=True)
class DialogueFactRow:
    """2026-08-05 用于向对话与情绪融合消费者暴露数据库图对话事实"""

    chapter_id: int
    speaker: list[str]
    speaker_references: list[dict[str, Any]]
    length: int
    tone: str | None


@dataclass(frozen=True)
class ForeshadowingTreeView:
    """2026-09-13 用于向 API 与诊断暴露伏笔树汇总视图（伏笔即事件树）"""

    root_event_id: str
    tree_id: str
    first_chapter_id: int
    last_chapter_id: int
    anchor_chapter_ids: list[int]
    description: str
    payoff_likelihood: str | None
    strength: str | None
    status: str
    active: bool
    latest_reason: str | None
    latest_why_unresolved_now: str | None


class AnnotationRepository(BaseRepository[ChapterAnnotationRecord]):
    """2026-08-05 用于统一读取章节正式标注与数据库图事实"""

    def _chapter_sequence_map(self, run_id: str) -> dict[int, int]:
        """2026-08-19 用于把稳定 chapter_id 映射为历史展示顺序"""
        rows = self.session.execute(select(Chapter.chapter_id, Chapter.sequence).where(Chapter.run_id == run_id)).all()
        return {int(row.chapter_id): int(row.sequence) for row in rows}

    def _chapter_annotations(self, run_id: str) -> list[ChapterAnnotationRecord]:
        """2026-08-05 用于按真实章节顺序读取全部正式章节标注"""
        stmt = (
            select(ChapterAnnotationRecord)
            .join(
                Chapter,
                (Chapter.run_id == ChapterAnnotationRecord.run_id)
                & (Chapter.chapter_id == ChapterAnnotationRecord.chapter_id),
            )
            .where(ChapterAnnotationRecord.run_id == run_id)
            .order_by(Chapter.sequence, ChapterAnnotationRecord.chapter_id)
        )
        return list(self.session.execute(stmt).scalars().all())

    def _graph_facts(self, run_id: str, *, content_kind: str) -> list[GraphFact]:
        """2026-08-19 用于读取指定类型的章节事实"""
        stmt = (
            select(GraphFact)
            .join(
                Chapter,
                (Chapter.run_id == GraphFact.run_id) & (Chapter.chapter_id == GraphFact.chapter_id),
            )
            .where(
                GraphFact.run_id == run_id,
                GraphFact.source_kind == "annotation",
            )
            .order_by(Chapter.sequence, GraphFact.chapter_id, GraphFact.graph_fact_id)
        )
        rows = self.session.execute(stmt).scalars().all()
        sequence_map = self._chapter_sequence_map(run_id)
        return sorted(
            (row for row in rows if isinstance(row.content, dict) and row.content.get("kind") == content_kind),
            key=lambda row: (sequence_map.get(row.effective_chapter_id, row.effective_chapter_id), row.graph_fact_id),
        )

    def _foreshadowing_by_chapter(self, run_id: str) -> dict[int, dict[str, Any]]:
        """2026-09-13 用于把伏笔树（根事件 + foreshadowing 挂边）展开到实际命中章节

        埋设章 linked 为 None（该章就是根所在）；后续挂边章 linked 指向树根事件 id。
        """
        roots = list(
            self.session.execute(
                select(EventNode).where(
                    EventNode.run_id == run_id,
                    EventNode.is_foreshadowing_root.is_(True),
                )
            ).scalars()
        )
        if not roots:
            return {}
        root_by_id = {root.event_id: root for root in roots}
        sequence_map = self._chapter_sequence_map(run_id)

        def _entry(root: EventNode, *, linked: str | None) -> dict[str, Any]:
            return {
                "has_foreshadowing": True,
                "is_strong_setup": (root.strength == "high") if root.strength is not None else None,
                "foreshadowing_desc": root.description,
                "why_unresolved_now": None,
                "payoff_likelihood": root.payoff_likelihood,
                "foreshadowing_root_event_id": linked,
            }

        by_chapter: dict[int, dict[str, Any]] = {}
        for root in sorted(roots, key=lambda r: (sequence_map.get(r.chapter_id, r.chapter_id), r.event_id)):
            by_chapter[root.chapter_id] = _entry(root, linked=None)
        edges = list(
            self.session.execute(
                select(EventEdge).where(
                    EventEdge.run_id == run_id,
                    EventEdge.edge_type == "foreshadowing",
                    EventEdge.is_active.is_(True),
                )
            ).scalars()
        )
        for edge in sorted(
            edges,
            key=lambda e: (sequence_map.get(e.target_chapter_id, e.target_chapter_id), e.edge_id),
        ):
            root_node = root_by_id.get(edge.source_event_id)
            if root_node is None:
                continue
            by_chapter[edge.target_chapter_id] = _entry(root_node, linked=root_node.event_id)
        return by_chapter

    def fetch_chapter_annotations(self, run_id: str) -> list[ChapterAnnotationRow]:
        """2026-08-05 用于读取聚合张力所需的章节 segment 标注"""
        return self.fetch_chapter_annotations_full(run_id)

    def fetch_chapter_annotations_full(self, run_id: str) -> list[ChapterAnnotationRow]:
        """2026-08-07 用于从最新系统绑定 payload 展开完整章节标注"""
        foreshadowing_by_chapter = self._foreshadowing_by_chapter(run_id)
        rows: list[ChapterAnnotationRow] = []
        for record in self._chapter_annotations(run_id):
            annotation = BoundChapterAnnotation.model_validate(record.payload)
            for chunk in annotation.chunks:
                rows.append(
                    ChapterAnnotationRow(
                        chapter_id=chunk.chunk_id,
                        emotional_valence=chunk.metrics.emotional_valence,
                        event_type=chunk.metrics.narrative_function,
                        pivot_moment=chunk.metrics.pivot_moment,
                        cliffhanger=chunk.metrics.cliffhanger,
                        coverage_warnings=list(chunk.coverage_warnings),
                        **foreshadowing_by_chapter.get(chunk.chunk_id, {}),
                    )
                )
        sequence_map = self._chapter_sequence_map(run_id)
        return sorted(rows, key=lambda row: (sequence_map.get(row.chapter_id, row.chapter_id), row.chapter_id))

    def fetch_full_annotations(self, run_id: str) -> list[ChapterAnnotationRow]:
        """2026-08-05 用于读取指标计算所需的完整章节标注字段"""
        return self.fetch_chapter_annotations_full(run_id)

    def fetch_chapter_characters_full(self, run_id: str) -> list[CharacterFactRow]:
        """2026-08-05 用于从数据库图人物事实展开 章节人物记录"""
        rows: list[CharacterFactRow] = []
        for fact in self._graph_facts(run_id, content_kind="character_observation"):
            content = dict(fact.content)
            entity = content.get("entity")
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("name") or "").strip()
            if entity.get("entity_type") != "character" or not is_global_character_surface_name(name):
                continue
            rows.append(
                CharacterFactRow(
                    chapter_id=int(content["chapter_id"]),
                    name=name,
                    surface_name=name,
                    reference_kind="global_character",
                    reference_slot=None,
                    resolved_global_name=name,
                    global_skip_reason=None,
                    role_function=str(content["role_function"]),
                    action=str(content["action"]),
                    emotion_score=str(content["emotion"]),
                )
            )
        return rows

    def fetch_characters_with_scores(self, run_id: str) -> list[CharacterFactRow]:
        """2026-08-05 用于读取人物榜与聚合指标需要的图人物事实"""
        return self.fetch_chapter_characters_full(run_id)

    def fetch_character_emotion_sequence(self, run_id: str) -> list[CharacterFactRow]:
        """2026-08-05 用于按章节顺序读取人物情绪事实序列"""
        sequence_map = self._chapter_sequence_map(run_id)
        return sorted(
            self.fetch_chapter_characters_full(run_id),
            key=lambda row: (sequence_map.get(row.chapter_id, row.chapter_id), row.chapter_id),
        )

    def fetch_chapter_dialogues_full(self, run_id: str) -> list[DialogueFactRow]:
        """2026-08-11 用于从对话记录表展开 章节对话记录"""
        rows: list[DialogueFactRow] = []
        statement = (
            select(DialogueRecord)
            .join(
                Chapter,
                (Chapter.run_id == DialogueRecord.run_id) & (Chapter.chapter_id == DialogueRecord.chapter_id),
            )
            .where(DialogueRecord.run_id == run_id)
            .order_by(Chapter.sequence, DialogueRecord.chapter_id, DialogueRecord.start)
        )
        for record in self.session.execute(statement).scalars().all():
            speaker_name = str(record.speaker or "").strip()
            valid_speaker = speaker_name if is_global_character_surface_name(speaker_name) else None
            speaker_names = [valid_speaker] if valid_speaker else []
            speaker_references = (
                [
                    {
                        "surface_name": valid_speaker,
                        "reference_kind": "global_character",
                        "reference_slot": None,
                        "resolved_global_name": valid_speaker,
                        "can_enter_global_character": True,
                        "global_skip_reason": None,
                    }
                ]
                if valid_speaker
                else []
            )
            rows.append(
                DialogueFactRow(
                    chapter_id=int(record.chapter_id),
                    speaker=speaker_names,
                    speaker_references=speaker_references,
                    length=len(record.content),
                    tone=record.tone,
                )
            )
        return rows

    def fetch_foreshadowing_trees(self, run_id: str) -> list[ForeshadowingTreeView]:
        """2026-09-13 用于汇总伏笔树（根事件属性 + 全部挂边章节与事件）"""
        sequence_map = self._chapter_sequence_map(run_id)
        root_stmt = (
            select(EventNode)
            .join(
                Chapter,
                (Chapter.run_id == EventNode.run_id) & (Chapter.chapter_id == EventNode.chapter_id),
            )
            .where(
                EventNode.run_id == run_id,
                EventNode.is_foreshadowing_root.is_(True),
            )
            .order_by(Chapter.sequence, EventNode.chapter_id, EventNode.event_id)
        )
        roots = list(self.session.execute(root_stmt).scalars().all())
        if not roots:
            return []
        edge_stmt = (
            select(EventEdge)
            .join(
                Chapter,
                (Chapter.run_id == EventEdge.run_id) & (Chapter.chapter_id == EventEdge.target_chapter_id),
            )
            .where(
                EventEdge.run_id == run_id,
                EventEdge.edge_type == "foreshadowing",
                EventEdge.is_active.is_(True),
            )
            .order_by(Chapter.sequence, EventEdge.target_chapter_id, EventEdge.edge_id)
        )
        edges_by_root: dict[str, list[EventEdge]] = {}
        targets_by_id: dict[str, EventNode] = {}
        all_edges: list[EventEdge] = list(self.session.execute(edge_stmt).scalars().all())
        for edge in all_edges:
            edges_by_root.setdefault(edge.source_event_id, []).append(edge)
        target_ids = {edge.target_event_id for edge in all_edges}
        if target_ids:
            for node in self.session.execute(
                select(EventNode).where(EventNode.run_id == run_id, EventNode.event_id.in_(target_ids))
            ).scalars().all():
                targets_by_id[node.event_id] = node
        views: list[ForeshadowingTreeView] = []
        for root in roots:
            edges = edges_by_root.get(root.event_id, [])
            anchor_chapter_ids = sorted(
                {root.chapter_id, *(edge.target_chapter_id for edge in edges)},
                key=lambda chapter_id: (sequence_map.get(chapter_id, chapter_id), chapter_id),
            )
            last_chapter_id = anchor_chapter_ids[-1] if anchor_chapter_ids else root.chapter_id
            latest_edge = edges[-1] if edges else None
            latest_node = targets_by_id.get(latest_edge.target_event_id) if latest_edge else None
            status = root.foreshadowing_status or "open"
            views.append(
                ForeshadowingTreeView(
                    root_event_id=root.event_id,
                    tree_id=root.tree_id,
                    first_chapter_id=root.chapter_id,
                    last_chapter_id=last_chapter_id,
                    anchor_chapter_ids=anchor_chapter_ids,
                    description=root.description,
                    payoff_likelihood=root.payoff_likelihood,
                    strength=root.strength,
                    status=status,
                    active=status != "likely_paid_off",
                    latest_reason=latest_node.description if latest_node is not None else None,
                    latest_why_unresolved_now=None,
                )
            )
        return views

    def calculate_foreshadow_expectation(self, run_id: str) -> float | None:
        """2026-09-13 用于按伏笔树根生命周期属性计算回收预期（权重口径不变）"""
        roots = list(
            self.session.execute(
                select(EventNode).where(
                    EventNode.run_id == run_id,
                    EventNode.is_foreshadowing_root.is_(True),
                )
            ).scalars().all()
        )
        if not roots:
            return None
        edge_counts = {
            row.source_event_id: int(row.edge_count)
            for row in self.session.execute(
                select(
                    EventEdge.source_event_id,
                    func.count().label("edge_count"),
                )
                .where(
                    EventEdge.run_id == run_id,
                    EventEdge.edge_type == "foreshadowing",
                )
                .group_by(EventEdge.source_event_id)
            ).all()
        }
        weighted_total = 0.0
        total_weight = 0.0
        has_evidence = False
        for root in roots:
            # 挂边数 + 埋设本体记 1（旧 hit_count 口径：埋设也是一条命中）
            hit_count = 1 + edge_counts.get(root.event_id, 0)
            # 2026-08-16 P3：字段为 None 时不冒充 LLM 判断；若全树都无
            # payoff_likelihood/strength 证据，说明上游输入退化，结果为 None。
            has_evidence = has_evidence or any(
                value is not None for value in (root.payoff_likelihood, root.strength)
            )
            status = root.foreshadowing_status or "open"
            base = _EXPECTATION_BASE_SCORE_BY_PAYOFF.get(
                root.payoff_likelihood or "",
                _EXPECTATION_BASE_SCORE_BY_PAYOFF["medium"],
            )
            status_bonus = _EXPECTATION_STATUS_BONUS.get(
                status,
                _EXPECTATION_STATUS_BONUS["open"],
            )
            strength_bonus = _EXPECTATION_STRENGTH_BONUS.get(
                root.strength or "",
                _EXPECTATION_STRENGTH_BONUS["low"],
            )
            score = min(
                1.0,
                max(
                    0.0,
                    base
                    + status_bonus
                    + strength_bonus
                    + (0.08 if hit_count >= 3 else 0.04 if hit_count == 2 else 0.0),
                ),
            )
            status_weight = _EXPECTATION_STATUS_WEIGHT.get(
                status,
                _EXPECTATION_STATUS_WEIGHT["open"],
            )
            strength_weight = _EXPECTATION_STRENGTH_WEIGHT.get(
                root.strength or "",
                _EXPECTATION_STRENGTH_WEIGHT["low"],
            )
            weight = status_weight + (0.20 if hit_count >= 3 else 0.10 if hit_count == 2 else 0.0) + strength_weight
            weighted_total += score * weight
            total_weight += weight
        if not has_evidence:
            return None
        return round(weighted_total / total_weight, 4)

    def has_annotations(self, run_id: str) -> bool:
        """2026-08-05 用于判断当前 run 是否存在章节正式标注"""
        stmt = select(func.count()).select_from(ChapterAnnotationRecord).where(ChapterAnnotationRecord.run_id == run_id)
        return int(self.session.execute(stmt).scalar_one() or 0) > 0

    def is_annotate_complete(self, run_id: str) -> bool:
        """2026-08-05 用于按真实章节集合严格判断标注阶段完成状态"""
        expected = {
            int(chapter_id)
            for chapter_id in self.session.execute(
                select(Chapter.chapter_id).where(Chapter.run_id == run_id).distinct()
            ).scalars()
        }
        if not expected:
            return False
        actual = {
            int(chapter_id)
            for chapter_id in self.session.execute(
                select(ChapterAnnotationRecord.chapter_id).where(ChapterAnnotationRecord.run_id == run_id).distinct()
            ).scalars()
        }
        return actual == expected

    def get_annotation_by_chapter(self, run_id: str, chapter_id: int) -> dict[str, Any] | None:
        """2026-08-05 用于按 chapter_id 回读由章节 segment 展开的标注字典"""
        for row in self.fetch_chapter_annotations_full(run_id):
            if row.chapter_id == chapter_id:
                return asdict(row)
        return None
