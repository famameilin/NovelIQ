"""
上传小说并启动分析的脚本

创建时间: 2026-03-19
创建者: TraeAI
任务: 上传重明传并启动分析
"""

import requests
import time
import sys

BASE_URL = "http://localhost:8000/api"
NOVEL_PATH = "data/novel/重明传.txt"

def upload_novel():
    """上传小说文件"""
    print("=" * 50)
    print("步骤1: 上传小说文件")
    print("=" * 50)

    with open(NOVEL_PATH, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/novels/upload",
            files={"file": f}
        )

    if response.status_code == 200:
        data = response.json()
        print(f"✓ 上传成功!")
        print(f"  - novel_id: {data.get('novel_id')}")
        print(f"  - filename: {data.get('filename')}")
        print(f"  - status: {data.get('status')}")
        return data.get('novel_id')
    else:
        print(f"✗ 上传失败: {response.status_code}")
        print(response.text)
        return None

def start_analysis(novel_id):
    """启动分析任务"""
    print("\n" + "=" * 50)
    print("步骤2: 启动分析任务")
    print("=" * 50)

    response = requests.post(
        f"{BASE_URL}/novels/{novel_id}/analyze",
        json={
            "num_topics": 25,
            "max_chars": 2000,
            "overlap": 200
        }
    )

    if response.status_code == 200:
        data = response.json()
        print(f"✓ 分析任务已启动!")
        print(f"  - novel_id: {data.get('novel_id')}")
        print(f"  - task_id: {data.get('task_id')}")
        return data.get('task_id')
    else:
        print(f"✗ 启动分析失败: {response.status_code}")
        print(response.text)
        return None

def check_status(novel_id, task_id):
    """检查分析状态"""
    print("\n" + "=" * 50)
    print("步骤3: 检查分析状态")
    print("=" * 50)

    while True:
        response = requests.get(
            f"{BASE_URL}/novels/{novel_id}/status",
            params={"task_id": task_id}
        )

        if response.status_code == 200:
            data = response.json()
            status = data.get('status')
            progress = data.get('progress', 0)
            stage = data.get('stage', 'unknown')

            print(f"\r  状态: {status} | 进度: {progress:.1f}% | 阶段: {stage}", end="", flush=True)

            if status == "completed":
                print(f"\n✓ 分析完成!")
                return True
            elif status == "failed":
                print(f"\n✗ 分析失败!")
                print(f"  错误: {data.get('error')}")
                return False

            time.sleep(2)
        else:
            print(f"\n✗ 查询状态失败: {response.status_code}")
            print(response.text)
            return False

def get_results(novel_id, task_id):
    """获取分析结果"""
    print("\n" + "=" * 50)
    print("步骤4: 导出分析结果")
    print("=" * 50)

    response = requests.get(
        f"{BASE_URL}/novels/{novel_id}/results",
        params={"task_id": task_id}
    )

    if response.status_code == 200:
        data = response.json()
        print(f"✓ 结果导出成功!")
        print(f"  - file_path: {data.get('file_path')}")
        print(f"  - novel_id: {data.get('novel_id')}")
        print(f"  - novel_name: {data.get('novel_name')}")
        return data
    else:
        print(f"✗ 导出结果失败: {response.status_code}")
        print(response.text)
        return None

def main():
    print("重明传 小说分析流程")
    print("=" * 50)

    # 步骤1: 上传小说
    novel_id = upload_novel()
    if not novel_id:
        sys.exit(1)

    # 步骤2: 启动分析
    task_id = start_analysis(novel_id)
    if not task_id:
        sys.exit(1)

    # 步骤3: 等待分析完成
    if not check_status(novel_id, task_id):
        sys.exit(1)

    # 步骤4: 获取结果
    results = get_results(novel_id, task_id)
    if not results:
        sys.exit(1)

    print("\n" + "=" * 50)
    print("所有步骤完成!")
    print("=" * 50)
    print(f"\n结果文件: {results.get('file_path')}")

if __name__ == "__main__":
    main()
