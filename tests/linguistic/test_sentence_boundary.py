"""句级情绪边界单测（2026-09-07 句级监督按书边界）"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.linguistic.sentence_boundary import (
    fit_sentence_boundary,
    score_sentences,
    strong_negative_share,
)


def _deterministic_vectors(emotions: list[int], dim: int = 8) -> np.ndarray:
    """按情绪分值构造可分句向量：正向沿 e0、负向沿 -e0、中性接近原点扰动"""
    vectors = []
    rng = np.random.default_rng(7)
    for emotion in emotions:
        vector = rng.normal(scale=0.01, size=dim)
        if emotion > 0:
            vector[0] += 1.0
        elif emotion < 0:
            vector[0] -= 1.0
        vectors.append(vector)
    return np.array(vectors, dtype=np.float32)


@pytest.mark.parametrize(
    ("emotions", "expect_fits"),
    [
        ([2, 1, 0, -2], True),
        ([0, 0], False),
        ([-2], False),
    ],
)
def test_fit_sentence_boundary_gatekeeping(emotions: list[str], *, expect_fits: bool) -> None:
    """标签分值有变化才拟合；不足 2 条或全同分值返回 None 不伪造边界"""
    boundary = fit_sentence_boundary(_deterministic_vectors(emotions), emotions)
    assert (boundary is not None) is expect_fits


def test_fit_and_score_recovers_polarity_order() -> None:
    """正类向量分值高、负类分值低、强负低于强正（分值方向单调）"""
    emotions = [2, 1, 0, -1, -2]
    boundary = fit_sentence_boundary(_deterministic_vectors(emotions), emotions)
    assert boundary is not None
    scores = score_sentences(boundary, _deterministic_vectors(emotions))
    assert all(score is not None for score in scores)
    ordered = [float(score) for score in scores]
    assert ordered[0] > ordered[1] > ordered[2] > ordered[3] > ordered[4]
    assert boundary.sample_count == len(emotions)


def test_score_sentences_dimension_mismatch_returns_none() -> None:
    """维度不匹配按 None 处理，不伪造分值"""
    boundary = fit_sentence_boundary(
        _deterministic_vectors([2, -2]),
        [2, -2],
    )
    assert boundary is not None
    wrong_dim = np.zeros((1, len(boundary.weights) + 1), dtype=np.float32)
    scores = score_sentences(boundary, wrong_dim)
    assert scores == [None]


def test_strong_negative_share_threshold_and_empty() -> None:
    """p≥0.8 强分层：分值 ≤ -0.8 计强负；全 None 返回 None"""
    assert strong_negative_share([-0.9, -0.5, 1.2, None]) == pytest.approx(1 / 3)
    assert strong_negative_share([None, None]) is None
