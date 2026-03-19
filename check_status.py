"""
检查分析任务状态

创建时间: 2026-03-18
创建者: TraeAI
任务: 监控分析任务状态
"""
import requests
import json
import time

novel_id = '57df28dc'
task_id = 'f8f4c80d'

while True:
    url = f'http://localhost:8000/api/novels/{novel_id}/status?task_id={task_id}'
    response = requests.get(url)
    data = response.json()
    print(f"Status: {data.get('status')}, Progress: {data.get('progress')}%, Stage: {data.get('stage')}")
    if data.get('status') in ['completed', 'failed']:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        break
    time.sleep(5)
