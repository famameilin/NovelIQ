"""
LTTB（Largest-Triangle-Three-Buckets）保形降采样

用于段落曲线 API 的展示降采样（设计文档《章节粒度分析指标重设计》§9.4）：
- 完整曲线始终一段一点，原始与平滑指标计算使用全量段落
- 降采样只影响传输与绘图，不参与指标计算，结果不回写数据库
- 章节边界点与诊断锚点必须强制保留（由调用方传入，见
  sample_paragraph_curve_points）
"""

from __future__ import annotations

from collections.abc import Sequence


def lttb_indices(
    y: Sequence[float],
    max_points: int,
) -> list[int]:
    """
    标准 LTTB：返回保留点的索引列表（含首尾）

    - len(y) <= max_points：返回全部索引
    - max_points < 3：退化为保留首尾 + 均匀间隔补齐
    - y 中不含 NaN（调用方先过滤）；点数不足时返回全量
    """
    n = len(y)
    if n == 0:
        return []
    if n <= max_points:
        return list(range(n))
    if max_points < 3:
        # 预算不足 3 点时退化为保留首尾（端点即诊断锚点）
        return [0, n - 1]

    sampled: list[int] = [0]
    bucket_size = (n - 2) / (max_points - 2)
    prev_selected = 0

    for bucket_index in range(max_points - 2):
        bucket_start = 1 + int(bucket_index * bucket_size)
        bucket_end = 1 + int((bucket_index + 1) * bucket_size)
        bucket_end = min(bucket_end, n - 1)
        if bucket_start >= bucket_end:
            continue

        # 下一桶均值（三角形面积计算的目标点）
        if bucket_index < max_points - 3:
            next_start = 1 + int((bucket_index + 1) * bucket_size)
            next_end = min(1 + int((bucket_index + 2) * bucket_size), n - 1)
            next_mean_y = sum(y[next_start:next_end]) / max(len(y[next_start:next_end]), 1)
        else:
            next_mean_y = y[-1]

        prev_x, prev_y = float(prev_selected), float(y[prev_selected])
        next_x = float(bucket_index + 1)
        best_idx = bucket_start
        best_area = -1.0
        for idx in range(bucket_start, bucket_end):
            area = abs((prev_x - next_x) * (y[idx] - prev_y) - (prev_x - idx) * (next_mean_y - prev_y))
            if area > best_area:
                best_area = area
                best_idx = idx
        sampled.append(best_idx)
        prev_selected = best_idx

    sampled.append(n - 1)
    return sampled


def sample_paragraph_curve_points(
    points: Sequence[dict],
    max_points: int | None,
    *,
    must_keep_indices: Sequence[int],
    value_key: str = "net_density",
) -> list[int]:
    """
    段落曲线保形降采样：返回保留点的索引列表

    - max_points 为 None 或 >= 总点数：返回全部索引
    - must_keep_indices（章节边界、峰值、诊断锚点）无条件保留；
      其余点按 LTTB 补齐到 max_points 预算
    - value_key 用于 LTTB 的 y 值（缺省 net_density，None 值点按 0 参与）
    """
    n = len(points)
    if max_points is None or max_points >= n:
        return list(range(n))
    budget = max(max_points - len(must_keep_indices), 3)
    keep_set = set(must_keep_indices)

    y_values: list[float] = []
    for point in points:
        raw_value = point.get(value_key)
        y_values.append(float(raw_value) if raw_value is not None else 0.0)
    candidates = [i for i in range(n) if i not in keep_set]
    if not candidates:
        return sorted(keep_set)

    sampled = lttb_indices([y_values[i] for i in candidates], budget)
    selected = {candidates[i] for i in sampled}
    selected.update(keep_set)
    return sorted(selected)
