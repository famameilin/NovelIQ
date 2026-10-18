"""当前 work 的原文读取授权与查询适配"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from src.agents.annotation.text_search import TextSearchCandidate, TextSearchService
from src.config import settings
from src.embedding import EmbeddingClient
from src.storage import Storage


class DatabaseAnnotationQueryService:
    """原文能力只通过实际查询产生，不读取案例池或可变图"""

    def __init__(
        self,
        session_factory: Callable[[], Storage],
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
            current_chapter_sequence = session.reads.agents_annotation_queries_init_1(current_chapter_id, run_id)
            if current_chapter_sequence is None:
                raise ValueError(f"当前章节不存在: chapter_id={current_chapter_id}")
            self.current_chapter_sequence = int(current_chapter_sequence)
            chapter_ids = list(session.reads.agents_annotation_queries_init_2(run_id))
            if current_chapter_id not in chapter_ids:
                raise ValueError(f"当前章节不存在: chapter_id={current_chapter_id}")
            self.current_chapter_order = chapter_ids.index(current_chapter_id) + 1
            self.chapter_orders = {chapter_id: index + 1 for index, chapter_id in enumerate(chapter_ids)}

    @contextmanager
    def _read_scope(self) -> Iterator[Storage]:
        """提供本次工具调用使用的 Storage 入口，连接与只读事务由各读取操作管理"""
        yield self._session_factory()

    async def search_text(
        self,
        query: str,
        *,
        range_name: str,
        limit: int = 50,
    ) -> list[TextSearchCandidate]:
        """2026-08-30 用于按 Chapter.sequence 在 SQL 层执行配置授权的正文范围检索

        2026-09-16 检索服务改为只读作用域内按次构造（构造函数纯赋值，零成本），
        语义检索的 HTTP 往返仍落在这一次调用里。
        返回段落级候选行；域模型（TextSearchResult）由调用方标注 agent 自行构造。
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
        return list(candidates)

    async def read_paragraph(self, paragraph_id: int, *, allow_future_context: bool) -> dict:
        """读取完整原文段落，不要求来源章节已完成标注"""

        def read() -> dict:
            with self._read_scope() as session:
                row = session.reads.agents_annotation_queries_read_1(paragraph_id, self.run_id)
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
