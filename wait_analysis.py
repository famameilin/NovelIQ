import requests
import time

novel_id = 'd7d67942'
task_id = '22aaa884'

print(f"开始监控任务状态... novel_id={novel_id}, task_id={task_id}")

while True:
    try:
        response = requests.get(f'http://localhost:8002/api/novels/{novel_id}/status?task_id={task_id}', timeout=30)
        status = response.json()
        print(f"[{time.strftime('%H:%M:%S')}] status: {status.get('status')}, progress: {status.get('progress', 0):.1f}%, stage: {status.get('stage', 'N/A')}")

        if status.get('status') == 'completed':
            print('任务完成!')
            break
        elif status.get('status') == 'failed':
            print(f"任务失败: {status.get('error')}")
            break
    except Exception as e:
        print(f"查询出错: {e}")

    time.sleep(10)