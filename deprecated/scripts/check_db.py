import json

problem_chunks = [3, 8]

for chunk_id in problem_chunks:
    with open(r'e:\projects\python-projects\novel quantitative analysis\logs\analysis\22b3a001\20260310_222728\local_prompts.jsonl', 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            if data.get('chunk_id') == chunk_id:
                print("=" * 80)
                print(f"=== Chunk {chunk_id} 完整 Prompt ===")
                print("=" * 80)
                for msg in data['messages']:
                    if msg['role'] == 'user':
                        content = msg['content']
                        # 只打印最后一条user消息（包含RAG信息的）
                        if '待分析文本' in content:
                            print(f"\n--- USER (最后一条) ---")
                            print(content)
                print("\n" + "=" * 80)
                print(f"=== Chunk {chunk_id} 完整 Response ===")
                print("=" * 80)
                print(data.get('response', ''))
                print("\n")
                break
