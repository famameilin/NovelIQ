"""
章节标注连续性查询与写入 Repository
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    AfterChunkSearchResult,
    CasePayload,
    CaseSearchResult,
    ChapterAnnotation,
    CompletionCase,
    CompletionFact,
    CompletionForeshadowing,
    Evidence,
    FactPayload,
    FactSearchResult,
    ForeshadowingPayload,
    ForeshadowingSearchResult,
    SearchResult,
)
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    ChapterAnnotationRecord,
    Chunk,
    ContinuityFact,
    ForeshadowingThread,
    ForeshadowingThreadHit,
    GraphFact,
    GraphFactSource,
)
from src.storage.repositories.base import BaseRepository


def normalize_text(value: str) -> str:
    """2026-08-05 用于统一 Unicode NFC 换行和首尾空白"""
    return unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n").strip()


def canonical_json(value: Any) -> str:
    """2026-08-05 用于生成键排序稳定的 JSON 语义文本"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_dedupe_key(value: Any) -> str:
    """2026-08-05 用于生成案例与事实精确复用的稳定摘要"""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _query_terms(query: str) -> list[str]:
    """2026-08-05 用于把检索问题拆成可同时匹配中英文的规范化词项"""
    normalized = normalize_text(query).lower()
    terms = [term for term in re.split(r"[\s,，。；;：:、!?！？\"'（）()\[\]{}]+", normalized) if term]
    return list(dict.fromkeys([normalized, *terms]))


def _text_matches(query: str, *values: str) -> bool:
    """2026-08-05 用于判断 query 或拆分词项是否命中任一文本字段"""
    haystack = "\n".join(normalize_text(value).lower() for value in values if value)
    return any(term in haystack for term in _query_terms(query))


def _case_view(row: CasePoolCase) -> CaseSearchResult:
    """2026-08-05 用于把活动案例 ORM 行转换为字段顺序固定的查询结果"""
    return CaseSearchResult.model_validate(
        {
            "id": row.id,
            "keys": list(row.keys),
            "description": row.description,
            "evidence": row.evidence,
            "state": row.state,
        }
    )


def _excerpt(text_value: str, query: str, *, radius: int = 100) -> str:
    """2026-08-05 用于围绕 after 命中位置返回受限检索片段"""
    normalized_text = text_value.lower()
    positions = [normalized_text.find(term) for term in _query_terms(query)]
    positions = [position for position in positions if position >= 0]
    position = min(positions) if positions else 0
    start = max(0, position - radius)
    end = min(len(text_value), position + max(1, len(query)) + radius)
    return text_value[start:end]


