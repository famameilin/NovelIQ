"""全书指标输入的原始 SQL 读取；业务计算由 metrics 负责"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import Paragraph, ParagraphCurve, ParagraphMetric


def fetch_global_stat_rows(session: Session, run_id: str):
    return session.execute(
        select(
            Paragraph.chapter_id,
            Paragraph.text,
            Paragraph.char_count,
            ParagraphMetric.token_count,
            ParagraphMetric.sentence_count,
            ParagraphMetric.sentence_char_sum,
            ParagraphMetric.positive_weight_sum,
            ParagraphMetric.negative_weight_sum,
            ParagraphCurve.net_density,
            ParagraphCurve.surface_tension,
        )
        .join(
            ParagraphMetric,
            (ParagraphMetric.run_id == Paragraph.run_id) & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
            isouter=True,
        )
        .join(
            ParagraphCurve,
            (ParagraphCurve.run_id == Paragraph.run_id) & (ParagraphCurve.paragraph_id == Paragraph.paragraph_id),
            isouter=True,
        )
        .where(Paragraph.run_id == run_id)
        .order_by(Paragraph.global_start_char, Paragraph.paragraph_id)
    ).fetchall()
