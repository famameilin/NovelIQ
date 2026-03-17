"""
检查最新的分析任务

创建时间: 2026-03-17
创建者: TraeAI
任务: 查看最新的分析任务run_id
"""

from src.storage.db import get_engine
from sqlalchemy import text

engine = get_engine()

with engine.connect() as conn:
    # 查询最新的分析任务
    result = conn.execute(text("""
        SELECT run_id, novel_id, status, created_at, completed_at
        FROM analysis_runs
        ORDER BY created_at DESC
        LIMIT 5
    """)).fetchall()
    
    print("最新的5个分析任务:\n")
    for i, row in enumerate(result, 1):
        print(f"{i}. run_id: {row[0]}")
        print(f"   novel_id: {row[1]}")
        print(f"   status: {row[2]}")
        print(f"   created_at: {row[3]}")
        if row[4]:
            print(f"   completed_at: {row[4]}")
        print()
