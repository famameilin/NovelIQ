"""当前工作信封的原文查询与正式标注读仓储"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.fact_graph.schema import BoundChapterAnnotation, BoundParagraphLabel, TextSearchResult
from src.storage.text_search import TextSearchService
from src.config import settings
from src.embedding import EmbeddingClient
from src.storage.models import AnalysisOutput, Chapter, Paragraph
from src.storage.repositories.base import BaseRepository


class DatabaseAnnotationQueryService:
    """原文能力只通过实际查询产生，不读取案例池或可变图"""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        run_id: str,
        current_chapter_id: int,
        current_first_paragraph_id: int,
        current_last_paragraph_id: int,
        embedding_client: EmbeddingClient | None = None,
    ):
        """2026-08-14 用于绑定单次尝试的 run 章节边界与原文检索服务

        二期段落化：边界为当前章的段落事实源边界（paragraph_id，§5.2）；
        M7 子 chunk 场景由调用方传章的段落边界，不是子块的边界。
        2026-09-16 连接粒度=单次工具调用：构造期只用一次性只读会话解析章节序与
        章序（每 agent 会话一次，与改动前同量），连接随即归还；查询方法各自在
        _read_scope() 内开只读会话，模型生成期间不占用连接。
        """
        self._session_factory = session_factory
        self._embedding_client = embedding_client
        self.run_id = run_id
        self.current_chapter_id = current_chapter_id
        self.current_first_paragraph_id = current_first_paragraph_id
        self.current_last_paragraph_id = current_last_paragraph_id
        with self._read_scope() as session:
            current_chapter_sequence = session.execute(
                select(Chapter.sequence).where(
                    Chapter.run_id == run_id,
                    Chapter.chapter_id == current_chapter_id,
                )
            ).scalar_one_or_none()
            if current_chapter_sequence is None:
                raise ValueError(f"当前章节不存在: chapter_id={current_chapter_id}")
            self.current_chapter_sequence = int(current_chapter_sequence)
            chapter_ids = list(
                session.execute(
                    select(Chapter.chapter_id)
                    .where(Chapter.run_id == run_id)
                    .order_by(Chapter.sequence, Chapter.chapter_id)
                ).scalars()
            )
            if current_chapter_id not in chapter_ids:
                raise ValueError(f"当前章节不存在: chapter_id={current_chapter_id}")
            self.current_chapter_order = chapter_ids.index(current_chapter_id) + 1

    @contextmanager
    def _read_scope(self) -> Iterator[Session]:
        """2026-09-16 用于把连接占用收敛到单次工具调用：开只读会话，返回前归还

        守卫（PostgreSQL 显式只读）从三个会话入口的内联块收进这里一处；
        SQLite 等方言没有该语句，非 PostgreSQL 绑定跳过。作用域退出时无论
        正常返回还是抛错都回滚并关闭，异常路径不泄漏连接。
        """
        session = self._session_factory()
        try:
            bind = session.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))
            yield session
        finally:
            try:
                session.rollback()
            finally:
                session.close()

    async def search_text(
        self,
        query: str,
        *,
        range_name: str,
        limit: int = 50,
    ) -> list[TextSearchResult]:
        """2026-08-30 用于按 Chapter.sequence 在 SQL 层执行配置授权的正文范围检索

        2026-09-16 检索服务改为只读作用域内按次构造（构造函数纯赋值，零成本），
        语义检索的 HTTP 往返仍落在这一次调用里。
        """
        before_chapter_sequence: int | None = None
        after_chapter_sequence: int | None = None
        if range_name == "previous":
            before_chapter_sequence = self.current_chapter_sequence
        elif range_name == "future":
            after_chapter_sequence = self.current_chapter_sequence
        elif range_name != "all":
            raise ValueError("search_text.range 只能是 previous、future 或 all")
        with self._read_scope() as session:
            candidates = await TextSearchService(
                session,
                run_id=self.run_id,
                embedding_client=self._embedding_client,
                semantic_enabled=settings.models.paragraph_embedding.semantic_enabled,
                semantic_top_k=settings.models.paragraph_embedding.top_k,
            ).search(
                query,
                before_chapter_sequence=before_chapter_sequence,
                after_chapter_sequence=after_chapter_sequence,
                limit=limit,
            )
        return [
            TextSearchResult(
                chapter_id=row.chapter_id,
                paragraph_ids=[row.paragraph_id],
                content=row.excerpt,
                keyword_score=row.keyword_score,
                semantic_score=row.semantic_score,
            )
            for row in candidates
        ]

    async def read_paragraph(self, paragraph_id: int, *, allow_future_context: bool) -> dict:
        """读取完整原文段落，不要求来源章节已完成标注"""

        def read() -> dict:
            with self._read_scope() as session:
                row = session.execute(
                    select(Paragraph, Chapter.sequence)
                    .join(
                        Chapter, ((Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id))
                    )
                    .where(Paragraph.run_id == self.run_id, Paragraph.paragraph_id == paragraph_id)
                ).one_or_none()
                if row is None:
                    raise ValueError("原文段落不属于当前分析")
                if not allow_future_context and row.sequence > self.current_chapter_sequence:
                    raise ValueError("当前原文读取范围不允许未来章节")
                paragraph = row.Paragraph
                return {
                    "chapter_id": paragraph.chapter_id,
                    "paragraph_id": paragraph.paragraph_id,
                    "text": paragraph.text,
                }

        return await asyncio.to_thread(read)


class ChapterAnnotationRepository(BaseRepository[AnalysisOutput]):
    """按成功保存的角色贡献读取章标注，不创建额外章级产物"""

    def fetch_paragraph_labels(self, run_id: str) -> list[BoundParagraphLabel]:
        """2026-09-14 用于读取全书自选段情绪标签（段落级监督按书边界）

        标签随章节标注 payload 落库；句级旧字段（sentence_labels，2026-09-07 口径）
        已从合同删除，重建库后无历史 payload 兼容问题。
        """
        from .results import chapter_annotations

        records = chapter_annotations(self.session, run_id)
        labels: list[BoundParagraphLabel] = []
        for record in records:
            annotation = BoundChapterAnnotation.model_validate(record.payload)
            labels.extend(annotation.paragraph_labels)
        return labels
