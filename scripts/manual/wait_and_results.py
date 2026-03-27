import requests
import time

BASE_URL = 'http://localhost:8001/api'
novel_id = '10960c77'

while True:
    try:
        resp = requests.get(f'{BASE_URL}/novels/{novel_id}/status', timeout=10)
        data = resp.json()
        status = data.get('status', 'unknown')
        progress = data.get('progress', 0)
        stage = data.get('stage', '')
        print(f'Status: {status}, Progress: {progress}%, Stage: {stage}')
        
        if status == 'completed':
            print('分析完成!')
            break
        elif status == 'failed':
            error_msg = data.get('error', 'Unknown error')
            print(f'分析失败: {error_msg}')
            break
        
        time.sleep(10)
    except Exception as e:
        print(f'请求出错: {e}, 等待重试...')
        time.sleep(5)

print('正在调用results接口...')
try:
    result_resp = requests.get(f'{BASE_URL}/novels/{novel_id}/results', timeout=30)
    print(f'Results response: {result_resp.status_code}')
    print(result_resp.text)
except Exception as e:
    print(f'Results请求出错: {e}')