class DatabaseAnnotationQueryService:
    """2026-08-05 用于通过只读 Session 实现 Agent 全部检索与 after 授权查询"""

    def __init__(self, session: Session, run_id: str):
        """2026-08-05 用于绑定单次尝试的只读 Session 与 run 边界"""
        self.session = session
        self.run_id = run_id

    def _active_case_rows(self) -> list[CasePoolCase]:
        """2026-08-05 用于按稳定顺序读取当前 run 的全部活动案例"""
        stmt = (
            select(CasePoolCase)
            .where(CasePoolCase.run_id == self.run_id, CasePoolCase.state == "active")
            .order_by(CasePoolCase.created_at, CasePoolCase.id)
        )
        return list(self.session.execute(stmt).scalars().all())

    def find_initial_case_candidates(
        self,
        current_text: str,
        *,
        semantic_limit: int = 50,
        rotation_limit: int = 50,
    ) -> tuple[list[CaseSearchResult], list[str]]:
        """2026-08-05 用于合并 current 相关候选与最久未展示活动案例"""
        rows = self._active_case_rows()
        semantic_rows = [
            row
            for row in rows
            if any(normalize_text(key).lower() in current_text.lower() for key in row.keys)
            or _text_matches(row.description, current_text)
        ][:semantic_limit]
        rotation_stmt = (
            select(CasePoolCase)
            .where(CasePoolCase.run_id == self.run_id, CasePoolCase.state == "active")
            .order_by(CasePoolCase.last_surfaced_at.asc().nullsfirst(), CasePoolCase.id)
            .limit(rotation_limit)
        )
        rotation_rows = list(self.session.execute(rotation_stmt).scalars().all())
        merged: dict[str, CasePoolCase] = {row.id: row for row in semantic_rows}
        for row in rotation_rows:
            if len(merged) >= semantic_limit + rotation_limit:
                break
            merged.setdefault(row.id, row)
        return (
            [_case_view(row) for row in merged.values()],
            [row.id for row in rotation_rows],
        )

    def search_continuity(
        self,
        query: str,
        *,
        hidden_case_ids: set[str],
        limit: int = 50,
    ) -> SearchResult:
        """2026-08-05 用于用同一 query 合并案例 keys description 图事实与伏笔线程"""
        results: list[Any] = []
        for row in self._active_case_rows():
            if row.id in hidden_case_ids:
                continue
            if _text_matches(query, *[str(key) for key in row.keys], row.description):
                results.append(_case_view(row))
            if len(results) >= limit:
                return SearchResult(results=results)

        fact_stmt = (
            select(GraphFact, GraphFactSource)
            .join(GraphFactSource, GraphFactSource.graph_fact_id == GraphFact.graph_fact_id)
            .where(GraphFact.run_id == self.run_id, GraphFact.active.is_(True))
            .order_by(GraphFact.graph_fact_id)
        )
        for fact, source in self.session.execute(fact_stmt).all():
            content_text = canonical_json(fact.content)
            if not _text_matches(query, fact.subject_name, fact.predicate, content_text):
                continue
            results.append(
                FactSearchResult(
                    fact_id=source.stable_fact_id,
                    source_kind=source.source_kind,
                    content=dict(fact.content),
                    evidence=Evidence.model_validate(source.evidence),
                )
            )
            if len(results) >= limit:
                return SearchResult(results=results)

        thread_stmt = (
            select(ForeshadowingThread)
            .where(
                ForeshadowingThread.run_id == self.run_id,
                ForeshadowingThread.active.is_(True),
            )
            .order_by(ForeshadowingThread.last_chunk_id, ForeshadowingThread.setup_id)
        )
        for thread in self.session.execute(thread_stmt).scalars().all():
            if not _text_matches(
                query,
                thread.setup_summary,
                thread.setup_kind,
                thread.expected_payoff_family,
            ):
                continue
            results.append(
                ForeshadowingSearchResult(
                    record_id=thread.setup_id,
                    content={
                        "setup_summary": thread.setup_summary,
                        "setup_kind": thread.setup_kind,
                        "expected_payoff_family": thread.expected_payoff_family,
                        "payoff_likelihood": thread.payoff_likelihood,
                        "status": thread.status,
                    },
                    evidence=Evidence.model_validate(thread.evidence),
                )
            )
            if len(results) >= limit:
                break
        return SearchResult(results=results)

    def fetch_active_cases(self, ids: list[str]) -> list[CaseSearchResult]:
        """2026-08-05 用于按输入顺序回读本轮仍为 active 的真实案例"""
        stmt = select(CasePoolCase).where(
            CasePoolCase.run_id == self.run_id,
            CasePoolCase.state == "active",
            CasePoolCase.id.in_(ids),
        )
        rows_by_id = {row.id: row for row in self.session.execute(stmt).scalars().all()}
        return [_case_view(rows_by_id[case_id]) for case_id in ids if case_id in rows_by_id]

    def search_after(
        self,
        query: str,
        *,
        after_chapter_ids: tuple[int, ...],
        limit: int = 50,
    ) -> list[AfterChunkSearchResult]:
        """2026-08-05 用于遍历固定全部后续章节并只返回 query 命中的 chunk"""
        if not after_chapter_ids:
            return []
        stmt = (
            select(Chunk.chapter_id, Chunk.chunk_id, Chunk.text)
            .where(
                Chunk.run_id == self.run_id,
                Chunk.chapter_id.in_(after_chapter_ids),
            )
            .order_by(Chunk.chapter_id, Chunk.chunk_id)
        )
        results: list[AfterChunkSearchResult] = []
        for row in self.session.execute(stmt).all():
            if not _text_matches(query, row.text):
                continue
            results.append(
                AfterChunkSearchResult(
                    chapter_id=row.chapter_id,
                    chunk_id=row.chunk_id,
                    excerpt=_excerpt(row.text, query),
                )
            )
            if len(results) >= limit:
                break
        return results

    def read_after_chunk(
        self,
        *,
        chapter_id: int,
        chunk_id: int,
        after_chapter_ids: tuple[int, ...],
    ) -> str:
        """2026-08-05 用于读取固定 after 范围中已由工具账本授权的完整原文"""
        if chapter_id not in after_chapter_ids:
            raise ValueError(f"chapter_id 不属于固定 after 范围: {chapter_id}")
        stmt = select(Chunk.text).where(
            Chunk.run_id == self.run_id,
            Chunk.chapter_id == chapter_id,
            Chunk.chunk_id == chunk_id,
        )
        content = self.session.execute(stmt).scalar_one_or_none()
        if content is None:
            raise ValueError(f"after chunk 不存在: chapter_id={chapter_id} chunk_id={chunk_id}")
        return str(content)


