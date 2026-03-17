"""
图数据存储相关操作

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 补充遗漏方法
说明: 图数据的保存和加载操作
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.storage.models import GraphStorage

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def save_graph(session: Session, run_id: str, graph_name: str, graph_json: str) -> None:
    """
    保存图数据到数据库

    Args:
        session: 数据库会话
        run_id: 运行ID
        graph_name: 图名称
        graph_json: 图的 JSON 序列化字符串
    """
    now = datetime.now().isoformat()
    stmt = (
        pg_insert(GraphStorage)
        .values(
            graph_name=graph_name,
            graph_json=graph_json,
            updated_at=now,
            run_id=run_id,
        )
        .on_conflict_do_update(
            constraint="uq_graph_storage_name_run",
            set_={
                "graph_json": graph_json,
                "updated_at": now,
            },
        )
    )
    session.execute(stmt)
    session.commit()


def load_graph(session: Session, run_id: str, graph_name: str) -> Optional[str]:
    """
    从数据库加载图数据

    Args:
        session: 数据库会话
        run_id: 运行ID
        graph_name: 图名称

    Returns:
        图的 JSON 序列化字符串，不存在则返回 None
    """
    stmt = select(GraphStorage.graph_json).where(
        GraphStorage.graph_name == graph_name,
        GraphStorage.run_id == run_id,
    )
    result = session.execute(stmt).fetchone()
    return result.graph_json if result else None
