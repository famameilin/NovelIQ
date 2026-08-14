"""
段落曲线计算（设计《章节粒度分析指标重设计》§5.5 / §9）

从段落事实源（paragraphs 的坐标/字符权重）与段落指标（paragraph_metrics 的
分子/分母/表层张力）按 paragraph_id 对齐出逐段曲线行：

- pos/neg/net 密度：分子/分母（token_count 为 0 时不伪造，密度为 None，§15.2）
- position：段落字符中点 / 全书字符数（§9.1）
- smoothed_net_density / smoothed_surface_tension：字符坐标上的 LOWESS 平滑
  （§9.3，样本权重 = char_count，参数默认取 settings.metrics.lowess_*）
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.config import settings
from src.metrics.robust_smooth import robust_local_regression
from src.storage.repositories.paragraph_repository import ParagraphCurveRow


def _smooth_mapped(
    positions: Sequence[float],
    values: Sequence[float | None],
    sample_weights: Sequence[float],
    bandwidth: float,
    min_points: int,
) -> list[float | None]:
    """
    对非 None 点集做 robust_local_regression，映射回全量（被剔除点 None）

    n < min_points 时回归函数直接返回原始序列，与 §9.3 第 4 条一致
    （少于最少有效点不生成常数线）。
    """
    valid = [
        (i, positions[i], float(value))
        for i, value in enumerate(values)
        if value is not None
    ]
    if not valid:
        return [None] * len(values)
    fitted = robust_local_regression(
        [position for _, position, _ in valid],
        [value for _, _, value in valid],
        weights=[sample_weights[index] for index, _, _ in valid],
        bandwidth=bandwidth,
        min_points=min_points,
    )
    smoothed: list[float | None] = [None] * len(values)
    for (index, _, _), value in zip(valid, fitted, strict=True):
        smoothed[index] = value
    return smoothed


def compute_paragraph_curves(
    paragraphs: Sequence[Any],
    metric_rows: Sequence[Any],
    total_chars: int,
    weights: Sequence[float] | None = None,
    bandwidth: float | None = None,
    min_points: int | None = None,
) -> list[ParagraphCurveRow]:
    """
    计算 run 的段落曲线行

    Args:
        paragraphs: fetch_paragraph_rows 结果行（paragraph_id/global_start_char/
            global_end_char/char_count/token_count），按 paragraph_id 对齐
        metric_rows: fetch_paragraph_metrics（或同等内存行）结果（paragraph_id/
            positive_weight_sum/negative_weight_sum/token_count/surface_tension）
        total_chars: 全书字符数；<= 0 时 position 全为 0
        weights: 平滑样本权重，None 时取段落 char_count（§9.1）
        bandwidth: LOWESS 带宽（全文比例），None 时取 settings.metrics.lowess_bandwidth
        min_points: LOWESS 最少有效点数，None 时取 settings.metrics.lowess_min_points

    Returns:
        按 paragraphs 顺序的 ParagraphCurveRow 列表；缺任一侧（段落行缺指标行、
        指标行无对应段落）的段落跳过
    """
    bw = settings.metrics.lowess_bandwidth if bandwidth is None else bandwidth
    mp = settings.metrics.lowess_min_points if min_points is None else min_points
    if weights is not None and len(weights) != len(paragraphs):
        raise ValueError(
            f"weights length mismatch: len(weights)={len(weights)} "
            f"len(paragraphs)={len(paragraphs)}"
        )

    metric_by_id = {int(row.paragraph_id): row for row in metric_rows}

    aligned_paragraphs: list[Any] = []
    positions: list[float] = []
    pos_densities: list[float | None] = []
    neg_densities: list[float | None] = []
    net_densities: list[float | None] = []
    surface_tensions: list[float | None] = []
    sample_weights: list[float] = []

    for index, paragraph in enumerate(paragraphs):
        metric = metric_by_id.get(int(paragraph.paragraph_id))
        if metric is None:
            # 指标行缺失：无法计算密度，跳过该段落
            continue
        if total_chars > 0:
            position = (
                (float(paragraph.global_start_char) + float(paragraph.global_end_char))
                / 2.0
                / float(total_chars)
            )
        else:
            position = 0.0
        token_count = int(metric.token_count or 0)
        if token_count > 0:
            pos_density = float(metric.positive_weight_sum or 0.0) / token_count
            neg_density = float(metric.negative_weight_sum or 0.0) / token_count
            net_density = pos_density - neg_density
        else:
            # §15.2 分母为零不伪造
            pos_density = None
            neg_density = None
            net_density = None

        aligned_paragraphs.append(paragraph)
        positions.append(position)
        pos_densities.append(pos_density)
        neg_densities.append(neg_density)
        net_densities.append(net_density)
        surface_tensions.append(
            float(metric.surface_tension) if metric.surface_tension is not None else None
        )
        if weights is not None:
            sample_weights.append(float(weights[index]))
        else:
            sample_weights.append(float(paragraph.char_count))

    smoothed_net = _smooth_mapped(
        positions, net_densities, sample_weights, bandwidth=bw, min_points=mp
    )
    smoothed_tension = _smooth_mapped(
        positions, surface_tensions, sample_weights, bandwidth=bw, min_points=mp
    )

    return [
        ParagraphCurveRow(
            paragraph_id=int(paragraph.paragraph_id),
            pos_density=pos_densities[i],
            neg_density=neg_densities[i],
            net_density=net_densities[i],
            smoothed_net_density=smoothed_net[i],
            surface_tension=surface_tensions[i],
            smoothed_surface_tension=smoothed_tension[i],
        )
        for i, paragraph in enumerate(aligned_paragraphs)
    ]
