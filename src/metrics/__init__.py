"""
Metrics 模块入口

本包为聚合命名空间，不维护 re-export 面：全部消费者按子模块路径导入
（如 `from src.metrics.aggregate import aggregate_all_metrics`）。
2026-10-02 清理：包级 re-export 全仓零消费者，整体移除（修改者 Trae）。
"""
