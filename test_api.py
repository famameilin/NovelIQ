"""
测试API获取结果

创建时间: 2026-03-17
创建者: TraeAI
任务: 测试修复后的API
"""

import requests
import json

BASE_URL = "http://localhost:8000/api"
NOVEL_ID = "434e9d9c"
TASK_ID = "650ce333"

# 测试获取结果
print("=" * 60)
print("测试获取分析结果")
print("=" * 60)

response = requests.get(f"{BASE_URL}/novels/{NOVEL_ID}/results?task_id={TASK_ID}")
print(f"\n状态码: {response.status_code}")

if response.status_code == 200:
    results = response.json()
    print(f"✅ 成功获取结果!")
    print(f"\n结果概览:")
    print(f"  状态: {results.get('status')}")
    print(f"  阶段: {list(results.get('results', {}).keys())}")
    
    # 保存到文件
    output_file = "analysis_results_650ce333.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    import os
    file_size = os.path.getsize(output_file)
    print(f"\n✅ 结果已保存到: {output_file}")
    print(f"  文件大小: {file_size / 1024:.1f} KB")
else:
    print(f"❌ 获取失败:")
    print(f"  {response.text}")
