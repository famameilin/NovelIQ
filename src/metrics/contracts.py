"""指标契约 registry：从 config/metrics_contracts.yaml 加载可执行契约。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONTRACTS_PATH = _PROJECT_ROOT / "config" / "metrics_contracts.yaml"


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


def load_metric_contracts(path: Path | None = None) -> list[MetricContract]:
    contracts_path = path or _CONTRACTS_PATH
    if not contracts_path.exists():
        raise FileNotFoundError(f"metrics contracts file not found: {contracts_path}")
    raw_data = yaml.safe_load(contracts_path.read_text(encoding="utf-8")) or {}
    return [_parse_contract(item) for item in raw_data.get("metrics", [])]


__all__ = ["MetricContract", "load_metric_contracts"]