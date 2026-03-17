"""
检查task_id格式

创建时间: 2026-03-17
创建者: TraeAI
任务: 检查数据库中的task_id和run_id
"""

from src.storage.db import get_engine
from sqlalchemy import text

engine = get_engine()

with engine.connect() as conn:
    # 查询所有运行记录
    result = conn.execute(text("""
        SELECT run_id,