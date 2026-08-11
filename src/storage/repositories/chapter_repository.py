"""
实现 ChapterRepository 类，管理章节目录的存储和检索

章节表存储章节结构解析（src.chapters）的完整输出，
chunks 表通过 chapter_id 引用有正文章节。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.chapters.models import ChapterData
from src.storage.models import Chapter as ChapterModel
from src.storage.repositories.base import BaseRepository


class ChapterRepository(BaseRepository["ChapterModel"]):
    """章节数据 Repository"""

    def __init__(self, session: Session):
        super().__init__(session)

    def insert_chapters(self, run_id: str, chapters: Sequence[ChapterData]) -> None:
        """批量插入章节目录，插入前先删除该 run_id 的旧数据"""
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

    def fetch_chapters(self, run_id: str) -> Sequence[ChapterModel]:
        """按顺序读取指定 run 的章节目录"""
        stmt = (
            select(ChapterModel)
            .where(ChapterModel.run_id == run_id)
            .order_by(ChapterModel.sequence)
        )
        return self.session.execute(stmt).scalars().all()

    def count_chapters(self, run_id: str) -> int:
        """统计指定 run 的章节数量"""
        stmt = select(func.count()).select_from(ChapterModel).where(ChapterModel.run_id == run_id)
        return int(self.session.execute(stmt).scalar_one() or 0)
