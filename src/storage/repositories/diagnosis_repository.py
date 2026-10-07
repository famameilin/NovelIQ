"""诊断素材的原始 SQL 查询，领域规则和产物读取由诊断查询负责"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.storage.models import Chapter, Paragraph, ParagraphCurve, ParagraphTopic, ParagraphTopicInference
from src.storage.repositories.base import BaseRepository


class DiagnosisRepository(BaseRepository["DiagnosisRepository"]):
    def __init__(self, session: Session):
        """2026-08-05 用于初始化诊断事实查询仓储"""
        super().__init__(session)

    def _text_by_chapter_id(self, run_id: str) -> dict[int, str]:
        """2026-08-20 用于构建诊断素材的章节原文映射"""
        stmt = select(Chapter.chapter_id, Chapter.text).where(Chapter.run_id == run_id)
        return {int(row.chapter_id): str(row.text) for row in self.session.execute(stmt).all()}

    def fetch_high_tension_chunks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, float]]:
        """2026-08-14 M8a：高张力诊断数据源切换为段落曲线（§12.3 事实定位段落化）。

        按 paragraph_curves.surface_tension 原始值排序（run 内稳健标准化 + sigmoid，
            章节级旧复合指数不再参与排序；text 取 paragraphs.text。
        NULL 处理保持原有行为：NULL 参与比较结果为 NULL，被 > 0.01 过滤条件排除。
        """
        row_limit = limit if limit is not None else 10
        tension_expr = ParagraphCurve.surface_tension.label("tension")
        stmt = (
            select(Paragraph.paragraph_id, Paragraph.text, tension_expr)
            .select_from(Paragraph)
            .join(
                ParagraphCurve,
                and_(
                    Paragraph.paragraph_id == ParagraphCurve.paragraph_id,
                    Paragraph.run_id == ParagraphCurve.run_id,
                ),
            )
            .where(
                ParagraphCurve.surface_tension > 0.01,
                ParagraphCurve.run_id == run_id,
                Paragraph.run_id == run_id,
            )
            .order_by(tension_expr.desc())
            .limit(row_limit)
        )
        return [(int(row.paragraph_id), str(row.text), float(row.tension)) for row in self.session.execute(stmt)]

    def fetch_topic_weights(self, run_id: str, top_n: int | None = None) -> list[dict[str, Any]]:
        row_limit = top_n
        # §5.11：分母/token 从每段一行的推断状态读取，不在此表重复保存
        weighted_sum = func.sum(ParagraphTopic.topic_weight * ParagraphTopicInference.inference_token_count)
        stmt = (
            select(
                ParagraphTopic.topic_id,
                weighted_sum.label("weighted_total"),
            )
            .join(
                ParagraphTopicInference,
                (ParagraphTopicInference.run_id == ParagraphTopic.run_id)
                & (ParagraphTopicInference.paragraph_id == ParagraphTopic.paragraph_id),
            )
            .where(ParagraphTopic.run_id == run_id)
            .group_by(ParagraphTopic.topic_id)
            .order_by(weighted_sum.desc())
        )
        rows = [
            {
                "topic_id": row.topic_id,
                "weight": round(row.weighted_total, 4) if row.weighted_total else 0.0,
            }
            for row in self.session.execute(stmt).all()[:row_limit]
        ]
        return rows
