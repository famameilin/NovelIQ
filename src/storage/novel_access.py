"小说记录的具名访问能力"

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.storage.input_boundary import plain_inputs
from src.storage.records.models import NovelRecord
from src.storage.repositories.novel_repository import NovelRepository


@plain_inputs
class NovelAccess:
    def __init__(self, runner):
        self._runner = runner

    def get(self, novel_id: str) -> NovelRecord | None:
        "读取小说普通快照"
        return self._runner.run(lambda session: NovelRepository(session).get(novel_id), read_only=True)

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
        "登记上传结果并在返回前提交"
        self._runner.run(
            lambda session: NovelRepository(session).create(
                novel_id=novel_id,
                filename=filename,
                title=title,
                file_path=file_path,
                file_size=file_size,
                upload_time=upload_time,
            )
        )

    def list_with_latest_status(self) -> list[dict[str, Any]]:
        "读取小说与最新任务状态的普通记录"
        return self._runner.run(lambda session: NovelRepository(session).list_with_latest_status(), read_only=True)

    def delete(self, novel_id: str) -> bool:
        "完成单次小说登记删除；外键依赖尚未清除时整体失败"
        return self._runner.run(lambda session: NovelRepository(session).delete(novel_id))
