"""
paragraph_curves 区块（§5.5 段落曲线）

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分——从 paragraph_repository.py 提取段落曲线
写入/读取/存在性判断与每章张力聚合逻辑
说明: 纯结构搬移，不改 SQL 与聚合口径；密度列在分母为 0 时为 None
（合法观测，不伪造为零）。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from src.storage.models import Chapter, Paragraph, ParagraphCurve
from src.storage.repositories.paragraph.rows import ParagraphCurveRow


def insert_paragraph_curves(session: Session, run_id: str, rows: Sequence[ParagraphCurveRow]) -> int:
    """
    先删后插写入 run 的段落曲线行

    密度列在分母为 0 时为 None（合法观测，不伪造为零）
    """
    session.execute(delete(ParagraphCurve).where(ParagraphCurve.run_id == run_id))
    if not rows:
        return 0
    insert_rows = [
        {
            "run_id": run_id,
            "paragraph_id": row.paragraph_id,
            "pos_density": row.pos_density,
            "neg_density": row.neg_density,
            "net_density": row.net_density,
            "smoothed_net_density": row.smoothed_net_density,
            "surface_tension": row.surface_tension,
            "smoothed_surface_tension": row.smoothed_surface_tension,
        }
        for row in rows
    ]
    session.execute(insert(ParagraphCurve), insert_rows)
    return len(insert_rows)


def fetch_paragraph_curves(session: Session, run_id: str) -> Sequence[Row]:
    """读取 run 的全部段落曲线行，按 paragraph_id 升序"""
    statement = (
        select(
            ParagraphCurve.paragraph_id,
            ParagraphCurve.pos_density,
            ParagraphCurve.neg_density,
            ParagraphCurve.net_density,
            ParagraphCurve.smoothed_net_density,
            ParagraphCurve.surface_tension,
            ParagraphCurve.smoothed_surface_tension,
        )
        .where(ParagraphCurve.run_id == run_id)
        .order_by(ParagraphCurve.paragraph_id)
    )
    return session.execute(statement).all()


def fetch_chapter_tension_scores(session: Session, run_id: str) -> list[tuple[int, float]]:
    """
    每章张力 = 章内段落 surface_tension 均值（供 timeline/聚合使用）

    段落表面张力已是 run 内稳健标准化 + sigmoid 后的 [0,1] 值，
    章节值取段落均值（缺失张力数据的章由调用方兜底）。
    """
    statement = (
        select(
            Paragraph.chapter_id.label("chapter_id"),
            func.avg(ParagraphCurve.surface_tension).label("avg_tension"),
        )
        .join(
            ParagraphCurve,
            (ParagraphCurve.run_id == Paragraph.run_id) & (ParagraphCurve.paragraph_id == Paragraph.paragraph_id),
        )
        .join(
            Chapter,
            (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id),
        )
        .where(
            Paragraph.run_id == run_id,
            ParagraphCurve.surface_tension.is_not(None),
        )
        .group_by(Paragraph.chapter_id, Chapter.sequence)
        .order_by(Chapter.sequence, Paragraph.chapter_id)
    )
    rows = session.execute(statement).all()
    return [(int(row.chapter_id), float(row.avg_tension)) for row in rows]


def has_paragraph_curves(session: Session, run_id: str) -> bool:
    """run 是否存在段落曲线行"""
    statement = select(ParagraphCurve.paragraph_id).where(ParagraphCurve.run_id == run_id).limit(1)
    return session.execute(statement).scalar_one_or_none() is not None
