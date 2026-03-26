import sqlite3
conn = sqlite3.connect('data/uploads/50f8db00.db')

# 检查chunk_characters中是否有柱子的别名
cursor = conn.execute('SELECT DISTINCT name FROM chunk_characters ORDER BY name')
print('=== chunk_characters中的人物名 ===')
for row in cursor.fetchall():
    print(f'  {row[0]}')

# 检查是否有别名记录
cursor = conn.execute("""
    SELECT e.canonical, ea.alias 
    FROM entities e 
    JOIN entity_aliases ea ON e.entity_id = ea.entity_id 
    WHERE e.entity_type = 'character'
""")
print('\n=== 别名映射 ===')
for row in cursor.fetchall():
    print(f'  {row[1]} -> {row[0]}')

# 检查chunk 21和22的原始标注
print('\n=== chunk 21的人物 ===')
cursor = conn.execute('SELECT name, role_function, action FROM chunk_characters WHERE chunk_id = 21')
for row in cursor.fetchall():
    print(f'  {row[0]}: {row[1]} - {row[2][:30] if row[2] else ""}...')

print('\n=== chunk 22的人物 ===')
cursor = conn.execute('SELECT name, role_function, action FROM chunk_characters WHERE chunk_id = 22')
for row in cursor.fetchall():
    print(f'  {row[0]}: {row[1]} - {row[2][:30] if row[2] else ""}...')

conn.close()
