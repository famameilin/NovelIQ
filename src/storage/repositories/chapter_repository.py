"""
实现 ChapterRepository 类，管理章节目录与正文切片的存储和检索

2026-08-14 M9a-2：chunks 表合并进 chapters 表（正文列 text/char_offset/
char_end_offset），ChapterRepository 全部方法并入本类后删除——"chunk" 概念
自此只存在于 agent 运行时（章节正文运行时切子块，负 ID 不落库）。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from src.chapters.models import ChapterData
from src.chunking.chunker import Chunk
from src.config import settings
from src.storage.models import Chapter as ChapterModel
from src.storage.models import ChapterSummary
from src.storage.repositories.base import BaseRepository
from src.storage.repositories.paragraph import (
    get_incomplete_paragraph_embedding_paragraph_ids,
    has_paragraph_embeddings,
)
from src.storage.repositories.paragraph_repository import ParagraphRepository
from src.storage.vector_schema import validate_paragraph_embeddings_schema


class ChapterRepository(BaseRepository["ChapterModel"]):
    """章节数据 Repository（章节目录 + 正文切片）"""

    def __init__(self, session: Session):
        super().__init__(session)

    def insert_chapters(self, run_id: str, chapters: Sequence[ChapterData]) -> None:
        """批量插入章节目录，插入前先删除该 run_id 的旧数据

        2026-08-14 D8 契约：chapters 是 paragraphs/graph_facts/entity_states/
        dialogue_records/case_pool_cases/foreshadowing_threads 等下游表的 FK 父表
        （ON DELETE CASCADE），先删后插会级联清空同 run 的全部下游数据。
        **同 run 不允许重跑前序阶段**——重分析必须使用新 run_id（reanalysis 每次
        创建新 run）；若确需重建，应先显式 delete_run 清理整个 run。
        """
        self.session.execute(delete(ChapterModel).where(ChapterModel.run_id == run_id))
        models = [
            ChapterModel(
                chapter_id=chapter.chapter_id,
                sequence=chapter.sequence,
                title=chapter.title,
                display_title=chapter.display_title,
                display_index_label=chapter.display_index_label,
                level=chapter.level.value,
                start_pos=chapter.start_char,
                end_pos=chapter.end_char,
                run_id=run_id,
            )
            for chapter in chapters
        ]
        self.session.bulk_save_objects(models)

    def insert_chapter_texts(self, run_id: str, chunks: Sequence[Chunk]) -> None:
        """按章节回填正文切片（text/char_offset/char_end_offset）

        正文切片为 strip 后的 trimmed 边界（段落 global 坐标的基准）。
        结构行由 insert_chapters 先行写入（D8 契约：先删后插级联下游）；
        本方法对缺失的章节行以默认结构补建（便于独立调用/测试夹具），
        已有行只做 UPDATE 不删除。
        """
        for chunk in chunks:
            existing = self.session.scalar(
                select(ChapterModel.chapter_id).where(
                    ChapterModel.run_id == run_id,
                    ChapterModel.chapter_id == chunk.chapter_id,
                )
            )
            if existing is None:
                self.session.add(
                    ChapterModel(
                        chapter_id=chunk.chapter_id,
                        sequence=chunk.chapter_id,
                        title=f"第{chunk.chapter_id}章",
                        display_title=f"第{chunk.chapter_id}章",
                        display_index_label=None,
                        level="chapter",
                        start_pos=chunk.start,
                        end_pos=chunk.end,
                        text=chunk.text,
                        char_offset=chunk.start,
                        char_end_offset=chunk.end,
                        run_id=run_id,
                    )
                )
            else:
                self.session.execute(
                    update(ChapterModel)
                    .where(
                        ChapterModel.run_id == run_id,
                        ChapterModel.chapter_id == chunk.chapter_id,
                    )
                    .values(
                        text=chunk.text,
                        char_offset=chunk.start,
                        char_end_offset=chunk.end,
                    )
                )

    def fetch_chapters(self, run_id: str) -> Sequence[ChapterModel]:
        """按顺序读取指定 run 的章节目录"""
        stmt = (
            select(ChapterModel)
            .where(ChapterModel.run_id == run_id)
            .order_by(ChapterModel.sequence)
        )
        return self.session.execute(stmt).scalars().all()

    def fetch_chapter_texts(self, run_id: str) -> list[tuple[int, str]]:
        """获取所有有正文章节的文本，按章节 sequence 升序

        Returns:
            (chapter_id, text) 元组列表
        """
        stmt = (
            select(ChapterModel.chapter_id, ChapterModel.text)
            .where(ChapterModel.run_id == run_id, ChapterModel.text.is_not(None))
            .order_by(ChapterModel.sequence, ChapterModel.chapter_id)
        )
        result = self.session.execute(stmt)
        return [(int(row.chapter_id), str(row.text)) for row in result.fetchall()]

    def fetch_chapters_with_text(self, run_id: str) -> list[tuple[int, str]]:
        """读取标注 dispatcher 所需的章节文本（原 fetch_chapters_with_text）"""
        return self.fetch_chapter_texts(run_id)

    def fetch_chapter_counts(self, run_id: str) -> tuple[int, int]:
        """获取有正文章节的数量与总字符数

        Returns:
            (total_chapters, total_chars) 元组
        """
        stmt = select(
            func.count().label("total_chapters"),
            func.sum(func.length(ChapterModel.text)).label("total_chars"),
        ).where(ChapterModel.run_id == run_id, ChapterModel.text.is_not(None))
        result = self.session.execute(stmt)
        row = result.fetchone()
        if row is None:
            return (0, 0)
        total_chapters = row.total_chapters if row.total_chapters else 0
        total_chars = int(row.total_chars) if row.total_chars else 0
        return (int(total_chapters), total_chars)

    def fetch_all_chapter_texts(self, run_id: str) -> list[str]:
        """获取指定运行的所有章节正文文本（仅文本）"""
        stmt = (
            select(ChapterModel.text)
            .where(ChapterModel.run_id == run_id, ChapterModel.text.is_not(None))
            .order_by(ChapterModel.sequence, ChapterModel.chapter_id)
        )
        result = self.session.execute(stmt)
        return [row.text for row in result.fetchall() if row.text]

    def count_chapters(self, run_id: str) -> int:
        """统计指定运行的有正文章节数量"""
        stmt = (
            select(func.count())
            .select_from(ChapterModel)
            .where(ChapterModel.run_id == run_id, ChapterModel.text.is_not(None))
        )
        return int(self.session.execute(stmt).scalar_one() or 0)

    def fetch_prev_chapter_text(self, run_id: str, chapter_id: int) -> str | None:
        """获取上一章的正文文本（支持 rolling_memory 运行时上下文）"""
        current_sequence = self.session.scalar(
            select(ChapterModel.sequence).where(
                ChapterModel.run_id == run_id,
                ChapterModel.chapter_id == chapter_id,
            )
        )
        if current_sequence is None:
            return None
        stmt = select(ChapterModel.text).where(
            ChapterModel.run_id == run_id,
            ChapterModel.sequence < current_sequence,
            ChapterModel.text.is_not(None),
        ).order_by(ChapterModel.sequence.desc(), ChapterModel.chapter_id.desc()).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def fetch_next_chapter_text(self, run_id: str, chapter_id: int) -> str | None:
        """获取下一章的正文文本（支持 rolling_memory 运行时上下文）"""
        current_sequence = self.session.scalar(
            select(ChapterModel.sequence).where(
                ChapterModel.run_id == run_id,
                ChapterModel.chapter_id == chapter_id,
            )
        )
        if current_sequence is None:
            return None
        stmt = select(ChapterModel.text).where(
            ChapterModel.run_id == run_id,
            ChapterModel.sequence > current_sequence,
            ChapterModel.text.is_not(None),
        ).order_by(ChapterModel.sequence, ChapterModel.chapter_id).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def has_chapters(self, run_id: str) -> bool:
        """检查指定运行是否有正文章节数据"""
        stmt = (
            select(func.count())
            .select_from(ChapterModel)
            .where(ChapterModel.run_id == run_id, ChapterModel.text.is_not(None))
        )
        count = int(self.session.execute(stmt).scalar_one() or 0)
        return count > 0

    def is_preprocess_complete(self, run_id: str) -> bool:
        """
        检查预处理阶段是否完成

        当当前配置要求语义原文定位时，完成判定不再只看正文切片，
        而是要求 paragraph embedding schema 与数据完整就绪，
        避免半成品 run 被误判为 preprocess 已完成

        RAG 粒度固定为一个自然段：只检查 paragraph embeddings，不再检查 chunk embeddings
        """
        if not self.has_chapters(run_id):
            return False

        # 段落事实源完整性：paragraphs 是 run 内段落身份的唯一事实源（设计文档 §5.1），
        # 无段落行的 run 一律视为 preprocess 未完成，避免旧 run 缺段落仍被判定为可跳过
        paragraph_repo = ParagraphRepository(self.session)
        if not paragraph_repo.has_paragraphs(run_id):
            return False

        # 2026-08-15 M2：指标与曲线在 paragraphs 提交之后才分段提交，中间存在纯 CPU 窗口；
        # 只查段落行会把"窗口内被杀/崩溃的半成品 run"误判为 preprocess 完成，
        # 导致段落指标/曲线永久缺失。有段落行就必然有指标与曲线行（preprocess 无条件生成），
        # 二者缺一即判定未完成，触发完整重跑补全。
        if not paragraph_repo.has_paragraph_metrics(run_id):
            return False
        if not paragraph_repo.has_paragraph_curves(run_id):
            return False

        if not settings.models.paragraph_embedding.semantic_enabled:
            return True

        expected_dim = settings.models.paragraph_embedding.embedding_dim
        try:
            validate_paragraph_embeddings_schema(self.session, expected_dim)
        except ValueError:
            # 只要当前运行环境要求语义原文定位，而 schema 尚未就绪，就不能跳过 preprocess；
            # 否则会把缺向量的半成品 run 当成完成态，后续直接卡在 readiness
            return False

        if not has_paragraph_embeddings(self.session, run_id):
            return False
        if get_incomplete_paragraph_embedding_paragraph_ids(self.session, run_id):
            return False
        return True

    def fetch_chapter_summaries(self, run_id: str) -> Sequence[Row]:
        """获取指定运行的所有章节摘要

        Returns:
            Row 对象序列，支持字段名访问：row.chapter_id, row.summary
        """
        stmt = (
            select(ChapterSummary.chapter_id, ChapterSummary.summary)
            .join(
                ChapterModel,
                (ChapterModel.run_id == ChapterSummary.run_id)
                & (ChapterModel.chapter_id == ChapterSummary.chapter_id),
            )
            .where(ChapterSummary.run_id == run_id)
            .order_by(ChapterModel.sequence, ChapterSummary.chapter_id)
        )
        result = self.session.execute(stmt)
        return result.fetchall()
