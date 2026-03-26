import requests
import json

response = requests.get("http://localhost:8001/api/novels/22b3a001/results")
if response.status_code == 200:
    data = response.json()
    with open(r'e:\projects\python-projects\novel quantitative analysis\log\results\22b3a001_v1.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("导出成功")
    print(f"文件路径: {data.get('file_path')}")
else:
    print(f"错误: {response.status_code}")
    print(response.text)
