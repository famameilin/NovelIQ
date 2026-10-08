"""所属领域的产物完整性查询，供恢复编排调用"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import (
    Paragraph,
    ParagraphLinguisticFeature,
)


def is_linguistic_complete(session: Session, run_id: str) -> bool:
    """恢复任务只复用覆盖全部段落的语言特征，不能把首批数据当作阶段完成"""
    row = (
        session.execute(
            select(
                func.count(Paragraph.paragraph_id).label("total"),
                func.count(ParagraphLinguisticFeature.paragraph_id).label("completed"),
            )
            .select_from(Paragraph)
            .outerjoin(
                ParagraphLinguisticFeature,
                (ParagraphLinguisticFeature.run_id == Paragraph.run_id)
                & (ParagraphLinguisticFeature.paragraph_id == Paragraph.paragraph_id),
            )
            .where(Paragraph.run_id == run_id)
        )
        .mappings()
        .one()
    )
    return row["total"] > 0 and row["completed"] == row["total"]
