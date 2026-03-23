import time
import requests

novel_id = "705c5801"
task_id = "c0a3b438"

while True:
    resp = requests.get(f"http://localhost:8000/api/novels/{novel_id}/status?task_id={task_id}")
    data = resp.json()
    print(f"[{time.strftime('%H:%M:%S')}] status={data.get('status')}, progress={data.get('progress')}, stage={data.get('stage')}, error={data.get('error')}")
    if data.get('status') == 'completed':
        print("分析完成！")
        break
    if data.get('status') == 'failed':
        print(f"分析失败: {data.get('error')}")
        break
    time.sleep(10)