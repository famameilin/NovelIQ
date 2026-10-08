"""
聚合指标服务类

说明: 封装聚合结果的获取和缓存逻辑，消除重复计算和代码重复
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.api.services.results_contracts import (
    _convert_aggregate_result,
    build_aggregate_metrics_contract_from_models,
)
from src.metrics.queries.aggregate import MetricsQueryService


class MetricsService:
    """把指标领域结果装配为既有 HTTP 响应，取数与缓存由指标查询服务负责"""

    def __init__(self, cache_ttl: int = 300) -> None:
        self.query = MetricsQueryService(cache_ttl)

    def invalidate_cache(self, run_id: str) -> None:
        self.query.invalidate_cache(run_id)

    def get_aggregate_result(self, run_id: str, session: Session) -> tuple[Any, Any, Any, Any]:
        return _convert_aggregate_result(self.query.get_aggregate_result(run_id, session))

    def get_narrative_structure(self, run_id: str, session: Session) -> Any:
        """获取叙事结构指标"""
        narrative_structure, _, _, _ = self.get_aggregate_result(run_id, session)
        return narrative_structure

    def get_emotion_stats(self, run_id: str, session: Session) -> Any:
        """获取情感统计指标"""
        _, emotion_stats, _, _ = self.get_aggregate_result(run_id, session)
        return emotion_stats

    def get_character_stats(self, run_id: str, session: Session) -> Any:
        """获取角色统计指标"""
        _, _, character_stats, _ = self.get_aggregate_result(run_id, session)
        return character_stats

    def get_style_stats(self, run_id: str, session: Session) -> Any:
        """获取风格统计指标"""
        _, _, _, style_stats = self.get_aggregate_result(run_id, session)
        return style_stats

    def get_aggregate_metrics_contract(self, run_id: str, session: Session) -> dict[str, Any]:
        """获取稳定的 aggregate metrics contract，并复用聚合缓存"""
        narrative_structure, emotion_stats, character_stats, style_stats = self.get_aggregate_result(run_id, session)
        return build_aggregate_metrics_contract_from_models(
            narrative_structure,
            emotion_stats,
            character_stats,
            style_stats,
        )


# 聚合指标服务单例：API 依赖与报告导出工具共用同一实例
_metrics_service_instance: MetricsService | None = None


def get_metrics_service() -> MetricsService:
    """获取聚合指标服务单例（缓存 300s）"""
    global _metrics_service_instance
    if _metrics_service_instance is None:
        _metrics_service_instance = MetricsService(cache_ttl=300)
    return _metrics_service_instance
