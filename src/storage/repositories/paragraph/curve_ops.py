"""
段落曲线区块（§5.5 段落曲线 / §5.2 计算合同与读投影）

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分——从 paragraph_repository.py 提取段落曲线
说明: 纯结构搬移，不改 SQL 与聚合口径；密度列在分母为 0 时为 None
（合法观测，不伪造为零）。

2026-10-16 全库 3NF 改造（35 表冻结结构）：
- 旧宽表 paragraph_curves 退场：逐段 LOWESS 平滑结果写 paragraph_features 的
  lowess_net_density / lowess_surface_tension 两类标量行（NULL 保留不可计算
  语义）；批次完成事实写 analysis_runs.curve_completed_at
- 原始 pos/neg 密度与 net_density 不再落列，由指标分子÷同口径 token_count
  投影；surface_tension 由 paragraph_features 的 tension_z 观测按 sigmoid 投影；
  写入时的 pos/neg/net/surface_tension 字段一律忽略
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Table, delete, func, select, update
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, aliased

from src.config import settings
from src.storage.models import AnalysisRun, Chapter, Paragraph, ParagraphFeature, ParagraphMetric
from src.storage.repositories.metric_inputs import (
    FEATURE_TENSION_Z,
    density_projection,
    net_density_projection,
    surface_tension_projection,
)
from src.storage.repositories.paragraph.rows import ParagraphCurveRow

#: 曲线种类（paragraph_features 封闭 feature_code）
CURVE_KIND_NET_DENSITY = "lowess_net_density"
CURVE_KIND_SURFACE_TENSION = "lowess_surface_tension"

_LOWESS_FEATURE_CODES = (CURVE_KIND_NET_DENSITY, CURVE_KIND_SURFACE_TENSION)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def insert_paragraph_curves(session: Session, run_id: str, rows: Sequence[ParagraphCurveRow]) -> int:
    """
    先删后插写入 run 的段落曲线平滑结果（paragraph_features 两类标量行）

    平滑值按 lowess_net_density / lowess_surface_tension 两个既有序列写入，
    None 保留 NULL；行本身携带的密度与 surface_tension 是读投影来源，不落库。
    批次与运行级曲线合同（完成时间与 LOWESS 参数）在 analysis_runs 一并登记。
    """
    session.execute(
        delete(ParagraphFeature).where(
            ParagraphFeature.run_id == run_id,
            ParagraphFeature.feature_code.in_(_LOWESS_FEATURE_CODES),
        )
    )
    # 运行级曲线合同与实际批次完成事实一并登记（参数是本次实际使用的 settings 值）
    session.execute(
        update(AnalysisRun)
        .where(AnalysisRun.run_id == run_id)
        .values(
            curve_completed_at=_utcnow(),
            curve_bandwidth=float(settings.metrics.lowess_bandwidth),
            curve_min_points=int(settings.metrics.lowess_min_points),
        )
    )
    if not rows:
        # 空输入也是真实执行结果（无段落），完成事实已随合同登记
        return 0
    feature_rows = [
        {
            "run_id": run_id,
            "paragraph_id": int(row.paragraph_id),
            "feature_code": feature_code,
            "scalar_value": smoothed_value,
        }
        for row in rows
        for feature_code, smoothed_value in (
            (CURVE_KIND_NET_DENSITY, row.smoothed_net_density),
            (CURVE_KIND_SURFACE_TENSION, row.smoothed_surface_tension),
        )
        if smoothed_value is not None
    ]
    if feature_rows:
        # __table__ 静态类型是 FromClause，运行期是映射的真实 Table（行插入需要它）
        session.execute(
            cast(Table, ParagraphFeature.__table__).insert(),
            feature_rows,
        )
    return len(rows)


def fetch_paragraph_curves(session: Session, run_id: str) -> Sequence[Row]:
    """读取 run 的全部段落曲线行，按 paragraph_id 升序

    行集合为已有曲线平滑样本的段落（与旧曲线行一致）；pos/neg/net 密度与
    surface_tension 由指标分子/分母与张力 z 读投影给出，平滑值取特征行。
    """
    sample_net = aliased(ParagraphFeature, name="sample_net")
    sample_tension = aliased(ParagraphFeature, name="sample_tension")
    statement = (
        select(
            ParagraphMetric.paragraph_id,
            density_projection(ParagraphMetric.positive_weight_sum).label("pos_density"),
            density_projection(ParagraphMetric.negative_weight_sum).label("neg_density"),
            net_density_projection().label("net_density"),
            sample_net.scalar_value.label("smoothed_net_density"),
            surface_tension_projection().label("surface_tension"),
            sample_tension.scalar_value.label("smoothed_surface_tension"),
        )
        .select_from(ParagraphMetric)
        .join(
            ParagraphFeature,
            (ParagraphFeature.run_id == ParagraphMetric.run_id)
            & (ParagraphFeature.paragraph_id == ParagraphMetric.paragraph_id)
            & (ParagraphFeature.feature_code == FEATURE_TENSION_Z),
            isouter=True,
        )
        .join(
            sample_net,
            (sample_net.run_id == ParagraphMetric.run_id)
            & (sample_net.paragraph_id == ParagraphMetric.paragraph_id)
            & (sample_net.feature_code == CURVE_KIND_NET_DENSITY),
            isouter=True,
        )
        .join(
            sample_tension,
            (sample_tension.run_id == ParagraphMetric.run_id)
            & (sample_tension.paragraph_id == ParagraphMetric.paragraph_id)
            & (sample_tension.feature_code == CURVE_KIND_SURFACE_TENSION),
            isouter=True,
        )
        .where(
            ParagraphMetric.run_id == run_id,
            (sample_net.paragraph_id.is_not(None)) | (sample_tension.paragraph_id.is_not(None)),
        )
        .order_by(ParagraphMetric.paragraph_id)
    )
    return session.execute(statement).all()


def fetch_chapter_tension_scores(session: Session, run_id: str) -> list[tuple[int, float]]:
    """
    每章张力 = 章内段落 surface_tension 均值（供 timeline/聚合使用）

    段落表面张力已是 run 内稳健标准化 + sigmoid 后的 [0,1] 值，
    章节值取段落均值（缺失张力数据的章由调用方兜底）；先投影 sigmoid
    再求均值，保持原「逐段值平均」口径。
    """
    tension = surface_tension_projection()
    statement = (
        select(
            Paragraph.chapter_id.label("chapter_id"),
            func.avg(tension).label("avg_tension"),
        )
        .select_from(Paragraph)
        .join(
            ParagraphFeature,
            (ParagraphFeature.run_id == Paragraph.run_id)
            & (ParagraphFeature.paragraph_id == Paragraph.paragraph_id)
            & (ParagraphFeature.feature_code == FEATURE_TENSION_Z),
        )
        .join(
            Chapter,
            (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id),
        )
        .where(
            Paragraph.run_id == run_id,
            ParagraphFeature.scalar_value.is_not(None),
        )
        .group_by(Paragraph.chapter_id, Chapter.sequence)
        .order_by(Chapter.sequence, Paragraph.chapter_id)
    )
    rows = session.execute(statement).all()
    return [(int(row.chapter_id), float(row.avg_tension)) for row in rows]


def has_paragraph_curves(session: Session, run_id: str) -> bool:
    """run 是否存在段落曲线平滑样本行（曲线阶段实际产出过结果）"""
    statement = (
        select(ParagraphFeature.paragraph_id)
        .where(
            ParagraphFeature.run_id == run_id,
            ParagraphFeature.feature_code.in_(_LOWESS_FEATURE_CODES),
        )
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none() is not None
