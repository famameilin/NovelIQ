from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.models.cloud.schema import CloudAnalysis


@dataclass(frozen=True)
class ReportMeta:
    novel_id: str | None
    title: str | None
    author: str | None
    genre: str | None

    def to_dict(self) -> dict:
        return {
            "novel_id": self.novel_id,
            "title": self.title,
            "author": self.author,
            "genre": self.genre,
        }


@dataclass(frozen=True)
class DimensionSummary:
    name: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    notes: str | None = None

    def validate(self) -> None:
        if not self.name:
            raise ValueError("dimension name required")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "metrics": dict(self.metrics),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ChartSeries:
    name: str
    x: List[float] = field(default_factory=list)
    y: List[float] = field(default_factory=list)

    def validate(self) -> None:
        if len(self.x) != len(self.y):
            raise ValueError("series length mismatch")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "x": list(self.x),
            "y": list(self.y),
        }


@dataclass(frozen=True)
class ChartData:
    title: str
    kind: str
    series: List[ChartSeries] = field(default_factory=list)

    def validate(self) -> None:
        if not self.title:
            raise ValueError("chart title required")
        if not self.kind:
            raise ValueError("chart kind required")
        for item in self.series:
            item.validate()

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "kind": self.kind,
            "series": [item.to_dict() for item in self.series],
        }


@dataclass(frozen=True)
class ReportPayload:
    meta: ReportMeta
    dimensions: List[DimensionSummary] = field(default_factory=list)
    charts: List[ChartData] = field(default_factory=list)
    cloud_analysis: CloudAnalysis | None = None

    def validate(self) -> None:
        for dimension in self.dimensions:
            dimension.validate()
        for chart in self.charts:
            chart.validate()

    def to_dict(self) -> dict:
        return {
            "meta": self.meta.to_dict(),
            "dimensions": [item.to_dict() for item in self.dimensions],
            "charts": [item.to_dict() for item in self.charts],
            "cloud_analysis": self.cloud_analysis.to_dict() if self.cloud_analysis else None,
        }
