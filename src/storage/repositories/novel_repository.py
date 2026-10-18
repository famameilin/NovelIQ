"小说登记及列表的物理读写，不负责上传文件或业务删除流程"

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from src.storage.models import AnalysisRun, Novel
from src.storage.repositories.base import BaseRepository


class NovelRepository(BaseRepository):
    def get(self, novel_id: str) -> Novel | None:
        return self.session.get(Novel, novel_id)

    def create(
        self,
        *,
        novel_id: str,
        filename: str,
        title: str,
        file_path: str,
        file_size: int,
        upload_time: datetime,
    ) -> None:
        self.session.add(
            Novel(
                novel_id=novel_id,
                filename=filename,
                title=title,
                file_path=file_path,
                file_size=file_size,
                upload_time=upload_time,
            )
        )

    def list_with_latest_status(self) -> list[dict[str, Any]]:
        "列表投影采用原有最新运行时间口径，返回具名记录"
        latest = (
            select(AnalysisRun.novel_id, func.max(AnalysisRun.created_at).label("latest_created_at"))
            .group_by(AnalysisRun.novel_id)
            .subquery()
        )
        latest_run = aliased(AnalysisRun)
        rows = self.session.execute(
            select(Novel, latest_run.status.label("latest_status"))
            .outerjoin(latest, Novel.novel_id == latest.c.novel_id)
            .outerjoin(
                latest_run,
                (latest_run.novel_id == latest.c.novel_id) & (latest_run.created_at == latest.c.latest_created_at),
            )
            .order_by(Novel.upload_time.desc())
        ).all()
        return [{"novel": row.Novel, "latest_status": row.latest_status} for row in rows]

    def delete(self, novel_id: str) -> bool:
        novel = self.session.get(Novel, novel_id)
        if novel is None:
            return False
        self.session.delete(novel)
        return True
