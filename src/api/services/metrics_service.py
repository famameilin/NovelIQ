"""
聚合指标服务类

说明: 封装聚合结果的获取和缓存逻辑，消除重复计算和代码重复
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from src.api.services.results_contracts import (
    _convert_aggregate_result,
    build_aggregate_metrics_contract_from_models,
)
from src.metrics.aggregate import aggregate_all_metrics
from src.storage.repositories import AnnotationRepository, ChapterRepository, StatsRepository


class MetricsService:
    """聚合指标服务类 - 提供缓存和统一的聚合结果获取"""

    def __init__(self, cache_ttl: int = 300):
        """
        Args:
            cache_ttl: 缓存过期时间（秒），默认5分钟
        """
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[Any, float]] = {}

    def _get_cache_key(self, run_id: str) -> str:
        """生成缓存键"""
        return f"aggregate_metrics:{run_id}"

    def _is_cache_valid(self, timestamp: float) -> bool:
        """检查缓存是否有效"""
        return time.time() - timestamp < self.cache_ttl

    def _get_from_cache(self, run_id: str) -> Any | None:
        """从缓存获取聚合结果"""
        cache_key = self._get_cache_key(run_id)
        if cache_key in self._cache:
            result, timestamp = self._cache[cache_key]
            if self._is_cache_valid(timestamp):
                logger.debug(f"Cache hit for {cache_key}")
                return result
            # 缓存过期，删除
            del self._cache[cache_key]
        return None

    def _set_cache(self, run_id: str, result: Any) -> None:
        """设置缓存"""
        cache_key = self._get_cache_key(run_id)
        self._cache[cache_key] = (result, time.time())
        logger.debug(f"Cache set for {cache_key}")

    def invalidate_cache(self, run_id: str) -> None:
        """失效指定run_id的缓存"""
        cache_key = self._get_cache_key(run_id)
        if cache_key in self._cache:
            del self._cache[cache_key]
            logger.info(f"Cache invalidated for {cache_key}")

    def get_aggregate_result(
        self,
        run_id: str,
        session: Session,
    ) -> tuple[Any, Any, Any, Any]:
        """
        获取聚合结果（带缓存）

        Args:
            run_id: 运行ID
            session: 数据库会话

        Returns:
            (narrative_structure, emotion_stats, character_stats, style_stats)
        """
        # 尝试从缓存获取
        cached_result = self._get_from_cache(run_id)
        if cached_result is not None:
            return cached_result

        # 缓存未命中，执行计算
        logger.info(f"Computing aggregate metrics for {run_id}")
        ann_repo = AnnotationRepository(session)
        chapter_repo = ChapterRepository(session)
        stats_repo = StatsRepository(session)

        result = aggregate_all_metrics(run_id, ann_repo, chapter_repo, stats_repo)
        converted_result = _convert_aggregate_result(result)

        # 设置缓存
        self._set_cache(run_id, converted_result)

        return converted_result

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
