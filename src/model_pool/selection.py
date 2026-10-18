"""按权重为每次标注尝试重新选择模型"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping

from src.config.schemas.model import WeightedModelSettings


def select_annotation_model(
    key: str,
    pool: list[WeightedModelSettings],
    *,
    previous_model_id: str | None = None,
    in_flight: Mapping[str, int] | None = None,
    failures: Mapping[str, int] | None = None,
) -> str | None:
    """尝试键决定加权选择；有其他可用模型时不重复失败的模型

    选举在模型池分发时刻发生——只在有空位的模型（在途任务数 < max_in_flight）中
    加权选举，全部满位返回 None，任务留在队列；in_flight=None 时退化为无容量
    过滤的纯加权选择。
    """
    candidates = [item for item in pool if item.weight > 0]
    if not candidates:
        raise ValueError("模型池没有正权重的标注模型")
    if in_flight is not None:
        candidates = [item for item in candidates if in_flight.get(item.model_id, 0) < item.max_in_flight]
        if not candidates:
            return None
    if failures is not None:
        lowest = min(failures.get(item.model_id, 0) for item in candidates)
        candidates = [item for item in candidates if failures.get(item.model_id, 0) == lowest]
    elif previous_model_id is not None and any(item.model_id != previous_model_id for item in candidates):
        candidates = [item for item in candidates if item.model_id != previous_model_id]
    effective = [item.weight / (1 + (failures or {}).get(item.model_id, 0)) for item in candidates]
    scale = max(effective)
    weights = [weight / scale for weight in effective]
    total = math.fsum(weights)
    fraction = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") / 2**64
    threshold = fraction * total
    for item, weight in zip(candidates, weights, strict=True):
        threshold -= weight
        if threshold < 0:
            return item.model_id
    return candidates[-1].model_id
