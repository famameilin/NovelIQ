from __future__ import annotations

from types import SimpleNamespace

from src.metrics.rhythm_curve_fusion import build_display_surface_tension


def _curve_row(
    chunk_id: int,
    *,
    tension_proxy: float,
) -> SimpleNamespace:
    return SimpleNamespace(chunk_id=chunk_id, tension_proxy=tension_proxy)


def _style_row(
    chunk_id: int,
    *,
    fight_density: float = 0.0,
    exclaim_density: float = 0.0,
    question_density: float = 0.0,
    dialogue_ratio: float = 0.0,
    sent_len_std: float = 0.0,
    sensory_density: float = 0.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        chunk_id=chunk_id,
        fight_density=fight_density,
        exclaim_density=exclaim_density,
        question_density=question_density,
        dialogue_ratio=dialogue_ratio,
        sent_len_std=sent_len_std,
        sensory_density=sensory_density,
    )


def test_build_display_surface_tension_prefers_normalized_style_signal() -> None:
    curve_rows = [
        _curve_row(1, tension_proxy=0.9),
        _curve_row(2, tension_proxy=0.1),
    ]
    style_rows = [
        _style_row(1),
        _style_row(
            2,
            fight_density=0.6,
            exclaim_density=0.2,
            question_density=0.2,
            dialogue_ratio=0.4,
            sent_len_std=0.5,
            sensory_density=0.3,
        ),
    ]

    result = build_display_surface_tension(curve_rows, style_rows)

    assert result[2] > result[1]
    assert 0.0 <= result[1] <= 1.0
    assert 0.0 <= result[2] <= 1.0


def test_build_display_surface_tension_falls_back_to_raw_proxy_when_style_missing() -> None:
    curve_rows = [
        _curve_row(1, tension_proxy=0.2),
        _curve_row(2, tension_proxy=0.8),
    ]

    result = build_display_surface_tension(curve_rows, style_rows=[])

    assert result[2] > result[1]
    assert 0.0 <= result[1] <= 1.0
    assert 0.0 <= result[2] <= 1.0
