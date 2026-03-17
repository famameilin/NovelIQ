"""
创建时间: 2026-03-14
创建者: TraeAI
任务: 实现 StatsRepository 类
说明: 统计数据的数据库操作实现，支持 run_id 参数

修改时间: 2026-03-17
修改者: TraeAI
任务: code-quality-refactor - 拆分stats_repository
修改内容: 改为从stats包导入，保持向后兼容
"""

from __future__ import annotations

# 保持向后兼容的导入
from src.storage.repositories.stats import StatsRepository

__all__ = ["StatsRepository"]
