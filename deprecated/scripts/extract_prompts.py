import json

with open('logs/86fe028a/local_prompts.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        chunk_id = data.get('chunk_id')
        if chunk_id in [0, 3, 5, 7]:
            print(f'========== CHUNK {chunk_id} ==========')
            for msg in data['messages']:
                role = msg['role'].upper()
                content = msg['content']
                print(f'--- {role} ---')
                print(content)
                print()
