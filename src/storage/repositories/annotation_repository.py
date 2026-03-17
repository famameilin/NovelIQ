"""
创建时间: 2026-03-14
创建者: TraeAI
任务: 实现 AnnotationRepository 类
说明: 标注数据的数据库操作实现，管理分块标注、角色、对话、关系等数据

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-routes-use-repository
修改内容: 添加查询方法 fetch_chunk_annotations_full, fetch_chunk_characters, fetch_chunk_relations, fetch_chunk_dialogues, fetch_alias_map

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session，使用 ORM 模型替代原生 SQL

修改时间: 2026-03-16
修改者: TraeAI
任务: fix-disambiguation-three-phase
修改内容: 新增 apply_alias_corrections 方法

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - 拆分annotation_repository
修改内容: 重构为包结构，原代码移至 annotation/ 子模块
"""

# 转发导入，保持向后兼容
from src.storage.repositories.annotation import AnnotationRepository

__all__ = ["AnnotationRepository"]
