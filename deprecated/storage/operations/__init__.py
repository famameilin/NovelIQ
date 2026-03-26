"""
数据库操作模块 - 已废弃

.. deprecated::
    此模块已废弃。请使用 `src.storage.repositories` 中的 Repository 类代替：
    
    - ChunkRepository: 分块相关操作
    - AnnotationRepository: 标注相关操作
    - EntityRepository: 实体相关操作
    - StatsRepository: 统计相关操作
    - DiagnosisRepository: 诊断相关操作
    - RunRepository: 运行记录相关操作
    
    此模块已移入 deprecated 文件夹，将在未来版本中删除。

创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 数据库操作模块

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 标记整个模块为废弃，移动到 deprecated 文件夹

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 移除向后兼容导入，彻底废弃此模块
"""

__all__: list[str] = []
