"""
标注辅助函数模块 - 已废弃

.. deprecated::
    此模块已废弃。请使用 `src.workflows.annotate_helpers` 代替。
    
    此模块已移入 deprecated 文件夹，将在未来版本中删除。

创建时间: 2026-03-13
创建者: TraeAI
任务: refactor-analysis-layer-functions
说明: 从 run_annotate 函数中提取的辅助函数，实现职责分离

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-module-coupling-phase2
修改内容: 将本文件改为兼容层，重新导出 workflows.annotate_helpers 的内容

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 移除向后兼容导入，彻底废弃此模块
"""

__all__: list[str] = []
