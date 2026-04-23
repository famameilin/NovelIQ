from __future__ import annotations

from sqlalchemy import text

from src.storage.db import get_session_factory


def insert_test_novel(novel_id: str, *, session=None, title: str | None = None) -> None:
    """
    创建时间: 2026-04-23
    任务: 复杂度与耦合审查 P2 - 测试工程化
    说明: 为直接造 run 的 API 测试补 novels 主表记录，集中复用避免大型测试文件重复维护。
    """
    if len(novel_id) > 8:
        raise ValueError(f"test novel_id must be 8 chars or fewer, got: {novel_id}")

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
