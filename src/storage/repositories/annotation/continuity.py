"""
章节标注连续性查询与写入 Repository
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    ActiveCaseDetails,
    BoundChapterAnnotation,
    BoundDialogue,
    BoundForeshadowing,
    CaseSearchResult,
    CompletionCase,
    EventHistoryResult,
    ForeshadowingSearchResult,
    GraphEvidence,
    PendingCase,
    ResolvedCase,
    SearchResult,
    TextEvidence,
    TextSearchResult,
)
from src.config import settings
from src.models.local.embedding import EmbeddingClient
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    Chapter,
    ChapterAnnotationRecord,
    DialogueRecord,
    EventEdge,
    EventNode,
    ForeshadowingThread,
    ForeshadowingThreadHit,
    GraphFact,
)
from src.storage.repositories.base import BaseRepository
from src.text_search import TextSearchService, extract_query_terms


def normalize_text(value: str) -> str:
    """2026-08-05 用于统一 Unicode NFC 换行和首尾空白"""
    return unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _text_matches(query: str, *values: str | None) -> bool:
    """2026-08-05 用于判断 query 或拆分词项是否命中任一文本字段"""
    haystack = "\n".join(normalize_text(value).lower() for value in values if value)
    return any(term in haystack for term in extract_query_terms(query))


def _match_event_anchor(
    anchors: list[tuple[str, int, int]],
    start: int,
    end: int,
) -> str | None:
    """2026-08-18 用于按字符区间包含为对话弱关联事件锚点

    只有恰好一个事件完全包住 [start, end) 时才返回事件 ID；
    无匹配或多匹配均返回 None。同一坐标系（chunk 文本内偏移）。
    """
    candidates = [
        (event_id, a_start, a_end)
        for event_id, a_start, a_end in anchors
        if a_start <= start and end <= a_end
    ]
    if len(candidates) != 1:
        return None
    return candidates[0][0]


def _case_view(row: CasePoolCase) -> CaseSearchResult:
    """2026-08-07 用于把 active 案例转换为严格类型和原目标章节查询结果"""
    return CaseSearchResult.model_validate(
        {
            "id": row.id,
            "type": row.case_type,
            # M9a-2：运行时 CaseSearchResult 保留 chunk_id 字段（值即章 chunk_id）
            "chunk_id": row.chapter_id,
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
        current_first_paragraph_id: int,
        current_last_paragraph_id: int,
        embedding_client: EmbeddingClient | None = None,
    ):
        """2026-08-14 用于绑定单次尝试的 run 章节边界与原文检索服务

        二期段落化：边界为当前章的段落事实源边界（paragraph_id，§5.2）；
        M7 子 chunk 场景由调用方传章的段落边界，不是子块的边界。
        """
        self.session = session
        self.run_id = run_id
        self.current_chapter_id = current_chapter_id
        self.current_first_paragraph_id = current_first_paragraph_id
        self.current_last_paragraph_id = current_last_paragraph_id
        chapter_ids = list(
            self.session.execute(
                select(Chapter.chapter_id)
                .where(Chapter.run_id == run_id)
                .order_by(Chapter.chapter_id)
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
            .order_by(ForeshadowingThread.last_chapter_id, ForeshadowingThread.setup_id)
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
        """2026-08-14 用于按 previous/future/all 范围联合定位原文候选（段落边界）"""
        if range_name == "previous":
            min_paragraph_id = None
            max_paragraph_id = self.current_first_paragraph_id - 1
        elif range_name == "future":
            min_paragraph_id = self.current_last_paragraph_id + 1
            max_paragraph_id = None
        elif range_name == "all":
            min_paragraph_id = None
            max_paragraph_id = None
        else:
            raise ValueError("search_text.range 只能是 previous、future 或 all")
        candidates = await self.text_search_service.search(
            query,
            min_paragraph_id=min_paragraph_id,
            max_paragraph_id=max_paragraph_id,
            limit=limit,
        )
        return [
            TextSearchResult(
                chapter_id=row.chapter_id,
                paragraph_id=row.paragraph_id,
                excerpt=row.excerpt,
                keyword_score=row.keyword_score,
                semantic_score=row.semantic_score,
            )
            for row in candidates
        ]

    def read_text(self, paragraph_id: int) -> str:
        """2026-08-14 用于读取本轮文本搜索候选段落的同 run 原文（带默认上下文）"""
        return self.text_search_service.read(paragraph_id)

    def search_event_history(
        self,
        query: str,
        *,
        max_chapter_order: int,
        limit: int = 50,
    ) -> list[EventHistoryResult]:
        """2026-08-18 用于在历史章节边界内检索事件并返回可审计 Evidence"""
        if max_chapter_order <= 0 or limit <= 0:
            return []
        rows = self.session.execute(
            select(EventNode)
            .where(
                EventNode.run_id == self.run_id,
                EventNode.chapter_order <= max_chapter_order,
            )
            .order_by(EventNode.chapter_order.desc(), EventNode.event_id, EventNode.event_revision.desc())
        ).scalars()
        latest: dict[str, EventNode] = {}
        for node in rows:
            latest.setdefault(node.event_id, node)
        edge_rows = list(
            self.session.execute(
                select(EventEdge).where(
                    EventEdge.run_id == self.run_id,
                    EventEdge.is_active == 1,
                )
            ).scalars()
        )
        matched: list[EventHistoryResult] = []
        for node in latest.values():
            participant_text = " ".join(
                str(participant.get("entity") or participant.get("name") or "")
                for participant in node.participants
                if isinstance(participant, dict)
            )
            if not _text_matches(query, node.description, participant_text):
                continue
            matched.append(
                EventHistoryResult(
                    event_id=node.event_id,
                    event_revision=node.event_revision,
                    chapter_id=node.chapter_id,
                    chapter_order=node.chapter_order,
                    description=node.description,
                    participants=list(node.participants),
                    anchor_paragraph_ids=list(node.anchor_paragraph_ids),
                    char_start=node.char_start,
                    char_end=node.char_end,
                    text_hash=node.text_hash,
                    evidence=[
                        (
                            TextEvidence.model_validate(item)
                            if "paragraph_ids" in item
                            else GraphEvidence.model_validate(item)
                        )
                        for item in node.evidence
                    ],
                    causal_event_refs=list(node.causal_event_refs),
                    edges=[
                        {
                            "edge_id": edge.edge_id,
                            "edge_type": edge.edge_type,
                            "source_event_id": edge.source_event_id,
                            "source_event_revision": edge.source_event_revision,
                            "target_event_id": edge.target_event_id,
                            "target_event_revision": edge.target_event_revision,
                            "evidence": list(edge.evidence),
                        }
                        for edge in edge_rows
                        if edge.source_event_id == node.event_id
                        or edge.target_event_id == node.event_id
                    ],
                )
            )
            if len(matched) >= limit:
                break
        return matched

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
            # M9a-2：运行时 PendingCase 保留 chunk_id 字段（值即章 chunk_id）
            chapter_id=pending_case.chunk_id,
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
        dialogues: list[BoundDialogue],
        event_anchors: list[tuple[str, int, int]] | None = None,
    ) -> list[DialogueRecord]:
        """2026-08-11 用于把最终系统绑定对话投影到对话记录表（幂等按 candidate_key 去重）

        2026-08-18 P3：event_anchors 为 (event_id, char_start, char_end) 列表，
        写入时按字符区间包含做弱关联——对话区间完全落在某个事件锚点区间内时
        关联该事件的 event_id；无匹配或未提供 anchors 时保持 None。
        """
        rows: list[DialogueRecord] = []
        # 2026-08-13 P2-4：幂等键与唯一约束 uq_dialogue_records_run_candidate 对齐为
        # (run_id, candidate_key)。此前按 (run_id, chapter_id) 查 existing，跨章重复台词
        # 会撞唯一约束抛 IntegrityError。
        candidate_keys = [dialogue.candidate_key for dialogue in dialogues]
        existing_keys = set(
            self.session.execute(
                select(DialogueRecord.candidate_key).where(
                    DialogueRecord.run_id == run_id,
                    DialogueRecord.candidate_key.in_(candidate_keys),
                )
            ).scalars()
        )
        anchors = list(event_anchors or [])
        for dialogue in dialogues:
            if dialogue.candidate_key in existing_keys:
                continue
            row = DialogueRecord(
                dialogue_id=str(uuid4()),
                run_id=run_id,
                chapter_id=chapter_id,
                candidate_key=dialogue.candidate_key,
                content=dialogue.content,
                start=dialogue.start,
                end=dialogue.end,
                speaker=dialogue.speaker,
                tone=dialogue.tone,
                is_inner_monologue=dialogue.is_inner_monologue,
                confidence="medium",
                event_id=_match_event_anchor(anchors, dialogue.start, dialogue.end),
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
        chapter_id: int,
        foreshadowing: BoundForeshadowing,
        setup_event_id: str,
    ) -> tuple[ForeshadowingThread, ForeshadowingThreadHit | None]:
        """2026-08-18 用于创建或续接伏笔线程（按 setup_event_id 去重，不重复建线程）

        2026-08-18：去重键从 setup_summary casefold 文本换为 UNIQUE(run_id, setup_event_id)
        ——同一 setup 事件只允许一条线程。setup_summary 定义为 setup 事件的派生快照
        （兼容字段，不再是独立判断源）。
        """
        normalized = normalize_text(foreshadowing.description)
        # 2026-08-18 按 setup_event_id 查找已存在线程（UNIQUE(run_id, setup_event_id) 兜底）
        thread = self.session.execute(
            select(ForeshadowingThread).where(
                ForeshadowingThread.run_id == run_id,
                ForeshadowingThread.setup_event_id == setup_event_id,
            )
        ).scalar_one_or_none()
        if thread is not None:
            # 2026-08-13 P1-3：已存在 thread 时本次 sync 也是新的 Phase2 命中，
            # 按合同（foreshadowing.py 注释"每次命中都落一条 hit"）补写 hit 行；
            # 幂等：同 章节 同 thread 已有 hit 时视为纯 no-op，不重复写、不制造假命中。
            existing_hit = self.session.execute(
                select(ForeshadowingThreadHit.hit_id).where(
                    ForeshadowingThreadHit.setup_id == thread.setup_id,
                    ForeshadowingThreadHit.run_id == run_id,
                    ForeshadowingThreadHit.chapter_id == chapter_id,
                )
            ).scalar_one_or_none()
            if existing_hit is not None:
                return thread, None
            now = datetime.now(UTC)
            hit = ForeshadowingThreadHit(
                setup_id=thread.setup_id,
                run_id=run_id,
                chapter_id=chapter_id,
                anchor_text=normalized,
                is_new_setup=False,
                event_id=setup_event_id,
                created_at=now,
            )
            self.session.add(hit)
            if chapter_id > thread.last_chapter_id:
                thread.last_chapter_id = chapter_id
                thread.updated_at = now
            self.session.flush()
            return thread, hit
        now = datetime.now(UTC)
        thread = ForeshadowingThread(
            setup_id=str(uuid4()),
            run_id=run_id,
            first_chapter_id=chapter_id,
            last_chapter_id=chapter_id,
            setup_summary=normalized,
            foreshadowing_type=None,
            setup_kind=None,
            expected_payoff_family=None,
            payoff_likelihood=None,
            confidence=foreshadowing.confidence,
            strength=None,
            status="open",
            active=True,
            setup_event_id=setup_event_id,
            payoff_event_id=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(thread)
        self.session.flush()
        hit = ForeshadowingThreadHit(
            setup_id=thread.setup_id,
            run_id=run_id,
            chapter_id=chapter_id,
            anchor_text=normalized,
            is_new_setup=True,
            event_id=setup_event_id,
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
        target_setup_event_id: str | None = None,
        target_payoff_event_id: str | None = None,
    ) -> CaseResolutionMapping:
        """2026-08-11 用于按 action 写入解决结果和对应目标标识

        2026-08-18：foreshadowing 动作可产生 setup_event_id/payoff_event_id 目标。
        """
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
                "setup_event_id",
                "payoff_event_id",
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
            target_setup_event_id=target_setup_event_id,
            target_payoff_event_id=target_payoff_event_id,
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
            # M9a-2：运行时 CompletionCase 保留 chunk_id 字段（值即章 chunk_id）
            "chunk_id": row.chapter_id,
            "keys": list(row.keys),
            "description": row.description,
            "target_ref": dict(row.target_ref),
            "state": row.state,
        }
    )
