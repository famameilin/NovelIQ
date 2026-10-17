"""所属领域的产物完整性查询，供恢复编排调用"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import Paragraph, ParagraphMetric


def is_linguistic_complete(session: Session, run_id: str) -> bool:
    """恢复任务只复用覆盖全部段落的语言完成事实，不能把首批数据当作阶段完成

    完成事实是 paragraph_metrics.linguistic_completed_at 非空（不靠词元行数
    推断）：零词元段落同样有完成行（零词元≠未处理）。
    """
    row = (
        session.execute(
            select(
                func.count(Paragraph.paragraph_id).label("total"),
                func.count(ParagraphMetric.paragraph_id).filter(
                    ParagraphMetric.linguistic_completed_at.is_not(None)
                ).label("completed"),
            )
            .select_from(Paragraph)
            .outerjoin(
                ParagraphMetric,
                (ParagraphMetric.run_id == Paragraph.run_id)
                & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
            )
            .where(Paragraph.run_id == run_id)
        )
        .mappings()
        .one()
    )
    return row["total"] > 0 and row["completed"] == row["total"]
