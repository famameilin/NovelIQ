import requests
import time

novel_id = '3d950b49'
task_id = '96f6febd'

print(f"Checking analysis status for novel {novel_id}, task {task_id}...")

while True:
    r = requests.get(f'http://localhost:8002/api/novels/{novel_id}/status?task_id={task_id}')
    status = r.json()
    print(f"Status: {status.get('status')}, Progress: {status.get('progress', 0):.1f}%, Stage: {status.get('stage')}")
    if status.get('status') in ['completed', 'failed']:
        break
    time.sleep(10)

if status.get('status') == 'completed':
    print("\nAnalysis completed! Fetching results...")
    result = requests.get(f'http://localhost:8002/api/novels/{novel_id}/results?task_id={task_id}')
    print(result.json())