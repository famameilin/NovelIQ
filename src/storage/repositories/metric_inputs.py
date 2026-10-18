"""全书指标输入的原始 SQL 读取；业务计算由 metrics 负责

本模块给出读投影的唯一定义，供指标/曲线/主题各存取点复用：

- char_count：段落正文精确字符长度（与 Python ``len`` 同口径）
- pos/neg_density：权重分子 ÷ 同口径 token_count；token=0 或指标缺失保持 NULL
- net_density：正密度 − 负密度（NULL 分量保持 NULL）
- surface_tension：paragraph_features 的 tension_z 观测按 sigmoid 投影
  （数值稳定等价式，NULL→NULL）
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import SQLCoreOperations

from src.storage.models import Chapter, Paragraph, ParagraphFeature, ParagraphMetric

#: 表层张力 z 的 feature_code（paragraph_features 封闭计算种类）
FEATURE_TENSION_Z = "tension_z"


def char_count_projection(text_column: SQLCoreOperations[str] = Paragraph.text) -> ColumnElement[int]:
    """正文长度读投影：PostgreSQL ``length`` 按字符计数，不落同表派生列"""
    return func.length(text_column)


def global_start_char_projection(
    *,
    local_start_column: SQLCoreOperations[int] = Paragraph.local_start_char,
    char_offset_column: SQLCoreOperations[int | None] = Chapter.char_offset,
) -> ColumnElement[int | None]:
    """全文起点读投影：所属章节正文起点 + 章内起点（需已连接 chapters）

    空正文章节无 char_offset，位置口径保持 NULL（不补 0）。
    """
    return char_offset_column + local_start_column


def density_projection(
    molecule_column: SQLCoreOperations[float | None],
    token_count_column: SQLCoreOperations[int | None] = ParagraphMetric.token_count,
) -> ColumnElement[float | None]:
    """密度读投影：分子 ÷ 同口径 token_count；分母为零或指标缺失一律 NULL，不补 0"""
    return molecule_column / func.nullif(token_count_column, 0)


def net_density_projection() -> ColumnElement[float | None]:
    """净密度读投影：正密度 − 负密度，NULL 分量保持 NULL"""
    return density_projection(ParagraphMetric.positive_weight_sum) - density_projection(
        ParagraphMetric.negative_weight_sum
    )


def surface_tension_projection(
    z_column: SQLCoreOperations[float | None] = ParagraphFeature.scalar_value,
) -> ColumnElement[float | None]:
    """表面张力读投影：对正式 tension_z 观测应用 sigmoid，保留数值稳定与 NULL 语义

    z >= 0 用 1/(1+exp(-z))、z < 0 用 exp(z)/(1+exp(z))，避免指数溢出；
    z 为 NULL 时两条分支均为 NULL，不把缺失变成 sigmoid(0)=0.5。
    调用方必须连接 paragraph_features 的 tension_z 行（见 tension_z_feature_join）。
    """
    return case(
        (z_column >= 0.0, 1.0 / (1.0 + func.exp(-z_column))),
        else_=func.exp(z_column) / (1.0 + func.exp(z_column)),
    )


def tension_z_feature_join(statement, *, run_column, paragraph_column, isouter: bool = True):
    """连接段落张力 z 特征行（feature_code='tension_z'，scalar_value 为 z）

    run_column/paragraph_column 为左侧关系的 (run_id, paragraph_id) 列；
    外连接时无观测为 NULL。
    """
    return statement.join(
        ParagraphFeature,
        (ParagraphFeature.run_id == run_column)
        & (ParagraphFeature.paragraph_id == paragraph_column)
        & (ParagraphFeature.feature_code == FEATURE_TENSION_Z),
        isouter=isouter,
    )


def fetch_global_stat_rows(session: Session, run_id: str):
    """全书统计的段落级输入行（按 paragraph_id 升序，与全文顺序一致）

    char_count 取正文长度投影，net_density/surface_tension 取读投影；
    指标行或张力 z 特征行缺失时对应值为 NULL。
    """
    return session.execute(
        select(
            Paragraph.chapter_id,
            Paragraph.text,
            char_count_projection().label("char_count"),
            ParagraphMetric.token_count,
            ParagraphMetric.sentence_count,
            ParagraphMetric.sentence_char_sum,
            ParagraphMetric.positive_weight_sum,
            ParagraphMetric.negative_weight_sum,
            net_density_projection().label("net_density"),
            surface_tension_projection().label("surface_tension"),
        )
        .join(
            ParagraphMetric,
            (ParagraphMetric.run_id == Paragraph.run_id) & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
            isouter=True,
        )
        .join(
            ParagraphFeature,
            (ParagraphFeature.run_id == Paragraph.run_id)
            & (ParagraphFeature.paragraph_id == Paragraph.paragraph_id)
            & (ParagraphFeature.feature_code == FEATURE_TENSION_Z),
            isouter=True,
        )
        .where(Paragraph.run_id == run_id)
        .order_by(Paragraph.paragraph_id)
    ).fetchall()
