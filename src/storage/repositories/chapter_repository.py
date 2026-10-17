"""
实现 ChapterRepository 类，管理章节目录与正文切片的存储和检索

2026-08-14 M9a-2：chunks 表合并进 chapters 表（正文列 text/char_offset），
ChapterRepository 全部方法并入本类后删除——"chunk" 概念自此只存在于
agent 运行时（章节正文运行时切子块，负 ID 不落库）。

2026-10-16 全库 3NF 改造（35 表冻结结构）：正文切片 text 与全文起点
char_offset 与章节目录同键合并进 chapters（一对一属性）；正文终点
char_offset+字符长度(text) 为读取投影，不再落列。空正文章节 text/char_offset
同为空（CHECK 约束保证成对），正文读取按 text 非空过滤。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from sqlalchemy import ColumnElement, Table, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from src.storage.input_records import ChapterRecord as ChapterData
from src.storage.input_records import ChunkRecord as Chunk
from src.storage.models import Chapter as ChapterModel
from src.storage.repositories.base import BaseRepository


class ChapterRepository(BaseRepository["ChapterModel"]):
    """章节数据 Repository（章节目录 + 正文切片）"""

    def __init__(self, session: Session):
        super().__init__(session)

    def insert_chapters(self, run_id: str, chapters: Sequence[ChapterData]) -> None:
        """批量插入章节目录，插入前先删除该 run_id 的旧数据

        2026-08-14 D8 契约：chapters 是 paragraphs/graph_facts/dialogue_records/
        case_pool_cases 等下游表的 FK 父表（ON DELETE CASCADE），先删后插会级联
        清空同 run 的全部下游数据。**同 run 不允许重跑前序阶段**——重分析必须使用
        新 run_id（reanalysis 每次创建新 run）；若确需重建，应先显式 delete_run
        清理整个 run。
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
        """按章节回填正文切片（chapters.char_offset/text，与目录同键一行）

        正文切片为 strip 后的 trimmed 边界（段落 global 坐标的基准）。
        结构行由 insert_chapters 先行写入（D8 契约：先删后插级联下游）；
        本方法对缺失的章节行以默认结构补建（便于独立调用/测试夹具），
        已有章节行只 upsert 正文，不删除章节结构行。
        """
        existing_ids = set(
            self.session.scalars(
                select(ChapterModel.chapter_id).where(ChapterModel.run_id == run_id)
            ).all()
        )
        for chunk in chunks:
            if chunk.chapter_id in existing_ids:
                continue
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
                    run_id=run_id,
                )
            )
            existing_ids.add(chunk.chapter_id)
        if chunks:
            # 章节行先落，正文 upsert 依赖其存在
            self.session.flush()

        if not chunks:
            return

        # 正文列与目录同键：按最新章节覆盖（text/char_offset 成对，不做半写）
        # __table__ 静态类型是 FromClause，运行期是映射的真实 Table（Konflikt 目标需要它）
        statement = pg_insert(cast(Table, ChapterModel.__table__)).values(
            [
                {
                    "run_id": run_id,
                    "chapter_id": chunk.chapter_id,
                    "sequence": chunk.chapter_id,
                    "title": f"第{chunk.chapter_id}章",
                    "display_title": f"第{chunk.chapter_id}章",
                    "display_index_label": None,
                    "level": "chapter",
                    "start_pos": chunk.start,
                    "end_pos": chunk.end,
                    "char_offset": chunk.start,
                    "text": chunk.text,
                }
                for chunk in chunks
            ]
        )
        statement = statement.on_conflict_do_update(
            index_elements=["run_id", "chapter_id"],
            set_={
                "char_offset": statement.excluded.char_offset,
                "text": statement.excluded.text,
            },
        )
        self.session.execute(statement)

    def fetch_chapters(self, run_id: str) -> Sequence[ChapterModel]:
        """按顺序读取指定 run 的章节目录"""
        stmt = select(ChapterModel).where(ChapterModel.run_id == run_id).order_by(ChapterModel.sequence)
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

    def fetch_chapter_bodies(self, run_id: str) -> Sequence[Row]:
        """获取 run 的章节正文行（章序 + 正文起点 + 正文终点投影 + 文本）

        2026-10-16 3NF：正文终点 = char_offset + 字符长度(text)，读取投影不落列；
        按章节 sequence 升序。
        """
        stmt = (
            select(
                ChapterModel.chapter_id,
                ChapterModel.sequence,
                ChapterModel.char_offset,
                # char_length(NULL)=NULL 由库内函数语义表达；空正文章节 text 为空是同一口径
                (ChapterModel.char_offset + func.char_length(cast(ColumnElement[str], ChapterModel.text))).label(
                    "char_end_offset"
                ),
                ChapterModel.text,
            )
            .where(ChapterModel.run_id == run_id)
            .order_by(ChapterModel.sequence, ChapterModel.chapter_id)
        )
        return self.session.execute(stmt).all()

    def fetch_chapter_counts(self, run_id: str) -> tuple[int, int]:
        """获取有正文章节的数量与总字符数

        Returns:
            (total_chapters, total_chars) 元组
        """
        stmt = select(
            func.count().label("total_chapters"),
            func.sum(func.char_length(cast(ColumnElement[str], ChapterModel.text))).label("total_chars"),
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
        """统计指定运行的有正文章节数量（空正文章节无正文，不计入）"""
        stmt = (
            select(func.count())
            .select_from(ChapterModel)
            .where(ChapterModel.run_id == run_id, ChapterModel.text.is_not(None))
        )
        return int(self.session.execute(stmt).scalar_one() or 0)

    def has_chapters(self, run_id: str) -> bool:
        """检查指定运行是否有正文数据"""
        stmt = (
            select(func.count())
            .select_from(ChapterModel)
            .where(ChapterModel.run_id == run_id, ChapterModel.text.is_not(None))
        )
        count = int(self.session.execute(stmt).scalar_one() or 0)
        return count > 0
