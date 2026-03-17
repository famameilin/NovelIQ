"""
查看表结构

创建时间: 2026-03-17
创建者: TraeAI
任务: 查看analysis_runs表结构
"""

from src.storage.db import get_engine
from sqlalchemy import text

engine = get_engine()

with engine.connect() as conn:
    # 查询表结构
    columns = conn.execute(text("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'analysis_runs'
        ORDER BY ordinal_position
    """)).fetchall()
    
    print("analysis_runs 表结构:")
    for col in columns:
        print(f"  - {col[0]}: {col[1]}")
    
    # 查询数据
    result = conn.execute(text("""
        SELECT * FROM analysis_runs
        ORDER BY created_at DESC
        LIMIT 3
    """)).fetchall()
    
    print(f"\n最近3条记录:")
    for row in result:
        print(f"  {dict(row._mapping)}")
