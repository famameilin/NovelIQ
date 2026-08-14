"""
LTTB 保形降采样测试（设计 §9.4：降采样不丢章节边界、峰值和诊断锚点）
"""

from __future__ import annotations

import math

from src.utils.lttb import lttb_indices, sample_paragraph_curve_points


def test_lttb_returns_all_when_within_budget() -> None:
    assert lttb_indices([1.0, 2.0, 3.0], 5) == [0, 1, 2]
    assert lttb_indices([], 10) == []


def test_lttb_preserves_first_and_last() -> None:
    y = [float(i) for i in range(100)]
    indices = lttb_indices(y, 10)
    assert indices[0] == 0
    assert indices[-1] == 99
    assert len(indices) <= 10
    assert indices == sorted(indices)


def test_lttb_min_points_fallback() -> None:
    y = [float(i) for i in range(50)]
    indices = lttb_indices(y, 2)
    assert indices[0] == 0
    assert indices[-1] == 49
    assert len(indices) <= 2


def test_lttb_spike_preserved() -> None:
    """单峰数据：LTTB 应保留尖峰附近点"""
    y = [0.0] * 40 + [10.0, 0.0, 0.0]
    indices = lttb_indices(y, 8)
    # 尖峰点（索引 40）或其邻近点必须被保留（面积最大）
    assert 40 in indices or 41 in indices or 39 in indices


def test_lttb_monotonic_no_duplicates() -> None:
    y = [math.sin(i / 10) for i in range(200)]
    indices = lttb_indices(y, 20)
    assert indices == sorted(set(indices))
    assert len(indices) == 20


def test_sample_preserves_must_keep_and_respects_budget() -> None:
    points = [
        {"net_density": float(i % 5), "paragraph_id": i} for i in range(100)
    ]
    must_keep = [0, 49, 99]  # 章节边界/峰值
    indices = sample_paragraph_curve_points(
        points, 20, must_keep_indices=must_keep
    )
    for idx in must_keep:
        assert idx in indices
    assert len(indices) <= 20
    assert indices == sorted(indices)


def test_sample_no_downsample_when_budget_sufficient() -> None:
    points = [{"net_density": 0.1} for _ in range(10)]
    indices = sample_paragraph_curve_points(
        points, None, must_keep_indices=[2]
    )
    assert indices == list(range(10))
    indices = sample_paragraph_curve_points(
        points, 10, must_keep_indices=[2]
    )
    assert indices == list(range(10))


def test_sample_handles_null_values() -> None:
    """net_density 为 None 的点按 0 参与降采样，不抛异常"""
    points = [
        {"net_density": 0.5 if i % 3 else None} for i in range(60)
    ]
    indices = sample_paragraph_curve_points(
        points, 15, must_keep_indices=[0, 59]
    )
    assert 0 in indices
    assert 59 in indices
    assert len(indices) <= 15
