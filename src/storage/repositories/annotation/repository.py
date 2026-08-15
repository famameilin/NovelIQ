"""
章节标注最新读侧仓储门面
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func, select

from src.agents.annotation.schema import BoundChapterAnnotation
from src.models.local.character_reference_policy import is_global_character_surface_name
from src.storage.models import (
    Chapter,
    ChapterAnnotationRecord,
    DialogueRecord,
    ForeshadowingThread,
    ForeshadowingThreadHit,
    GraphFact,
)
from src.storage.repositories.base import BaseRepository

_EXPECTATION_BASE_SCORE_BY_PAYOFF = {"high": 0.62, "medium": 0.38}
_EXPECTATION_STATUS_BONUS = {"open": -0.07, "reinforced": 0.03, "likely_paid_off": 0.28}
_EXPECTATION_STRENGTH_BONUS = {"high": 0.03, "medium": 0.0, "low": -0.05}
_EXPECTATION_STATUS_WEIGHT = {"open": 0.75, "reinforced": 1.0, "likely_paid_off": 1.2}
_EXPECTATION_STRENGTH_WEIGHT = {"high": 0.05, "medium": 0.0, "low": -0.05}


@dataclass(frozen=True)
class ChapterAnnotationRow:
    """2026-08-05 用于向 章节消费者暴露章节 segment 的具名读模型"""

    chapter_id: int
    emotional_valence: str
    event_type: str
    pivot_moment: bool
    cliffhanger: bool
    has_foreshadowing: bool | None = None
    is_strong_setup: bool | None = None
    foreshadowing_type: str | None = None
    setup_kind: str | None = None
    foreshadowing_desc: str | None = None
    setup_summary: str | None = None
    why_unresolved_now: str | None = None
    expected_payoff_family: str | None = None
    payoff_likelihood: str | None = None
    linked_setup_id: str | None = None


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
class ForeshadowingThreadView:
    """2026-08-05 用于向 API 与诊断暴露伏笔线程汇总视图"""

    setup_id: str
    first_chapter_id: int
    last_chapter_id: int
    anchor_chapter_ids: list[int]
    setup_summary: str
    setup_kind: str
    expected_payoff_family: str
    payoff_likelihood: str
    confidence: str
    strength: str
    status: str
    active: bool
    latest_reason: str
    latest_why_unresolved_now: str


class AnnotationRepository(BaseRepository[ChapterAnnotationRecord]):
    """2026-08-05 用于统一读取章节正式标注与数据库图事实"""

    def _chapter_annotations(self, run_id: str) -> list[ChapterAnnotationRecord]:
        """2026-08-05 用于按真实章节顺序读取全部正式章节标注"""
        stmt = (
            select(ChapterAnnotationRecord)
            .where(ChapterAnnotationRecord.run_id == run_id)
            .order_by(ChapterAnnotationRecord.chapter_id)
        )
        return list(self.session.execute(stmt).scalars().all())

    def _graph_facts(self, run_id: str, *, content_kind: str) -> list[GraphFact]:
        """2026-08-07 用于读取指定类型每个 fact_id 的最新不可变版本"""
        stmt = (
            select(GraphFact)
            .where(
                GraphFact.run_id == run_id,
                GraphFact.source_kind == "annotation",
            )
            .order_by(
                GraphFact.fact_id,
                GraphFact.fact_revision.desc(),
                GraphFact.graph_fact_version_id.desc(),
            )
        )
        latest_by_fact_id: dict[str, GraphFact] = {}
        for row in self.session.execute(stmt).scalars().all():
            latest_by_fact_id.setdefault(str(row.fact_id), row)
        return sorted(
            (
                row
                for row in latest_by_fact_id.values()
                if isinstance(row.content, dict) and row.content.get("kind") == content_kind
            ),
            key=lambda row: (row.effective_chapter_id, row.graph_fact_version_id),
        )

    def _foreshadowing_by_chapter(self, run_id: str) -> dict[int, dict[str, Any]]:
        """2026-08-05 用于把伏笔 thread 与 hit 展开到实际命中章节"""
        stmt = (
            select(ForeshadowingThreadHit, ForeshadowingThread)
            .join(ForeshadowingThread, ForeshadowingThreadHit.setup_id == ForeshadowingThread.setup_id)
            .where(
                ForeshadowingThreadHit.run_id == run_id,
                ForeshadowingThread.run_id == run_id,
            )
            .order_by(ForeshadowingThreadHit.chapter_id, ForeshadowingThreadHit.hit_id)
        )
        by_chapter: dict[int, dict[str, Any]] = {}
        for hit, thread in self.session.execute(stmt).all():
            by_chapter[hit.chapter_id] = {
                "has_foreshadowing": True,
                "is_strong_setup": True,
                "foreshadowing_type": thread.foreshadowing_type,
                "setup_kind": thread.setup_kind,
                "foreshadowing_desc": thread.setup_summary,
                "setup_summary": thread.setup_summary,
                "why_unresolved_now": "",
                "expected_payoff_family": thread.expected_payoff_family,
                "payoff_likelihood": thread.payoff_likelihood,
                "linked_setup_id": None if hit.is_new_setup else thread.setup_id,
            }
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
                        **foreshadowing_by_chapter.get(chunk.chunk_id, {}),
                    )
                )
        return sorted(rows, key=lambda row: row.chapter_id)

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
        return sorted(self.fetch_chapter_characters_full(run_id), key=lambda row: row.chapter_id)

    def fetch_chapter_dialogues_full(self, run_id: str) -> list[DialogueFactRow]:
        """2026-08-11 用于从对话记录表展开 章节对话记录"""
        rows: list[DialogueFactRow] = []
        statement = (
            select(DialogueRecord)
            .where(DialogueRecord.run_id == run_id)
            .order_by(DialogueRecord.chapter_id, DialogueRecord.start)
        )
        for record in self.session.execute(statement).scalars().all():
            speaker_name = str(record.speaker or "").strip()
            valid_speaker = (
                speaker_name if is_global_character_surface_name(speaker_name) else None
            )
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

    def fetch_foreshadowing_threads(self, run_id: str) -> list[ForeshadowingThreadView]:
        """2026-08-05 用于汇总伏笔线程与全部命中锚点"""
        thread_stmt = (
            select(ForeshadowingThread)
            .where(ForeshadowingThread.run_id == run_id)
            .order_by(ForeshadowingThread.first_chapter_id, ForeshadowingThread.setup_id)
        )
        threads = list(self.session.execute(thread_stmt).scalars().all())
        if not threads:
            return []
        hit_stmt = (
            select(ForeshadowingThreadHit)
            .where(ForeshadowingThreadHit.run_id == run_id)
            .order_by(
                ForeshadowingThreadHit.setup_id,
                ForeshadowingThreadHit.chapter_id,
                ForeshadowingThreadHit.hit_id,
            )
        )
        hits_by_setup: dict[str, list[ForeshadowingThreadHit]] = {}
        for hit in self.session.execute(hit_stmt).scalars().all():
            hits_by_setup.setdefault(hit.setup_id, []).append(hit)
        views: list[ForeshadowingThreadView] = []
        for thread in threads:
            hits = hits_by_setup.get(thread.setup_id, [])
            latest = hits[-1] if hits else None
            views.append(
                ForeshadowingThreadView(
                    setup_id=thread.setup_id,
                    first_chapter_id=thread.first_chapter_id,
                    last_chapter_id=thread.last_chapter_id,
                    anchor_chapter_ids=sorted({hit.chapter_id for hit in hits}),
                    setup_summary=thread.setup_summary,
                    setup_kind=thread.setup_kind,
                    expected_payoff_family=thread.expected_payoff_family,
                    payoff_likelihood=thread.payoff_likelihood,
                    confidence=thread.confidence,
                    strength=thread.strength,
                    status=thread.status,
                    active=bool(thread.active),
                    latest_reason=latest.anchor_text if latest else "",
                    latest_why_unresolved_now="",
                )
            )
        return views

    def calculate_foreshadow_expectation(self, run_id: str) -> float | None:
        """2026-08-05 用于按最新伏笔线程生命周期计算回收预期"""
        threads = list(
            self.session.execute(
                select(ForeshadowingThread).where(ForeshadowingThread.run_id == run_id)
            )
            .scalars()
            .all()
        )
        if not threads:
            return None
        hit_counts = {
            row.setup_id: int(row.hit_count)
            for row in self.session.execute(
                select(
                    ForeshadowingThreadHit.setup_id,
                    func.count().label("hit_count"),
                )
                .where(ForeshadowingThreadHit.run_id == run_id)
                .group_by(ForeshadowingThreadHit.setup_id)
            ).all()
        }
        weighted_total = 0.0
        total_weight = 0.0
        for thread in threads:
            hit_count = hit_counts.get(thread.setup_id, 0)
            if hit_count < 1:
                raise ValueError(f"伏笔线程缺少命中记录: {thread.setup_id}")
            # 2026-08-13 P1-2：schema 侧对枚举字段非法值降级为 "unknown"，
            # 这里按最保守档位兜底，避免任意字符串直接索引常量字典抛 KeyError
            base = _EXPECTATION_BASE_SCORE_BY_PAYOFF.get(
                thread.payoff_likelihood,
                _EXPECTATION_BASE_SCORE_BY_PAYOFF["medium"],
            )
            status_bonus = _EXPECTATION_STATUS_BONUS.get(
                thread.status,
                _EXPECTATION_STATUS_BONUS["open"],
            )
            strength_bonus = _EXPECTATION_STRENGTH_BONUS.get(
                thread.strength,
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
                thread.status,
                _EXPECTATION_STATUS_WEIGHT["open"],
            )
            strength_weight = _EXPECTATION_STRENGTH_WEIGHT.get(
                thread.strength,
                _EXPECTATION_STRENGTH_WEIGHT["low"],
            )
            weight = (
                status_weight
                + (0.20 if hit_count >= 3 else 0.10 if hit_count == 2 else 0.0)
                + strength_weight
            )
            weighted_total += score * weight
            total_weight += weight
        return round(weighted_total / total_weight, 4)

    def has_annotations(self, run_id: str) -> bool:
        """2026-08-05 用于判断当前 run 是否存在章节正式标注"""
        stmt = (
            select(func.count())
            .select_from(ChapterAnnotationRecord)
            .where(ChapterAnnotationRecord.run_id == run_id)
        )
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
                select(ChapterAnnotationRecord.chapter_id)
                .where(ChapterAnnotationRecord.run_id == run_id)
                .distinct()
            ).scalars()
        }
        return actual == expected

    def get_annotation_by_chapter(self, run_id: str, chapter_id: int) -> dict[str, Any] | None:
        """2026-08-05 用于按 chapter_id 回读由章节 segment 展开的标注字典"""
        for row in self.fetch_chapter_annotations_full(run_id):
            if row.chapter_id == chapter_id:
                return asdict(row)
        return None
