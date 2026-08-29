"""指标契约 registry:从 src/config/constants 的 METRIC_CONTRACTS 加载可执行契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.config.constants import METRIC_CONTRACTS


@dataclass(frozen=True)
class MetricContract:
    id: str
    concept: str
    problem: str
    fields: tuple[str, ...]
    endpoint: str
    category: str
    objective_subjective: str
    authoritative: bool
    null_semantics: str
    computation_chain: str
    invariants: tuple[str, ...]


def _parse_contract(raw: dict[str, Any]) -> MetricContract:
    return MetricContract(
        id=str(raw["id"]),
        concept=str(raw["concept"]),
        problem=str(raw["problem"]),
        fields=tuple(str(field) for field in raw.get("fields", [])),
        endpoint=str(raw.get("endpoint", "")),
        category=str(raw.get("category", "")),
        objective_subjective=str(raw.get("objective_subjective", "")),
        authoritative=bool(raw.get("authoritative", False)),
        null_semantics=str(raw.get("null_semantics", "")),
        computation_chain=str(raw.get("computation_chain", "")),
        invariants=tuple(str(item) for item in raw.get("invariants", [])),
    )


def load_metric_contracts(raw: list[dict[str, Any]] | None = None) -> list[MetricContract]:
    """读取指标契约;raw 为可选的契约声明列表(缺省用 constants 内置注册表)"""
    source = METRIC_CONTRACTS if raw is None else raw
    return [_parse_contract(item) for item in source]


__all__ = ["MetricContract", "load_metric_contracts"]
