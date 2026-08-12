"""
章节标注连续性查询与写入 Repository
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    ActiveCaseDetails,
    BoundChapterAnnotation,
    BoundDialogue,
    BoundForeshadowing,
    CaseSearchResult,
    CompletionCase,
    ForeshadowingSearchResult,
    PendingCase,
    ResolvedCase,
    SearchResult,
    TextSearchResult,
)
from src.config import settings
from src.models.local.embedding import EmbeddingClient
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    ChapterAnnotationRecord,
    Chunk,
    DialogueRecord,
    ForeshadowingThread,
    ForeshadowingThreadHit,
    GraphFact,
)
from src.storage.repositories.base import BaseRepository
from src.text_search import TextSearchService, extract_query_terms


def normalize_text(value: str) -> str:
    """2026-08-05 用于统一 Unicode NFC 换行和首尾空白"""
    return unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _text_matches(query: str, *values: str) -> bool:
    """2026-08-05 用于判断 query 或拆分词项是否命中任一文本字段"""
    haystack = "\n".join(normalize_text(value).lower() for value in values if value)
    return any(term in haystack for term in extract_query_terms(query))


def _case_view(row: CasePoolCase) -> CaseSearchResult:
    """2026-08-07 用于把 active 案例转换为严格类型和原目标章节查询结果"""
    return CaseSearchResult.model_validate(
        {
            "id": row.id,
            "type": row.case_type,
            "chunk_id": row.chunk_id,
            "keys": list(row.keys),
            "description": row.description,
            "state": row.state,
        }
    )


class DatabaseAnnotationQueryService:
    """2026-08-07 用于通过只读 Session 实现图原文案例与伏笔查询"""

    def __init__(
        self,
        session: Session,
        run_id: str,
        current_chapter_id: int,
        current_first_chunk_id: int,
        current_last_chunk_id: int,
        embedding_client: EmbeddingClient | None = None,
    ):
        """2026-08-07 用于绑定单次尝试的 run 章节边界与原文检索服务"""
        self.session = session
        self.run_id = run_id
        self.current_chapter_id = current_chapter_id
        self.current_first_chunk_id = current_first_chunk_id
        self.current_last_chunk_id = current_last_chunk_id
        chapter_ids = list(
            self.session.execute(
                select(Chunk.chapter_id)
                .where(Chunk.run_id == run_id)
                .group_by(Chunk.chapter_id)
                .order_by(func.min(Chunk.chunk_id))
            ).scalars()
        )
        if current_chapter_id not in chapter_ids:
            raise ValueError(f"当前章节不存在: chapter_id={current_chapter_id}")
        self.current_chapter_order = chapter_ids.index(current_chapter_id) + 1
        self.text_search_service = TextSearchService(
            session,
            run_id=run_id,
            embedding_client=embedding_client,
            semantic_enabled=settings.models.paragraph_embedding.semantic_enabled,
            semantic_top_k=settings.models.paragraph_embedding.top_k,
        )

    def _active_case_rows(self) -> list[CasePoolCase]:
        """2026-08-05 用于按稳定顺序读取当前 run 的全部活动案例"""
        statement = (
            select(CasePoolCase)
            .where(CasePoolCase.run_id == self.run_id, CasePoolCase.state == "active")
            .order_by(CasePoolCase.created_at, CasePoolCase.id)
        )
        return list(self.session.execute(statement).scalars().all())

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
        rotation_statement = (
            select(CasePoolCase)
            .where(CasePoolCase.run_id == self.run_id, CasePoolCase.state == "active")
            .order_by(CasePoolCase.last_surfaced_at.asc().nullsfirst(), CasePoolCase.id)
            .limit(rotation_limit)
        )
        rotation_rows = list(self.session.execute(rotation_statement).scalars().all())
        merged: dict[str, CasePoolCase] = {row.id: row for row in semantic_rows}
        for row in rotation_rows:
            if len(merged) >= semantic_limit + rotation_limit:
                break
            merged.setdefault(row.id, row)
        return (
            [_case_view(row) for row in merged.values()],
            [row.id for row in rotation_rows],
        )

    def search_pool(
        self,
        query: str,
        *,
        hidden_case_ids: set[str],
        limit: int = 50,
    ) -> SearchResult:
        """2026-08-07 用于检索案例与伏笔池并原样转交根 Evidence"""
        results: list[CaseSearchResult | ForeshadowingSearchResult] = []
        for row in self._active_case_rows():
            if row.id in hidden_case_ids:
                continue
            if _text_matches(query, *[str(key) for key in row.keys], row.description):
                results.append(_case_view(row))
            if len(results) >= limit:
                return SearchResult(results=results)

        thread_statement = (
            select(ForeshadowingThread)
            .where(
                ForeshadowingThread.run_id == self.run_id,
                ForeshadowingThread.active.is_(True),
            )
            .order_by(ForeshadowingThread.last_chunk_id, ForeshadowingThread.setup_id)
        )
        for thread in self.session.execute(thread_statement).scalars().all():
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
                )
            )
            if len(results) >= limit:
                break
        return SearchResult(results=results)

    async def search_text(
        self,
        query: str,
        *,
        range_name: str,
        limit: int = 50,
    ) -> list[TextSearchResult]:
        """2026-08-07 用于按 previous 或 future 范围联合定位原文候选"""
        if range_name == "previous":
            min_chunk_id = None
            max_chunk_id = self.current_first_chunk_id - 1
        elif range_name == "future":
            min_chunk_id = self.current_last_chunk_id + 1
            max_chunk_id = None
        else:
            raise ValueError("search_text.range 只能是 previous 或 future")
        candidates = await self.text_search_service.search(
            query,
            min_chunk_id=min_chunk_id,
            max_chunk_id=max_chunk_id,
            limit=limit,
        )
        return [
            TextSearchResult(
                chapter_id=row.chapter_id,
                chunk_id=row.chunk_id,
                excerpt=row.excerpt,
                keyword_score=row.keyword_score,
                semantic_score=row.semantic_score,
            )
            for row in candidates
        ]

    def read_text(self, chunk_id: int) -> str:
        """2026-08-07 用于读取本轮文本搜索候选的同 run 完整原文"""
        return self.text_search_service.read(chunk_id)

    def fetch_active_case_details(self, case_id: str) -> ActiveCaseDetails | None:
        """2026-08-07 用于回读 active 案例并恢复系统稳定目标"""
        statement = select(CasePoolCase).where(
            CasePoolCase.run_id == self.run_id,
            CasePoolCase.id == case_id,
            CasePoolCase.state == "active",
        )
        row = self.session.execute(statement).scalar_one_or_none()
        if row is None:
            return None
        return ActiveCaseDetails(
            **_case_view(row).model_dump(mode="python"),
            target_key=row.target_key,
            target_ref=dict(row.target_ref),
        )

    def thread_exists(self, setup_id: str) -> bool:
        """2026-08-11 用于校验伏笔线程 id 属于当前 run 活跃线程"""
        return (
            self.session.execute(
                select(ForeshadowingThread.setup_id).where(
                    ForeshadowingThread.run_id == self.run_id,
                    ForeshadowingThread.setup_id == setup_id,
                    ForeshadowingThread.active.is_(True),
                )
            ).scalar_one_or_none()
            is not None
        )


class ChapterAnnotationRepository(BaseRepository[ChapterAnnotationRecord]):
    """2026-08-07 用于查询和新增章节唯一系统绑定标注"""

    def get_by_chapter(self, run_id: str, chapter_id: int) -> ChapterAnnotationRecord | None:
        """2026-08-05 用于按 run 与真实 chapter_id 查询已提交正式标注"""
        statement = select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id,
            ChapterAnnotationRecord.chapter_id == chapter_id,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def add_annotation(
        self,
        *,
        run_id: str,
        chapter_id: int,
        annotation: BoundChapterAnnotation,
    ) -> ChapterAnnotationRecord:
        """2026-08-07 用于保存最新合同的最终系统绑定章节标注"""
        row = ChapterAnnotationRecord(
            annotation_id=str(uuid4()),
            run_id=run_id,
            chapter_id=chapter_id,
            payload=annotation.model_dump(mode="json"),
        )
        self.session.add(row)
        self.session.flush()
        return row


class CasePoolRepository(BaseRepository[CasePoolCase]):
    """2026-08-07 用于锁定创建解决和轮转稳定目标案例"""

    def lock_active_cases(self, run_id: str, ids: list[str]) -> list[CasePoolCase]:
        """2026-08-05 用于在完成事务开始时锁定全部待解决案例"""
        if not ids:
            return []
        statement = (
            select(CasePoolCase)
            .where(
                CasePoolCase.run_id == run_id,
                CasePoolCase.id.in_(ids),
            )
            .with_for_update()
        )
        rows = list(self.session.execute(statement).scalars().all())
        rows_by_id = {row.id: row for row in rows}
        return [rows_by_id[case_id] for case_id in ids if case_id in rows_by_id]

    def create_case(
        self,
        *,
        run_id: str,
        annotation_id: str,
        pending_case: PendingCase,
    ) -> CasePoolCase:
        """2026-08-07 用于创建系统自动绑定目标的 active 案例"""
        normalized_keys = sorted({normalize_text(key) for key in pending_case.keys})
        row = CasePoolCase(
            id=str(uuid4()),
            run_id=run_id,
            case_type=pending_case.type,
            chunk_id=pending_case.chunk_id,
            keys=normalized_keys,
            description=normalize_text(pending_case.description),
            target_key=pending_case.target_key,
            target_ref=dict(pending_case.target_ref),
            state="active",
            created_by_annotation_id=annotation_id,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def resolve_cases(self, rows: list[CasePoolCase]) -> None:
        """2026-08-07 用于在解决事实已写入后把案例更新为 resolved"""
        now = datetime.now(UTC)
        for row in rows:
            row.state = "resolved"
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
        statement = select(CasePoolCase).where(
            CasePoolCase.run_id == run_id,
            CasePoolCase.state == "active",
            CasePoolCase.id.in_(ids),
        )
        now = datetime.now(UTC)
        for row in self.session.execute(statement).scalars().all():
            row.last_surfaced_annotation_id = annotation_id
            row.last_surfaced_at = now
            row.updated_at = now
        self.session.flush()


class DialogueRecordRepository(BaseRepository[DialogueRecord]):
    """2026-08-11 用于写入系统绑定对话记录并按案例目标定位更新"""

    def sync_dialogues(
        self,
        *,
        run_id: str,
        chapter_id: int,
        chunk_id: int,
        dialogues: list[BoundDialogue],
    ) -> list[DialogueRecord]:
        """2026-08-11 用于把最终系统绑定对话投影到对话记录表（幂等按 candidate_key 去重）"""
        rows: list[DialogueRecord] = []
        existing_keys = set(
            self.session.execute(
                select(DialogueRecord.candidate_key).where(
                    DialogueRecord.run_id == run_id,
                    DialogueRecord.chunk_id == chunk_id,
                )
            ).scalars()
        )
        for dialogue in dialogues:
            if dialogue.candidate_key in existing_keys:
                continue
            row = DialogueRecord(
                dialogue_id=str(uuid4()),
                run_id=run_id,
                chunk_id=chunk_id,
                chapter_id=chapter_id,
                candidate_key=dialogue.candidate_key,
                content=dialogue.content,
                start=dialogue.start,
                end=dialogue.end,
                speaker=dialogue.speaker,
                tone=dialogue.tone,
                is_inner_monologue=dialogue.is_inner_monologue,
                confidence="medium",
            )
            self.session.add(row)
            existing_keys.add(dialogue.candidate_key)
            rows.append(row)
        self.session.flush()
        return rows

    def find_by_candidate_key(self, run_id: str, candidate_key: str) -> DialogueRecord | None:
        """2026-08-11 用于按系统候选键定位对话记录"""
        return self.session.execute(
            select(DialogueRecord).where(
                DialogueRecord.run_id == run_id,
                DialogueRecord.candidate_key == candidate_key,
            )
        ).scalar_one_or_none()

    def apply_resolution(
        self,
        record: DialogueRecord,
        *,
        speaker: str | None,
        tone: str | None,
        is_inner_monologue: bool | None,
    ) -> None:
        """2026-08-11 用于把 dialogue 动作解决结果直接改到对话记录表"""
        if speaker is not None:
            record.speaker = speaker
        if tone is not None:
            record.tone = tone
        if is_inner_monologue is not None:
            record.is_inner_monologue = is_inner_monologue
        record.updated_at = datetime.now(UTC)
        self.session.flush()


class ForeshadowingRepository(BaseRepository[ForeshadowingThread]):
    """2026-08-07 用于从系统绑定标注写入或续接伏笔线程"""

    def sync(
        self,
        *,
        run_id: str,
        chunk_id: int,
        foreshadowing: BoundForeshadowing,
    ) -> tuple[ForeshadowingThread, ForeshadowingThreadHit | None]:
        """2026-08-11 用于只创建新伏笔线程（description 相同视为同一伏笔，已存在时不再重复创建）"""
        normalized = normalize_text(foreshadowing.description)
        # 2026-08-12 大小写变体按 casefold 视为同一伏笔，避免重复建线程
        thread = self.session.execute(
            select(ForeshadowingThread).where(
                ForeshadowingThread.run_id == run_id,
                func.lower(ForeshadowingThread.setup_summary) == normalized.casefold(),
            )
        ).scalar_one_or_none()
        if thread is not None:
            return thread, None
        now = datetime.now(UTC)
        thread = ForeshadowingThread(
            setup_id=str(uuid4()),
            run_id=run_id,
            first_chunk_id=chunk_id,
            last_chunk_id=chunk_id,
            setup_summary=normalized,
            foreshadowing_type="其他",
            setup_kind="其他",
            expected_payoff_family="未指定",
            payoff_likelihood="medium",
            confidence=foreshadowing.confidence,
            strength=foreshadowing.confidence,
            status="open",
            active=True,
            created_at=now,
            updated_at=now,
        )
        self.session.add(thread)
        self.session.flush()
        hit = ForeshadowingThreadHit(
            setup_id=thread.setup_id,
            run_id=run_id,
            chunk_id=chunk_id,
            anchor_text=normalized,
            is_new_setup=True,
            created_at=now,
        )
        self.session.add(hit)
        self.session.flush()
        return thread, hit


class CaseResolutionMappingRepository(BaseRepository[CaseResolutionMapping]):
    """2026-08-11 用于保存案例动作解决结果和实际目标（对话/线程/事实版本）"""

    def add_mapping(
        self,
        *,
        run_id: str,
        annotation_id: str,
        resolved_case: ResolvedCase,
        target_fact: GraphFact | None,
        target_dialogue_id: str | None,
        target_setup_id: str | None,
    ) -> CaseResolutionMapping:
        """2026-08-11 用于按 action 写入解决结果和对应目标标识"""
        resolution = {
            "action": resolved_case.action,
            "reason": resolved_case.reason,
        }
        if resolved_case.action == "dialogue":
            for field_name in ("speaker", "tone", "description", "is_inner_monologue"):
                value = getattr(resolved_case, field_name)
                if value is not None:
                    resolution[field_name] = value
        elif resolved_case.action == "fact":
            for field_name in ("from_entity", "to_entity", "relation_type", "change_kind"):
                value = getattr(resolved_case, field_name)
                if value is not None:
                    resolution[field_name] = value
        elif resolved_case.action == "foreshadowing":
            for field_name in (
                "setup_summary",
                "setup_kind",
                "expected_payoff_family",
                "payoff_likelihood",
                "setup_status",
                "confidence",
                "strength",
            ):
                value = getattr(resolved_case, field_name)
                if value is not None:
                    resolution[field_name] = value
        row = CaseResolutionMapping(
            mapping_id=str(uuid4()),
            run_id=run_id,
            annotation_id=annotation_id,
            case_id=resolved_case.case_id,
            case_type=resolved_case.type,
            target_ref=dict(resolved_case.target_ref),
            resolution=resolution,
            target_fact_id=target_fact.fact_id if target_fact is not None else None,
            target_fact_revision=target_fact.fact_revision if target_fact is not None else None,
            target_dialogue_id=target_dialogue_id,
            target_setup_id=target_setup_id,
        )
        self.session.add(row)
        self.session.flush()
        return row


def completion_case_view(row: CasePoolCase) -> CompletionCase:
    """2026-08-07 用于把真实案例 ORM 行转换为完成结果"""
    return CompletionCase.model_validate(
        {
            "id": row.id,
            "type": row.case_type,
            "chunk_id": row.chunk_id,
            "keys": list(row.keys),
            "description": row.description,
            "target_ref": dict(row.target_ref),
            "state": row.state,
        }
    )