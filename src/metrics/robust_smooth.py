"""字符坐标 LOWESS 平滑（§9.3）：以归一化位置为 x、char_count 为权重，带宽按全文比例自适应；n<min 返原始。"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _tricube_weights(distances: np.ndarray, h: float) -> np.ndarray:
    """
    tricube 核权重：tricube(u) = (1 - |u|³)³，u = d / h

    distances 由窗口掩码保证 |d| <= h，这里 clip 只做数值防御
    """
    u = np.clip(distances / h, -1.0, 1.0)
    return (1.0 - u * u * u) ** 3


def _local_regression_fit(
    xa: np.ndarray,
    ya: np.ndarray,
    sample_w: np.ndarray,
    bandwidth: float,
    min_points: int,
) -> np.ndarray:
    """
    逐点加权局部线性回归（一次多项式），拟合值取 x_i 处的预测值

    窗口：初始带宽为 bandwidth，窗口内点数不足 min_points 时自适应扩大
    （每次 ×2）直到满足或覆盖全部点；每个点的样本权重为
    tricube 核权重 × 样本权重。退化情形（权重和 <= 0）返回原值，
    保证输出不含 NaN。闭式解分母加 1e-12 正则防止病态。
    """
    n = int(xa.shape[0])
    span = float(xa[-1] - xa[0])
    fitted = np.empty(n, dtype=np.float64)
    for i in range(n):
        dx = xa - xa[i]
        h = bandwidth
        while True:
            mask = np.abs(dx) <= h
            # h <= 0 时窗口无法定义且 h *= 2.0 恒不变（死循环）：直接退出，
            # 退化为当前点的局部窗口（后续加权均值分支返回原值，不伪造）
            if int(mask.sum()) >= min_points or h >= span or h <= 0:
                break
            h *= 2.0
        d = dx[mask]
        ww = sample_w[mask] * _tricube_weights(d, h)
        sw = float(ww.sum())
        if sw <= 0.0:
            # 窗口内有效权重为零（如样本权重全 0），返回原值，不伪造
            fitted[i] = ya[i]
            continue
        yw = ya[mask]
        swd = float(ww @ d)
        swd2 = float(ww @ (d * d))
        swy = float(ww @ yw)
        swdy = float(ww @ (d * yw))
        denom = sw * swd2 - swd * swd
        if denom <= 0.0:
            # 窗口内 x 退化（单点或全部重合），退化为加权均值
            slope = 0.0
        else:
            slope = (swdy * sw - swy * swd) / (denom + 1e-12)
        # 自变量已以 x_i 为中心，x_i 处预测值即截距
        intercept = (swy - slope * swd) / (sw + 1e-12)
        fitted[i] = intercept
    return fitted


def robust_local_regression(
    x: Sequence[float],
    y: Sequence[float],
    weights: Sequence[float] | None = None,
    bandwidth: float = 0.02,
    min_points: int = 7,
    robust_iters: int = 3,
) -> list[float]:
    """字符坐标 LOWESS 平滑；空输入返 []，n<min 返原始，无 NaN，长度不匹配抛错。"""
    xa = np.asarray(x, dtype=np.float64)
    ya = np.asarray(y, dtype=np.float64)
    if xa.ndim != 1 or ya.ndim != 1:
        raise ValueError("x and y must be one-dimensional sequences")
    if xa.shape[0] != ya.shape[0]:
        raise ValueError(f"x and y length mismatch: len(x)={xa.shape[0]} len(y)={ya.shape[0]}")
    # 2026-08-15 M3：非正带宽无法定义窗口（且自适应扩窗 h *= 2.0 恒不变会死循环），
    # 配置错误应在入口快速失败而不是挂死分析进程
    if bandwidth <= 0:
        raise ValueError(f"bandwidth must be positive, got {bandwidth}")
    if min_points < 1:
        raise ValueError(f"min_points must be at least 1, got {min_points}")
    n = int(xa.shape[0])
    if n == 0:
        return []
    if weights is None:
        sample_w = np.ones(n, dtype=np.float64)
    else:
        sample_w = np.asarray(weights, dtype=np.float64)
        if sample_w.shape != (n,):
            raise ValueError(f"weights length mismatch: len(weights)={sample_w.shape[0]} len(x)={n}")
    if n < min_points:
        return ya.tolist()

    fitted = _local_regression_fit(xa, ya, sample_w, bandwidth, min_points)
    if robust_iters > 0:
        for _ in range(robust_iters):
            residuals = ya - fitted
            median_abs_residual = float(np.median(np.abs(residuals)))
            if median_abs_residual <= 0.0:
                # 残差全为零，拟合已精确，无需继续稳健化
                break
            # 残差为浮点噪声量级时（如完美线性数据 + 单个离群点），
            # 直接除以 6*median 会把正常点也压成 0 权重导致稳健化失效；
            # 加 1e-12 绝对下限防止退化（与回归正则化同量级，不影响真实噪声数据）
            scale = 6.0 * median_abs_residual + 1e-12
            u = residuals / scale
            robust_w = np.where(np.abs(u) < 1.0, (1.0 - u * u) ** 2, 0.0)
            fitted = _local_regression_fit(xa, ya, sample_w * robust_w, bandwidth, min_points)
    return [float(value) for value in fitted]


def smooth_series(
    values: Sequence[float],
    bandwidth: float = 0.02,
    min_points: int = 7,
) -> list[float]:
    """
    等间距包装：x = linspace(0, 1, n) 的 robust_local_regression

    用于 chunk 链路（无真实字符坐标）替代 fourier_smooth 的过渡调用点，
    行为语义与 robust_local_regression 一致（空输入返回 []、n < min_points
    返回原始序列、无 NaN）。
    """
    value_list = list(values)
    n = len(value_list)
    if n == 0:
        return []
    x = np.linspace(0.0, 1.0, n).tolist()
    return robust_local_regression(x, value_list, bandwidth=bandwidth, min_points=min_points)