class ChapterAnnotationRepository(BaseRepository[ChapterAnnotationRecord]):
    """2026-08-05 用于查询和新增章节唯一正式标注"""

    def get_by_chapter(self, run_id: str, chapter_id: int) -> ChapterAnnotationRecord | None:
        """2026-08-05 用于按 run 与真实 chapter_id 查询已提交正式标注"""
        stmt = select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id,
            ChapterAnnotationRecord.chapter_id == chapter_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def add_annotation(
        self,
        *,
        run_id: str,
        chapter_id: int,
        annotation: ChapterAnnotation,
        initial_finish: ChapterAnnotation,
        after_chapter_ids: list[int],
        revision_payload: dict[str, Any],
    ) -> ChapterAnnotationRecord:
        """2026-08-05 用于 add 并 flush 一条章节正式标注但不提交事务"""
        row = ChapterAnnotationRecord(
            annotation_id=str(uuid4()),
            run_id=run_id,
            chapter_id=chapter_id,
            payload=annotation.model_dump(mode="json"),
            initial_finish_payload=initial_finish.model_dump(mode="json"),
            after_chapter_ids=list(after_chapter_ids),
            revision_payload=dict(revision_payload),
        )
        self.session.add(row)
        self.session.flush()
        return row


class CasePoolRepository(BaseRepository[CasePoolCase]):
    """2026-08-05 用于锁定复用创建与更新案例池记录"""

    def lock_active_cases(self, run_id: str, ids: list[str]) -> list[CasePoolCase]:
        """2026-08-05 用于在完成事务开始时锁定全部来源案例"""
        if not ids:
            return []
        stmt = (
            select(CasePoolCase)
            .where(
                CasePoolCase.run_id == run_id,
                CasePoolCase.id.in_(ids),
            )
            .with_for_update()
        )
        rows = list(self.session.execute(stmt).scalars().all())
        rows_by_id = {row.id: row for row in rows}
        return [rows_by_id[case_id] for case_id in ids if case_id in rows_by_id]

    def upsert_case(
        self,
        *,
        run_id: str,
        annotation_id: str,
        payload: CasePayload,
        evidence: Evidence,
    ) -> CasePoolCase:
        """2026-08-05 用于按规范化 keys 与 description 精确复用或创建活动案例"""
        normalized_keys = sorted({normalize_text(key) for key in payload.keys})
        description = normalize_text(payload.description)
        dedupe_key = build_dedupe_key({"keys": normalized_keys, "description": description})
        stmt = select(CasePoolCase).where(
            CasePoolCase.run_id == run_id,
            CasePoolCase.dedupe_key == dedupe_key,
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            row = CasePoolCase(
                id=str(uuid4()),
                run_id=run_id,
                keys=normalized_keys,
                description=description,
                evidence=evidence.model_dump(mode="json"),
                state="active",
                dedupe_key=dedupe_key,
                created_by_annotation_id=annotation_id,
            )
            self.session.add(row)
        else:
            row.keys = normalized_keys
            row.description = description
            row.evidence = evidence.model_dump(mode="json")
            row.state = "active"
            row.updated_at = datetime.now(UTC)
        self.session.flush()
        return row

    def update_source_states(
        self,
        rows: list[CasePoolCase],
        *,
        rejected_ids: set[str],
    ) -> None:
        """2026-08-05 用于把来源案例原子更新为 consumed 或 rejected"""
        now = datetime.now(UTC)
        for row in rows:
            row.state = "rejected" if row.id in rejected_ids else "consumed"
            row.updated_at = now
        self.session.flush()

    def mark_surfaced(
        self,
        *,
        run_id: str,
        ids: list[str],
        annotation_id: str,
    ) -> None:
        """2026-08-05 用于在完成事务成功路径推进活动案例轮转时间"""
        if not ids:
            return
        stmt = select(CasePoolCase).where(
            CasePoolCase.run_id == run_id,
            CasePoolCase.state == "active",
            CasePoolCase.id.in_(ids),
        )
        now = datetime.now(UTC)
        for row in self.session.execute(stmt).scalars().all():
            row.last_surfaced_annotation_id = annotation_id
            row.last_surfaced_at = now
            row.updated_at = now
        self.session.flush()


class ContinuityFactRepository(BaseRepository[ContinuityFact]):
    """2026-08-05 用于精确复用或创建连续性事实"""

    def upsert_fact(
        self,
        *,
        run_id: str,
        annotation_id: str,
        payload: FactPayload,
        evidence: Evidence,
    ) -> ContinuityFact:
        """2026-08-05 用于按完整规范化语义复用或新增 fact 记录"""
        payload_data = payload.model_dump(mode="json")
        dedupe_key = build_dedupe_key(payload_data)
        stmt = select(ContinuityFact).where(
            ContinuityFact.run_id == run_id,
            ContinuityFact.dedupe_key == dedupe_key,
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            row = ContinuityFact(
                fact_id=str(uuid4()),
                run_id=run_id,
                created_by_annotation_id=annotation_id,
                fact_type=payload.fact_type,
                subject=payload.subject.model_dump(mode="json"),
                predicate=payload.predicate,
                object=payload.object.model_dump(mode="json") if payload.object is not None else None,
                value=payload.value,
                participants=[item.model_dump(mode="json") for item in payload.participants],
                scope=payload.scope,
                story_time=payload.story_time.model_dump(mode="json") if payload.story_time is not None else None,
                assertion=payload.assertion,
                change_kind=payload.change_kind,
                linked_fact_id=payload.linked_fact_id,
                confidence=payload.confidence,
                evidence=evidence.model_dump(mode="json"),
                dedupe_key=dedupe_key,
            )
            self.session.add(row)
            self.session.flush()
        return row

    def completion_view(self, row: ContinuityFact) -> CompletionFact:
        """2026-08-05 用于把真实 fact 行转换为完成结果"""
        payload = FactPayload.model_validate(
            {
                "fact_type": row.fact_type,
                "subject": row.subject,
                "predicate": row.predicate,
                "object": row.object,
                "value": row.value,
                "participants": row.participants,
                "scope": row.scope,
                "story_time": row.story_time,
                "assertion": row.assertion,
                "change_kind": row.change_kind,
                "linked_fact_id": row.linked_fact_id,
                "confidence": row.confidence,
            }
        )
        return CompletionFact(
            fact_id=row.fact_id,
            payload=payload,
            evidence=Evidence.model_validate(row.evidence),
        )


class ForeshadowingRepository(BaseRepository[ForeshadowingThread]):
    """2026-08-05 用于写入或续接已确认伏笔线程与命中"""

    def sync(
        self,
        *,
        run_id: str,
        chunk_id: int,
        payload: ForeshadowingPayload,
        evidence: Evidence,
    ) -> tuple[ForeshadowingThread, ForeshadowingThreadHit]:
        """2026-08-05 用于按稳定字段或 linked_setup_id 同步伏笔并 flush"""
        if payload.is_new_setup:
            stmt = select(ForeshadowingThread).where(
                ForeshadowingThread.run_id == run_id,
                ForeshadowingThread.setup_summary == normalize_text(payload.setup_summary),
                ForeshadowingThread.setup_kind == payload.setup_kind,
                ForeshadowingThread.expected_payoff_family == payload.expected_payoff_family,
            )
            thread = self.session.execute(stmt).scalar_one_or_none()
        else:
            thread = self.session.get(ForeshadowingThread, payload.linked_setup_id)
            if thread is None or thread.run_id != run_id:
                raise ValueError(f"linked_setup_id 不存在或跨 run: {payload.linked_setup_id}")
            if (
                normalize_text(thread.setup_summary) != normalize_text(payload.setup_summary)
                or thread.setup_kind != payload.setup_kind
                or thread.expected_payoff_family != payload.expected_payoff_family
            ):
                raise ValueError("linked_setup_id 的稳定字段与 push payload 不一致")

        now = datetime.now(UTC)
        if thread is None:
            thread = ForeshadowingThread(
                setup_id=str(uuid4()),
                run_id=run_id,
                first_chunk_id=chunk_id,
                last_chunk_id=chunk_id,
                setup_summary=normalize_text(payload.setup_summary),
                foreshadowing_type=payload.foreshadowing_type,
                setup_kind=payload.setup_kind,
                expected_payoff_family=payload.expected_payoff_family,
                payoff_likelihood=payload.payoff_likelihood,
                confidence=payload.confidence,
                strength=payload.confidence,
                status=payload.setup_status,
                active=True,
                evidence=evidence.model_dump(mode="json"),
                created_at=now,
                updated_at=now,
            )
            self.session.add(thread)
        else:
            thread.last_chunk_id = chunk_id
            thread.foreshadowing_type = payload.foreshadowing_type
            thread.payoff_likelihood = payload.payoff_likelihood
            thread.confidence = payload.confidence
            thread.strength = payload.confidence
            thread.status = payload.setup_status
            thread.active = True
            thread.evidence = evidence.model_dump(mode="json")
            thread.updated_at = now
        self.session.flush()
        hit = ForeshadowingThreadHit(
            setup_id=thread.setup_id,
            run_id=run_id,
            chunk_id=chunk_id,
            anchor_text=payload.setup_summary,
            anchor_reason=evidence.reason,
            why_unresolved_now=payload.why_unresolved_now,
            evidence=evidence.model_dump(mode="json"),
            is_new_setup=payload.is_new_setup,
            created_at=now,
        )
        self.session.add(hit)
        self.session.flush()
        return thread, hit

    def completion_view(
        self,
        thread: ForeshadowingThread,
        hit: ForeshadowingThreadHit,
        payload: ForeshadowingPayload,
        evidence: Evidence,
    ) -> CompletionForeshadowing:
        """2026-08-05 用于把真实 setup 与 hit ID 转换为完成结果"""
        return CompletionForeshadowing(
            setup_id=thread.setup_id,
            hit_id=hit.hit_id,
            payload=payload,
            evidence=evidence,
        )


class CaseResolutionMappingRepository(BaseRepository[CaseResolutionMapping]):
    """2026-08-05 用于新增和查询来源案例到实际业务记录的映射"""

    def add_mapping(
        self,
        *,
        run_id: str,
        annotation_id: str,
        result_kind: str,
        evidence: Evidence,
        source_case_id: str | None = None,
        target_case_id: str | None = None,
        target_fact_id: str | None = None,
        target_setup_id: str | None = None,
        target_hit_id: int | None = None,
        rejected_reason_code: str | None = None,
    ) -> CaseResolutionMapping:
        """2026-08-05 用于 add 并 flush 一条严格目标类型来源映射"""
        row = CaseResolutionMapping(
            mapping_id=str(uuid4()),
            run_id=run_id,
            annotation_id=annotation_id,
            source_case_id=source_case_id,
            result_kind=result_kind,
            target_case_id=target_case_id,
            target_fact_id=target_fact_id,
            target_setup_id=target_setup_id,
            target_hit_id=target_hit_id,
            rejected_reason_code=rejected_reason_code,
            evidence=evidence.model_dump(mode="json"),
        )
        self.session.add(row)
        self.session.flush()
        return row


def completion_case_view(row: CasePoolCase) -> CompletionCase:
    """2026-08-05 用于把真实案例 ORM 行转换为完成结果"""
    return CompletionCase.model_validate(
        {
            "id": row.id,
            "keys": list(row.keys),
            "description": row.description,
            "evidence": row.evidence,
            "state": row.state,
        }
    )
