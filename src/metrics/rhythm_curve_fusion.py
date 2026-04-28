"""
为结果展示层构建表层张力曲线，保持 raw tension_proxy 导出语义不变

本模块不改写 chunk_curves 表中的 tension_proxy，仅基于已有的：
- chunk_style 的 fight/exclaim/question/dialogue/sentence variance/sensory 信号
- chunk_curves 的 raw tension_proxy

构建面向前端展示的 surface_tension
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.config import settings
from src.metrics.fourier_filter import fourier_smooth

_SURFACE_TENSION_WEIGHTS: dict[str, float] = {
    "fight_density": 0.35,
    "exclaim_density": 0.15,
    "question_density": 0.10,
    "dialogue_ratio": 0.15,
    "sent_len_std": 0.15,
    "sensory_density": 0.10,
}
_RAW_PROXY_BLEND = 0.15


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """
    约束展示层张力值范围，避免平滑后轻微越界
    """
    return max(low, min(high, value))


def _normalize_feature_series(values: Mapping[int, float]) -> dict[int, float]:
    """
    对单个特征按全书 chunk 做 min-max 归一化，强调相对起伏而非绝对量纲
    """
    if not values:
        return {}

    min_value = min(values.values())
    max_value = max(values.values())
    denom = max_value - min_value
    if denom <= 0:
        return dict.fromkeys(values, 0.0)
    return {chunk_id: (value - min_value) / denom for chunk_id, value in values.items()}


def build_display_surface_tension(
    curve_rows: Sequence[Any],
    style_rows: Sequence[Any],
) -> dict[int, float]:
    """
    构建面向结果展示的表层张力曲线

    融合策略：
    - 以 chunk_style 的表层信号为主，按 chunk 级做归一化后加权
    - raw tension_proxy 只做弱回退，避免 style 缺失时整条展示线塌成 0
    - 最终曲线做傅里叶平滑，保持和综合张力的视觉节奏一致
    """
    if not curve_rows:
        return {}

    style_map = {int(row.chunk_id): row for row in style_rows}

    normalized_feature_maps: dict[str, dict[int, float]] = {}
    for feature_name in _SURFACE_TENSION_WEIGHTS:
        feature_values = {
            chunk_id: float(getattr(row, feature_name, 0.0) or 0.0) for chunk_id, row in style_map.items()
        }
        normalized_feature_maps[feature_name] = _normalize_feature_series(feature_values)

    raw_proxy_values = {int(row.chunk_id): float(getattr(row, "tension_proxy", 0.0) or 0.0) for row in curve_rows}
    normalized_raw_proxy = _normalize_feature_series(raw_proxy_values)

    chunk_ids: list[int] = []
    raw_scores: list[float] = []

    for row in curve_rows:
        chunk_id = int(row.chunk_id)
        style_row = style_map.get(chunk_id)
        style_signal = sum(
            weight * normalized_feature_maps[feature_name].get(chunk_id, 0.0)
            for feature_name, weight in _SURFACE_TENSION_WEIGHTS.items()
        )
        raw_proxy_signal = normalized_raw_proxy.get(chunk_id, 0.0)

        # 表层张力以 style 信号为主，只借用 raw proxy 保持缺失样本和历史 run 的连续性，
        # 避免重新把旧的粗糙 proxy 当成主导指标
        if style_row is None:
            score = raw_proxy_signal
        else:
            score = style_signal * (1.0 - _RAW_PROXY_BLEND) + raw_proxy_signal * _RAW_PROXY_BLEND

        chunk_ids.append(chunk_id)
        raw_scores.append(score)

    smoothed_scores = fourier_smooth(
        raw_scores,
        keep_ratio=settings.metrics.fourier_smooth_keep_ratio,
    )
    return {chunk_id: _clamp(smoothed_scores[index]) for index, chunk_id in enumerate(chunk_ids)}
