import json

with open('outputs/50f8db00.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 检查自环
self_loops = []
for rel in data.get('character_relations', []):
    if rel['from_char'] == rel['to_char']:
        self_loops.append(rel)

print('=== 自环检查 ===')
if self_loops:
    print(f'发现 {len(self_loops)} 个自环:')
    for sl in self_loops[:10]:
        print(f'  chunk_id={sl["chunk_id"]}, char={sl["from_char"]}, type={sl["type"]}')
else:
    print('未发现自环问题')

# 检查别名问题 - characters列表中的名字
print('\n=== 人物列表 ===')
chars = data.get('characters', [])
for c in chars:
    print(f'  {c["name"]}: 出现{c["appearance_count"]}次, 角色={c["role_function"]}')

# 检查所有出现的人物名
all_names = set()
for rel in data.get('character_relations', []):
    all_names.add(rel['from_char'])
    all_names.add(rel['to_char'])

print(f'\n=== 关系中出现的人物名 ({len(all_names)}个) ===')
print(sorted(all_names))

# 检查是否有别名问题（同一人物的不同称呼同时出现）
# 例如：伯安 vs 贺伯安
alias_pairs = [
    ('伯安', '贺伯安'),
    ('贺铮', '贺老爷'),
]
print('\n=== 别名消歧检查 ===')
for name1, name2 in alias_pairs:
    if name1 in all_names and name2 in all_names:
        print(f'  ⚠️ 别名同时出现: {name1} 和 {name2}')
    elif name1 in all_names:
        print(f'  ✓ 仅使用: {name1}')
    elif name2 in all_names:
        print(f'  ✓ 仅使用: {name2}')

# 检查chunk_annotations中的人物名
print('\n=== chunk_annotations中的人物名检查 ===')
annotation_names = set()
for ann in data.get('chunk_annotations', []):
    for char in ann.get('characters', []):
        annotation_names.add(char['name'])
print(f'标注中出现的人物: {sorted(annotation_names)}')

# 检查是否有别名混用
for name1, name2 in alias_pairs:
    if name1 in annotation_names and name2 in annotation_names:
        print(f'  ⚠️ 标注中别名同时出现: {name1} 和 {name2}')
