import json

with open('outputs/50f8db00.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 检查 relations 中的自环
print('=== 检查 relations 中的自环 ===')
self_loops = []
if 'relations' in data:
    for r in data['relations']:
        if r.get('from') == r.get('to'):
            self_loops.append(r)
            print(f"自环: {r.get('from')} -> {r.get('to')} ({r.get('type')})")

if not self_loops:
    print('没有发现自环关系')

# 检查 chunk_annotations 中的自环
print()
print('=== 检查 chunk_annotations 中的自环 ===')
chunk_self_loops = []
if 'chunk_annotations' in data:
    for chunk in data['chunk_annotations']:
        for r in chunk.get('relations', []):
            if r.get('from') == r.get('to'):
                chunk_self_loops.append({'chunk_id': chunk.get('chunk_id'), 'relation': r})
                print(f"Chunk {chunk.get('chunk_id')}: 自环 {r.get('from')} -> {r.get('to')} ({r.get('type')})")

if not chunk_self_loops:
    print('没有发现自环关系')

print()
print(f'总计: {len(self_loops)} 个自环 (relations), {len(chunk_self_loops)} 个自环 (chunk_annotations)')
