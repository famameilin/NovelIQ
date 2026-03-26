import json

output_lines = []

with open('logs/86fe028a/local_prompts.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        chunk_id = data.get('chunk_id')
        if chunk_id in [0, 3, 5, 7]:
            output_lines.append(f'{"="*80}')
            output_lines.append(f'CHUNK {chunk_id} - 完整Prompt')
            output_lines.append(f'{"="*80}')
            output_lines.append('')
            for msg in data['messages']:
                role = msg['role'].upper()
                content = msg['content']
                output_lines.append(f'--- {role} ---')
                output_lines.append(content)
                output_lines.append('')
            output_lines.append('')

with open('logs/86fe028a/完整prompts.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_lines))

print('Done! Output saved to logs/86fe028a/完整prompts.txt')
