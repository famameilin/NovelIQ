import requests
import time

novel_id = '02e5218d'
task_id = 'b588159e'

print(f"Checking analysis status for novel {novel_id}, task {task_id}...")

while True:
    resp = requests.get(f'http://localhost:8001/api/novels/{novel_id}/status?task_id={task_id}')
    status = resp.json()
    print(f"Status: {status.get('status')}, Progress: {status.get('progress', 0):.1f}%, Stage: {status.get('stage')}")
    if status.get('status') in ['completed', 'failed']:
        break
    time.sleep(10)

print("\nAnalysis finished!")