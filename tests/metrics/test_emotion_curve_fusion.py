from __future__ import annotations

from types import SimpleNamespace

from src.metrics.emotion_curve_fusion import build_display_emotion_curve


def _curve_row(
    chunk_id: int,
    *,
    pos_density: float = 0.0,
    neg_density: float = 0.0,
    net_density: float = 0.0,
    smoothed_density: float = 0.0,
    tension_proxy: float = 0.0,
    tension_composite: float = 0.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        chunk_id=chunk_id,
        pos_density=pos_density,
        neg_density=neg_density,
        net_density=net_density,
        smoothed_density=smoothed_density,
        tension_proxy=tension_proxy,
        tension_composite=tension_composite,
    )


def test_build_display_emotion_curve_keeps_ai_negative_when_lexical_is_zero() -> None:
    curve_rows = [_curve_row(1)]
    annotation_rows = [SimpleNamespace(chunk_id=1, emotional_valence="strong_negative")]

    result = build_display_emotion_curve(
        curve_rows=curve_rows,
        annotation_rows=annotation_rows,
        style_rows=[],
        dialogue_rows=[],
    )

    assert len(result) == 1
    assert result[0].net_density < 0
    assert result[0].neg_density > 0


def test_build_display_emotion_curve_uses_lexical_signal_when_ai_is_neutral() -> None:
    curve_rows = [_curve_row(1, pos_density=0.03, neg_density=0.0, net_density=0.03)]
    annotation_rows = [SimpleNamespace(chunk_id=1, emotional_valence="neutral")]

    result = build_display_emotion_curve(
        curve_rows=curve_rows,
        annotation_rows=annotation_rows,
        style_rows=[],
        dialogue_rows=[],
    )

    assert len(result) == 1
    assert result[0].pos_density > 0
    assert result[0].net_density > 0


def test_build_display_emotion_curve_preserves_true_neutral_gap() -> None:
    curve_rows = [_curve_row(1)]
    annotation_rows = [SimpleNamespace(chunk_id=1, emotional_valence="neutral")]

    result = build_display_emotion_curve(
        curve_rows=curve_rows,
        annotation_rows=annotation_rows,
        style_rows=[],
        dialogue_rows=[],
    )

    assert len(result) == 1
    assert result[0].pos_density == 0
    assert result[0].neg_density == 0
    assert result[0].net_density == 0


def test_build_display_emotion_curve_keeps_conflict_signal_without_reversing_ai_direction() -> None:
    curve_rows = [_curve_row(1, pos_density=0.0, neg_density=0.04, net_density=-0.04)]
    annotation_rows = [SimpleNamespace(chunk_id=1, emotional_valence="mild_positive")]
    dialogue_rows = [SimpleNamespace(chunk_id=1, tone="强硬")]

    result = build_display_emotion_curve(
        curve_rows=curve_rows,
        annotation_rows=annotation_rows,
        style_rows=[],
        dialogue_rows=dialogue_rows,
    )

    assert len(result) == 1
    assert result[0].pos_density > 0
    assert result[0].neg_density > 0
    assert result[0].net_density > 0
