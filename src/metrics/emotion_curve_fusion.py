"""
创建时间: 2026-04-21
修改者: Codex
任务: fuse-display-emotion-curve
说明: 为结果展示层构建 AI 主导、词汇/语气/风格辅助的情绪曲线。

本模块不改写 chunk_curves 表中的词汇曲线存储，只负责把已有的：
- chunk_annotation.emotional_valence
- chunk_curves 词汇情绪密度
- chunk_dialogues.tone
- chunk_style 风格信号

融合为面向前端单曲线展示的最终情绪走势。
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.config import settings
from src.config.constants.annotation import EMOTION_SCORE_MAPPING
from src.metrics.fourier_filter import fourier_smooth

_ANNOTATION_SIGNAL_MAP: dict[str, float] = {
    "strong_positive": 0.78,
    "mild_positive": 0.36,
    "neutral": 0.0,
    "mild_negative": -0.36,
    "strong_negative": -0.78,
}

_TONE_SIGNAL_MAP: dict[str, float] = {
    "温和": 0.15,
    "强硬": -0.25,
    "讽刺": -0.2,
    "恳求": -0.15,
    "命令": -0.25,
    "恐惧": -0.45,
    "惊慌": -0.4,
}

_LEXICAL_DENSITY_SCALE = 0.02


@dataclass(slots=True)
class DisplayEmotionCurvePoint:
    """
    创建时间: 2026-04-21
    修改者: Codex
    任务: fuse-display-emotion-curve
    说明: 展示层情绪曲线点，保留字段名访问，避免下标式消费。
    """

    chunk_id: int
    pos_density: float
    neg_density: float
    net_density: float
    smoothed_density: float
    tension_proxy: float | None
    tension_composite: float | None
    surface_tension: float | None = None


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """
    创建时间: 2026-04-21
    修改者: Codex
    任务: fuse-display-emotion-curve
    说明: 限制数值范围，避免融合后曲线越界。
    """
    return max(low, min(high, value))


def _normalize_lexical_density(value: float | None) -> float:
    """
    创建时间: 2026-04-21
    修改者: Codex
    任务: fuse-display-emotion-curve
    说明: 将词汇密度映射到 0-1 区间，降低长 chunk 对密度的过度稀释影响。
    """
    raw_value = float(value or 0.0)
    if raw_value <= 0:
        return 0.0
    return raw_value / (raw_value + _LEXICAL_DENSITY_SCALE)


def _soft_positive(value: float, scale: float = 1.2) -> float:
    """
    创建时间: 2026-04-21
    修改时间: 2026-04-21
    任务: soften-display-emotion-curve
    新建原因: 展示层曲线需要保留强弱差异，但不能因为单个强标签长期贴住 1.0。
    """
    return 1.0 - math.exp(-max(value, 0.0) * scale)


def _soft_signed(value: float, scale: float = 1.35) -> float:
    """
    创建时间: 2026-04-21
    修改时间: 2026-04-21
    任务: soften-display-emotion-curve
    新建原因: 对最终趋势做软饱和压缩，让强情绪仍然明显，但不再出现大片平顶/平底。
    """
    return math.tanh(value * scale)


def _tone_signal(tones: Sequence[str]) -> tuple[float, float]:
    """
    创建时间: 2026-04-21
    修改者: Codex
    任务: fuse-display-emotion-curve
    说明: 聚合对话语气的方向与强度，方向用于辅助判定，强度用于补充显性情绪热度。
    """
    values = [_TONE_SIGNAL_MAP[tone] for tone in tones if tone in _TONE_SIGNAL_MAP]
    if not values:
        return 0.0, 0.0
    direction = sum(values) / len(values)
    intensity = sum(abs(value) for value in values) / len(values)
    return direction, intensity


def _style_intensity(style_row: Any | None) -> float:
    """
    创建时间: 2026-04-21
    修改者: Codex
    任务: fuse-display-emotion-curve
    说明: 将感官、惊叹和对话占比折算为弱情绪强度信号，避免无显式情绪词时整段完全归零。
    """
    if style_row is None:
        return 0.0

    sensory_density = float(getattr(style_row, "sensory_density", 0.0) or 0.0)
    exclaim_density = float(getattr(style_row, "exclaim_density", 0.0) or 0.0)
    dialogue_ratio = float(getattr(style_row, "dialogue_ratio", 0.0) or 0.0)
    return _clamp(sensory_density * 10.0 + exclaim_density * 8.0 + dialogue_ratio * 0.25, high=0.6)


def _annotation_signal(emotional_valence: str | None) -> float:
    """
    创建时间: 2026-04-21
    修改者: Codex
    任务: fuse-display-emotion-curve
    说明: 将五档情绪标签映射为主导方向信号，保持 Phase1 的判断权重高于其他辅助特征。
    """
    if emotional_valence is None:
        return 0.0
    return _ANNOTATION_SIGNAL_MAP.get(emotional_valence, EMOTION_SCORE_MAPPING.get(emotional_valence, 0) / 2.0)


def build_display_emotion_curve(
    curve_rows: Sequence[Any],
    annotation_rows: Sequence[Any],
    style_rows: Sequence[Any],
    dialogue_rows: Sequence[Any],
    surface_tension_by_chunk: Mapping[int, float] | None = None,
) -> list[DisplayEmotionCurvePoint]:
    """
    创建时间: 2026-04-21
    修改者: Codex
    任务: fuse-display-emotion-curve
    说明: 构建面向结果展示的融合情绪曲线。

    融合策略：
    - AI 标注 emotional_valence 决定主方向
    - lexical pos/neg 提供显式词汇支撑与冲突信号
    - dialogue tone 与 style intensity 只做辅助，不推翻 AI 主判
    - 通过软饱和压缩减少 1/-1 平台，让曲线更接近连续趋势而不是分档状态
    - neutral 且缺少词汇信号时允许回到 0，保持真正平缓段落的留白
    """
    if not curve_rows:
        return []

    surface_tension_by_chunk = surface_tension_by_chunk or {}
    annotation_map = {row.chunk_id: row for row in annotation_rows}
    style_map = {row.chunk_id: row for row in style_rows}

    dialogue_tone_map: dict[int, list[str]] = defaultdict(list)
    for row in dialogue_rows:
        tone = getattr(row, "tone", None)
        chunk_id = getattr(row, "chunk_id", None)
        if chunk_id is None or not tone:
            continue
        dialogue_tone_map[int(chunk_id)].append(str(tone))

    fused_rows: list[DisplayEmotionCurvePoint] = []
    fused_net_values: list[float] = []

    for row in curve_rows:
        chunk_id = int(row.chunk_id)
        lexical_pos = _normalize_lexical_density(getattr(row, "pos_density", None))
        lexical_neg = _normalize_lexical_density(getattr(row, "neg_density", None))
        lexical_strength = max(lexical_pos, lexical_neg)
        lexical_balance = lexical_pos - lexical_neg

        annotation_row = annotation_map.get(chunk_id)
        ai_signal = _annotation_signal(getattr(annotation_row, "emotional_valence", None) if annotation_row else None)

        tone_direction, tone_intensity = _tone_signal(dialogue_tone_map.get(chunk_id, []))
        style_intensity = _style_intensity(style_map.get(chunk_id))
        support_intensity = _clamp(
            lexical_strength * 0.55 + tone_intensity * 0.2 + style_intensity * 0.25,
            high=0.75,
        )
        support_direction = lexical_balance * 0.6 + tone_direction * 0.25

        pos_value = 0.0
        neg_value = 0.0
        if ai_signal > 0:
            dominant_intensity = abs(ai_signal)
            positive_raw = (
                dominant_intensity * 0.72
                + support_intensity * 0.28
                + lexical_pos * 0.16
                + max(tone_direction, 0.0) * 0.08
            )
            negative_raw = lexical_neg * 0.42 + max(-tone_direction, 0.0) * 0.18 + style_intensity * 0.08
            pos_value = _soft_positive(positive_raw)
            neg_value = _soft_positive(negative_raw)
        elif ai_signal < 0:
            dominant_intensity = abs(ai_signal)
            negative_raw = (
                dominant_intensity * 0.72
                + support_intensity * 0.28
                + lexical_neg * 0.16
                + max(-tone_direction, 0.0) * 0.08
            )
            positive_raw = lexical_pos * 0.42 + max(tone_direction, 0.0) * 0.18 + style_intensity * 0.08
            neg_value = _soft_positive(negative_raw)
            pos_value = _soft_positive(positive_raw)
        else:
            # 中文注释：当 AI 判中性时，不强行制造方向；只让显式词汇和语气提供弱偏向，
            # 这样真正平稳段落仍能保持接近 0，而隐性情绪不至于全部消失。
            positive_raw = lexical_pos * 0.68 + max(tone_direction, 0.0) * 0.24 + style_intensity * 0.1
            negative_raw = lexical_neg * 0.68 + max(-tone_direction, 0.0) * 0.24 + style_intensity * 0.1
            pos_value = _soft_positive(positive_raw)
            neg_value = _soft_positive(negative_raw)

        raw_trend = ai_signal * 0.72 + support_direction * 0.28
        if ai_signal == 0.0:
            raw_trend += lexical_balance * 0.18
        raw_trend += (pos_value - neg_value) * 0.12
        net_value = _soft_signed(raw_trend)
        fused_net_values.append(net_value)
        fused_rows.append(
            DisplayEmotionCurvePoint(
                chunk_id,
                pos_value,
                neg_value,
                net_value,
                0.0,
                getattr(row, "tension_proxy", None),
                getattr(row, "tension_composite", None),
                surface_tension_by_chunk.get(chunk_id),
            )
        )

    smoothed_values = fourier_smooth(
        fused_net_values,
        keep_ratio=settings.metrics.fourier_smooth_keep_ratio,
    )

    return [
        DisplayEmotionCurvePoint(
            chunk_id=row.chunk_id,
            pos_density=row.pos_density,
            neg_density=row.neg_density,
            net_density=row.net_density,
            smoothed_density=smoothed_values[index],
            tension_proxy=row.tension_proxy,
            tension_composite=row.tension_composite,
            surface_tension=row.surface_tension,
        )
        for index, row in enumerate(fused_rows)
    ]
