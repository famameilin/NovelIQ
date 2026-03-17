"""
查询 analysis_runs 表

创建时间: 2026-03-17
创建者: TraeAI
任务: 查询分析任务和结果
"""

from src.storage.db import get_engine
from sqlalchemy import text
import json

engine = get_engine()

with engine.connect() as conn:
    # 查询所有分析任务
    result = conn.execute(text("""
        SELECT run_id, novel_id, task_id, status, created_at, completed_at
        FROM analysis_runs
        ORDER BY created_at DESC
        LIMIT 10
    """)).fetchall()
    
    print("分析任务列表:")
    for row in result:
        print(f"  run_id: {row[0]}")
        print(f"  novel_id: {row[1]}")
        print(f"  task_id: {row[2]}")
        print(f"  status: {row[3]}")
        print(f"  created_at: {row[4]}")
        print(f"  completed_at: {row[5]}")
        print()
    
    # 查询特定任务的结果
    task_id = "650ce333"
    run_result = conn.execute(text("""
        SELECT run_id, novel_id, status, results
        FROM analysis_runs
        WHERE task_id = :task_id
    """), {"task_id": task_id}).fetchone()
    
    if run_result:
        print(f"\n任务 {task_id} 的结果:")
        print(f"  run_id: {run_result[0]}")
        print(f"  novel_id: {run_result[1]}")
        print(f"  status: {run_result[2]}")
        if run_result[3]:
            print(f"  results: {json.dumps(run_result[3], ensure_ascii=False, indent=2)[:500]}...")
        else:
            print("  results: None")
    else:
        print(f"\n未找到任务 {task_id}")
