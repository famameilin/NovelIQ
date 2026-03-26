import json
import os

log_dir = 'logs/50f8db00'
local_prompts = os.path.join(log_dir, 'local_prompts.jsonl')

if os.path.exists(local_prompts):
    print('=== 检查chunk 21和22的LLM输出 ===')
    with open(local_prompts, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            if data.get('chunk_id') in [21, 22]:
                print(f"\n--- chunk {data['chunk_id']} ---")
                response = data.get('response', '')
                # 查找relations部分
                if 'relations' in response:
                    # 尝试解析JSON
                    try:
                        # 找到JSON部分
                        start = response.find('{')
                        end = response.rfind('}') + 1
                        if start != -1 and end > start:
                            json_data = json.loads(response[start:end])
                            if 'relations' in json_data:
                                print('  关系:')
                                for rel in json_data['relations']:
                                    print(f"    {rel.get('from_name', '?')} -> {rel.get('to_name', '?')}: {rel.get('type', '?')}")
                    except:
                        print(f'  响应片段: {response[:200]}...')
