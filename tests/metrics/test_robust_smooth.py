"""
自研字符坐标稳健局部回归（LOWESS）测试

覆盖《章节粒度分析指标重设计》§9.3 与任务契约：
常数输入、线性保持、不等距 x、n<min_points 返回原始、窗口自适应扩大、
样本权重生效、空输入、长度不匹配 ValueError、robust 迭代对离群点不敏感
"""

from __future__ import annotations

import math

import pytest

from src.metrics.robust_smooth import robust_local_regression, smooth_series


class TestRobustLocalRegression:
    def test_empty_input_returns_empty(self) -> None:
        assert robust_local_regression([], []) == []
        assert smooth_series([]) == []

    def test_length_mismatch_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            robust_local_regression([0.0, 1.0, 2.0], [1.0, 2.0, 3.0, 4.0])
        with pytest.raises(ValueError):
            robust_local_regression([0.0, 1.0, 2.0], [1.0, 2.0, 3.0], weights=[1.0, 1.0])

    def test_fewer_than_min_points_returns_original(self) -> None:
        """n < min_points 返回原始序列（§9.3 第 4 条，不生成常数线）"""
        x = [0.0, 0.5, 1.0]
        y = [3.0, -1.0, 7.0]
        assert robust_local_regression(x, y) == y
        assert smooth_series(y) == y

    def test_constant_input_outputs_constant_without_nan(self) -> None:
        x = [float(i) / 20 for i in range(21)]
        y = [4.25] * 21
        result = robust_local_regression(x, y)
        assert all(math.isfinite(v) for v in result)
        assert all(abs(v - 4.25) < 1e-9 for v in result)

    def test_linear_data_on_uniform_x_stays_linear(self) -> None:
        """等间距线性数据平滑后仍线性（一次多项式局部拟合精确恢复）"""
        x = [float(i) / 29 for i in range(30)]
        y = [3.0 * xi + 1.0 for xi in x]
        result = robust_local_regression(x, y, bandwidth=0.05)
        for _xi, yi, fitted in zip(x, y, result, strict=True):
            assert fitted == pytest.approx(yi, abs=1e-6)

    def test_linear_data_on_nonuniform_x_correct(self) -> None:
        """不等距 x 上线性数据仍正确恢复（LOWESS 使用真实坐标距离）"""
        x = [0.0, 0.001, 0.05, 0.3, 0.31, 0.32, 0.9, 1.0]
        y = [5.0 * xi + 2.0 for xi in x]
        result = robust_local_regression(x, y, bandwidth=0.2)
        for yi, fitted in zip(y, result, strict=True):
            assert fitted == pytest.approx(yi, abs=1e-6)

    def test_adaptive_window_expansion_for_sparse_points(self) -> None:
        """
        窗口自适应扩大：远离簇的孤立点初始窗口只有自身，
        点过少时带宽 ×2 直到覆盖足够点（§9.3 第 3 条）
        """
        x = [0.0, 0.49, 0.51, 0.53, 0.55, 0.57, 0.59, 1.0]
        y = [0.0] * 7 + [10.0]
        result = robust_local_regression(x, y, bandwidth=0.001, min_points=7)
        # 无 NaN；若窗口未扩大，x=1.0 处单点窗口会原样返回 10.0，
        # 扩大后该点被簇（y≈0）主导，不应再是 10.0
        assert all(math.isfinite(v) for v in result)
        assert result[7] < 5.0

    def test_sample_weights_zero_point_does_not_pull(self) -> None:
        """
        样本权重生效：权重为 0 的离群点不拉偏邻域拟合

        前 10 点 y=0 权重 1，后 10 点 y=10 权重 0：
        x=0.75 处的拟合只由左侧 y=0 的点决定
        """
        x = [float(i) / 19 for i in range(20)]
        y = [0.0] * 10 + [10.0] * 10
        weights = [1.0] * 10 + [0.0] * 10

        weighted = robust_local_regression(x, y, weights=weights, bandwidth=0.5)
        unweighted = robust_local_regression(x, y, bandwidth=0.5)

        assert weighted[15] == pytest.approx(0.0, abs=0.5)
        assert unweighted[15] > 2.0
        assert all(math.isfinite(v) for v in weighted)

    def test_robust_iterations_insensitive_to_outlier(self) -> None:
        """
        robust 迭代对离群点不敏感：单个离群点不会拉弯整体

        线性趋势 + 小幅噪声中注入一个 y 离群点；robust_iters=3 时
        该点拟合值应回到趋势线附近（bisquare 残差权重将其剔除）
        """
        import random

        rng = random.Random(42)
        x = [float(i) / 49 for i in range(50)]
        y = [2.0 * xi + 1.0 + (rng.random() - 0.5) * 0.1 for xi in x]
        outlier_index = 25
        y[outlier_index] = 50.0

        robust_result = robust_local_regression(
            x, y, bandwidth=0.2, min_points=7, robust_iters=3
        )
        non_robust_result = robust_local_regression(
            x, y, bandwidth=0.2, min_points=7, robust_iters=0
        )
        # 离群点处平滑值回到真实趋势（2*0.5+1=2.0）附近，而非被拉到 50；
        # 且显著优于不做稳健化的拟合
        assert robust_result[outlier_index] == pytest.approx(2.0, abs=3.0)
        assert robust_result[outlier_index] < non_robust_result[outlier_index]
        assert all(math.isfinite(v) for v in robust_result)
        # 整体未被离群点拉弯：两端仍贴近趋势线
        assert robust_result[0] == pytest.approx(1.0, abs=1.0)
        assert robust_result[-1] == pytest.approx(3.0, abs=1.0)

    def test_smooth_series_matches_uniform_regression(self) -> None:
        """smooth_series 与 linspace 坐标的 robust_local_regression 等价"""
        values = [1.0, 2.0, 3.0, 2.0, 1.0, 2.0, 3.0, 2.0, 1.0, 2.0]
        expected = robust_local_regression(
            [float(i) / 9 for i in range(10)],
            values,
            bandwidth=0.2,
        )
        assert smooth_series(values, bandwidth=0.2) == pytest.approx(expected)

    def test_zero_bandwidth_raises_instead_of_hanging(self) -> None:
        """2026-08-15 M3 回归：带宽 ≤ 0 时入口快速失败（此前扩窗 ×2 恒不变会死循环）"""
        x = [float(i) / 9 for i in range(10)]
        y = [float(i) for i in range(10)]
        with pytest.raises(ValueError, match="bandwidth must be positive"):
            robust_local_regression(x, y, bandwidth=0.0)
        with pytest.raises(ValueError, match="bandwidth must be positive"):
            robust_local_regression(x, y, bandwidth=-0.02)

    def test_min_points_below_one_raises(self) -> None:
        """2026-08-15 M3 回归：min_points < 1 同样在入口拒绝"""
        x = [float(i) / 9 for i in range(10)]
        y = [float(i) for i in range(10)]
        with pytest.raises(ValueError, match="min_points"):
            robust_local_regression(x, y, bandwidth=0.2, min_points=0)
