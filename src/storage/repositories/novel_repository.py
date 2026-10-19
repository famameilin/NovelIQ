"小说登记及列表的物理读写，不负责上传文件或业务删除流程"

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from src.storage.models import Novel, Run
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
        "按 UUIDv7 运行身份取得最新任务状态"
        latest = (
            select(Run.novelid, Run.id.label("latest_id"))
            .distinct(Run.novelid)
            .order_by(Run.novelid, Run.id.desc())
            .subquery()
        )
        rows = self.session.execute(
            select(Novel, Run.status.label("latest_status"))
            .outerjoin(latest, Novel.novel_id == latest.c.novelid)
            .outerjoin(Run, Run.id == latest.c.latest_id)
            .order_by(Novel.upload_time.desc())
        )
        return [{"novel": row.Novel, "latest_status": row.latest_status} for row in rows]

    def delete(self, novel_id: str) -> bool:
        novel = self.session.get(Novel, novel_id)
        if novel is None:
            return False
        self.session.delete(novel)
        return True
