"""按权重为每次标注尝试重新选择模型"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping

from src.config.schemas.model import WeightedModelSettings
from src.model_pool.health import DEFAULT_SCORE, MIN_SELECT_SCORE


def select_annotation_model(
    key: str,
    pool: list[WeightedModelSettings],
    *,
    in_flight: Mapping[str, int] | None = None,
    failures: Mapping[str, int] | None = None,
    scores: Mapping[str, float] | None = None,
    min_score: float = MIN_SELECT_SCORE,
) -> str | None:
    """按配置权重除以一加失败次数选举有空位且健康分达标的模型

    全部满位或全部低于健康阈值时返回 None，健康分达标的失败模型保持参选资格
    """
    candidates = [item for item in pool if item.weight > 0]
    if not candidates:
        raise ValueError("模型池没有正权重的标注模型")
    if in_flight is not None:
        candidates = [item for item in candidates if in_flight.get(item.model_id, 0) < item.max_in_flight]
    if scores is not None:
        candidates = [
            item for item in candidates if scores.get(item.model_id, DEFAULT_SCORE) >= min_score
        ]
    if not candidates:
        return None
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
