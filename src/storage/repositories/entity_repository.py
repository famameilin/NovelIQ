"""
创建时间: 2026-03-14
创建者: TraeAI
任务: Repository 层重构 - 实现 EntityRepository
说明: 实现实体数据接口，管理实体、别名、嵌入向量、关系等数据

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session，使用 ORM 查询

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - 拆分entity_repository
修改内容: 重构为包结构，原代码移至 entity/ 子模块
"""

# 转发导入，保持向后兼容
from src.storage.repositories.entity import EntityRepository

__all__ = ["EntityRepository"]
