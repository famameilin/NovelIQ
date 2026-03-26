"""
检查JSON结果文件完整性
2026-03-11 创建
"""
import json

file_path = r'E:\projects\python-projects\novel quantitative analysis\outputs\ed83162a.json'

with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

print('=== JSON文件完整性检查 ===\n')

# 基本信息
print('【基本信息】')
print(f'  task_id: {data.get("task_id")}')
print(f'  novel_id: {data.get("novel_id")}')
print(f'  novel_name: {data.get("novel_name")}')
print(f'  generated_at: {data.get("generated_at")}')
print(f'  total_chunks: {data.get("total_chunks")}')
print(f'  total_chars: {data.get("total_chars")}')

# 检查各字段
print('\n【数据字段检查】')
fields = [
    ('emotion_curve', list),
    ('rhythm_curve', list),
    ('characters', list),
    ('topics', list),
    ('diagnosis', dict),
    ('chunk_styles', list),
    ('chunk_annotations', list),
    ('character_relations', list),
    ('global_stats', dict),
    ('chunk_cultures', list),
    ('aggregate_metrics', dict),
    ('token_usage_stats', dict),
]

missing = []
for field, expected_type in fields:
    value = data.get(field)
    if value is None:
        missing.append(field)
        print(f'  {field}: 缺失')
    elif not isinstance(value, expected_type):
        print(f'  {field}: 类型错误 (期望{expected_type.__name__}, 实际{type(value).__name__})')
    else:
        if isinstance(value, list):
            print(f'  {field}: 正常 ({len(value)}条记录)')
        elif isinstance(value, dict):
            print(f'  {field}: 正常 ({len(value)}个键)')
        else:
            print(f'  {field}: 正常')

print(f'\n【missing_fields】')
print(f'  {data.get("missing_fields")}')

# 详细检查关键数据
print('\n【关键数据详情】')

# 情感曲线
emotion = data.get('emotion_curve', [])
if emotion:
    print(f'  情感曲线: {len(emotion)}个chunk')
    print(f'    示例: chunk_0 net_density={emotion[0].get("net_density", 0):.6f}')

# 人物
characters = data.get('characters', [])
if characters:
    print(f'  人物: {len(characters)}个')
    top3 = sorted(characters, key=lambda x: x.get('appearance_count', 0), reverse=True)[:3]
    for c in top3:
        print(f'    {c.get("name")}: {c.get("appearance_count")}次出现, 角色={c.get("role_function")}')

# 主题
topics = data.get('topics', [])
topic_labels = data.get('diagnosis', {}).get('topic_labels', [])
if topics:
    print(f'  主题: {len(topics)}个')
    for t in topics[:3]:
        tid = t.get("topic_id")
        label = topic_labels[tid] if tid < len(topic_labels) else "未命名"
        words = t.get('words', [])[:3]
        print(f'    主题{tid}: {label} (关键词: {", ".join(words)}...)')

# 诊断
diagnosis = data.get('diagnosis')
if diagnosis:
    print(f'  诊断: 存在')
    keys = list(diagnosis.keys())
    print(f'    键: {keys[:5]}...')

# 聚合指标
agg = data.get('aggregate_metrics', {})
if agg:
    print(f'  聚合指标:')
    for k, v in agg.items():
        if v:
            print(f'    {k}: 正常')
        else:
            print(f'    {k}: 空或None')

print('\n=== 检查完成 ===')
