"""段落曲线（§5.5/§9/§15.2）：按 paragraph_id 对齐计算密度、位置及 LOWESS 平滑。"""

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
    """对非 None 子集 LOWESS 后映射回全量（n<min 返原始，§9.3）。"""
    valid = [(i, positions[i], float(value)) for i, value in enumerate(values) if value is not None]
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
    """按 paragraph_id 对齐计算段落曲线（密度/位置/LOWESS）。"""
    bw = settings.metrics.lowess_bandwidth if bandwidth is None else bandwidth
    mp = settings.metrics.lowess_min_points if min_points is None else min_points
    if weights is not None and len(weights) != len(paragraphs):
        raise ValueError(f"weights length mismatch: len(weights)={len(weights)} len(paragraphs)={len(paragraphs)}")

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
                (float(paragraph.global_start_char) + float(paragraph.global_end_char)) / 2.0 / float(total_chars)
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
        surface_tensions.append(float(metric.surface_tension) if metric.surface_tension is not None else None)
        if weights is not None:
            sample_weights.append(float(weights[index]))
        else:
            sample_weights.append(float(paragraph.char_count))

    smoothed_net = _smooth_mapped(positions, net_densities, sample_weights, bandwidth=bw, min_points=mp)
    smoothed_tension = _smooth_mapped(positions, surface_tensions, sample_weights, bandwidth=bw, min_points=mp)

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
