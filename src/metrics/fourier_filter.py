"""
傅里叶变换频域滤波模块

使用离散傅里叶变换进行频域滤波平滑，保留低频分量实现数据平滑。
      参考: Matthew Jockers《畅销书写作密码》(The Bestseller Code)
"""

from __future__ import annotations

import numpy as np


def fourier_smooth(values: list[float], keep_ratio: float = 0.1) -> list[float]:
    """
    使用傅里叶变换进行频域滤波平滑。

    通过离散傅里叶变换将时域信号转换为频域，保留低频分量（代表整体趋势），
    滤除高频分量（代表噪声和细节波动），再通过逆变换得到平滑后的信号。

    参数:
        values: 原始数值序列
        keep_ratio: 保留的低频分量比例，默认 0.1（保留前 10%）
                   值越小，平滑程度越高；值越大，保留的细节越多

    返回:
        平滑后的数值序列，长度与输入相同

    参考:
        Matthew Jockers 在《畅销书写作密码》中使用傅里叶变换分析小说的
        情节节奏曲线，通过频域滤波提取情节的主要趋势。
    """
    if not values:
        return []

    if len(values) == 1:
        return values.copy()

    arr = np.array(values, dtype=np.float64)

    fft_result = np.fft.fft(arr)

    n = len(fft_result)
    keep_count = max(1, int(n * keep_ratio))

    filtered_fft = np.zeros(n, dtype=np.complex128)
    filtered_fft[:keep_count] = fft_result[:keep_count]

    if keep_count < n:
        filtered_fft[-keep_count + 1 :] = fft_result[-keep_count + 1 :]

    smoothed = np.fft.ifft(filtered_fft)

    return smoothed.real.tolist()
