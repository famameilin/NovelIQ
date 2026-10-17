"""诊断素材的原始 SQL 查询，领域规则和产物读取由诊断查询负责

2026-10-16 全库 3NF 改造（35 表冻结结构）：章节原文改从 chapters.text 读取
（正文切片与章节目录同键一对一，chapter_bodies 退场）；高张力段落改按
paragraph_features 的 tension_z 正式观测（sigmoid 读投影）排序，不再依赖
已退场的曲线宽表。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import (
    Chapter,
    Paragraph,
    ParagraphFeature,
    ParagraphMetric,
    ParagraphTopic,
)
from src.storage.repositories.base import BaseRepository
from src.storage.repositories.metric_inputs import (
    FEATURE_TENSION_Z,
    surface_tension_projection,
)


class DiagnosisRepository(BaseRepository["DiagnosisRepository"]):
    def __init__(self, session: Session):
        """2026-08-05 用于初始化诊断事实查询仓储"""
        super().__init__(session)

    def _text_by_chapter_id(self, run_id: str) -> dict[int, str]:
        """2026-08-20 用于构建诊断素材的章节原文映射（正文切片与章节目录同键）"""
        stmt = select(Chapter.chapter_id, Chapter.text).where(
            Chapter.run_id == run_id, Chapter.text.is_not(None)
        )
        return {int(row.chapter_id): str(row.text) for row in self.session.execute(stmt).all()}

    def fetch_high_tension_chunks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, float]]:
        """2026-08-14 M8a：高张力诊断数据源为正式表面张力读数（§12.3 事实定位段落化）。

        按 paragraph_features 的 tension_z 行现存 sigmoid 读投影排序
        （run 内稳健标准化 + sigmoid，章节级旧复合指数不再参与排序；text 取 paragraphs.text。
        NULL 处理保持原有行为：NULL 参与比较结果为 NULL，被 > 0.01 过滤条件排除。
        """
        row_limit = limit if limit is not None else 10
        tension_expr = surface_tension_projection(ParagraphFeature.scalar_value)
        stmt = (
            select(Paragraph.paragraph_id, Paragraph.text, tension_expr.label("tension"))
            .select_from(Paragraph)
            .join(
                ParagraphFeature,
                (ParagraphFeature.run_id == Paragraph.run_id)
                & (ParagraphFeature.paragraph_id == Paragraph.paragraph_id)
                & (ParagraphFeature.feature_code == FEATURE_TENSION_Z),
            )
            .where(
                tension_expr > 0.01,
                Paragraph.run_id == run_id,
            )
            .order_by(tension_expr.desc())
            .limit(row_limit)
        )
        return [(int(row.paragraph_id), str(row.text), float(row.tension)) for row in self.session.execute(stmt)]

    def fetch_topic_weights(self, run_id: str, top_n: int | None = None) -> list[dict[str, Any]]:
        row_limit = top_n
        # §5.11：分母/token 从段落指标行读取，不在段主题表重复保存
        weighted_sum = func.sum(ParagraphTopic.topic_weight * ParagraphMetric.inference_token_count)
        stmt = (
            select(
                ParagraphTopic.topic_id,
                weighted_sum.label("weighted_total"),
            )
            .join(
                ParagraphMetric,
                (ParagraphMetric.run_id == ParagraphTopic.run_id)
                & (ParagraphMetric.paragraph_id == ParagraphTopic.paragraph_id),
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
