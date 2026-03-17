import requests
import json

base_url = "http://localhost:8001/api"
novel_id = "3f22da4a"

payload = {
    "force_preprocess": True,
    "force_annotate": True,
    "force_aggregate": True,
    "force_topic_model": True,
    "force_diagnose": True
}

print(f"Starting reanalysis for {novel_id}...")
response = requests.post(f"{base_url}/novels/{novel_id}/reanalyze", json=payload)
print(response.json())

if response.status_code == 200:
    task_id = response.json()["task_id"]
    print(f"Task ID: {task_id}")
    
    # Poll status
    import time
    while True:
        status_resp = requests.get(f"{base_url}/novels/{novel_id}/status", params={"task_id": task_id})
        status = status_resp.json()
        print(f"Status: {status['status']}, Stage: {status.get('stage')}, Progress: {status.get('progress')}")
        
        if status['status'] in ['completed', 'failed']:
            if status['status'] == 'failed':
                print(f"Error: {status.get('error')}")
            break
        time.sleep(2)

    # Get results if completed
    if status['status'] == 'completed':
        results = requests.get(f"{base_url}/novels/{novel_id}/results", params={"task_id": task_id})
        print("Results exported:")
        print(json.dumps(results.json(), indent=2, ensure_ascii=False))
