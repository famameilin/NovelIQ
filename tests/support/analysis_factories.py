from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.storage.db import get_session_factory


def insert_test_novel(novel_id: str, *, session=None, title: str | None = None) -> None:
    """为直接造 run 的 API 测试补 novels 主表记录"""
    if UUID(novel_id).version != 7:
        raise ValueError("测试小说身份必须是 UUIDv7")

    statement = text(
        """
        INSERT INTO novels (novel_id, title, filename, file_path)
        VALUES (:novel_id, :title, :filename, :file_path)
        ON CONFLICT (novel_id) DO NOTHING
        """
    )
    payload = {
        "novel_id": novel_id,
        "title": title or novel_id,
        "filename": f"{novel_id}.txt",
        "file_path": f"data/uploads/{novel_id}.txt",
    }

    if session is not None:
        session.execute(statement, payload)
        session.commit()
        return

    with get_session_factory()() as local_session:
        local_session.execute(statement, payload)
        local_session.commit()
