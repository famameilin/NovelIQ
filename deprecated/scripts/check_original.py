import sqlite3
import json

conn = sqlite3.connect('data/uploads/50f8db00.db')

# 检查原始标注日志
print('=== 检查是否有原始标注日志 ===')
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%log%'")
tables = cursor.fetchall()
print(f'日志表: {tables}')

# 检查local_prompts.jsonl
import os
log_dir = 'logs/50f8db00'
if os.path.exists(log_dir):
    print(f'\n=== 日志目录内容 ===')
    for f in os.listdir(log_dir):
        print(f'  {f}')

# 检查annotation日志
annotation_log = os.path.join(log_dir, 'annotations.jsonl')
if os.path.exists(annotation_log):
    print(f'\n=== 检查chunk 21和22的原始标注 ===')
    with open(annotation_log, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            if data.get('chunk_id') in [21, 22]:
                print(f"\n--- chunk {data['chunk_id']} ---")
                if 'relations' in data:
                    for rel in data['relations']:
                        print(f"  {rel.get('from_name', '?')} -> {rel.get('to_name', '?')}: {rel.get('type', '?')}")

conn.close()
