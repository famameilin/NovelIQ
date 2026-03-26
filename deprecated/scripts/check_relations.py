import sqlite3
conn = sqlite3.connect('data/uploads/50f8db00.db')

# 检查chunk 21和22的关系
print('=== chunk 21的关系 ===')
cursor = conn.execute('SELECT from_char, to_char, type, change FROM chunk_relations WHERE chunk_id = 21')
for row in cursor.fetchall():
    print(f'  {row[0]} -> {row[1]}: {row[2]} ({row[3]})')

print('\n=== chunk 22的关系 ===')
cursor = conn.execute('SELECT from_char, to_char, type, change FROM chunk_relations WHERE chunk_id = 22')
for row in cursor.fetchall():
    print(f'  {row[0]} -> {row[1]}: {row[2]} ({row[3]})')

# 检查是否有褚大山相关的记录
print('\n=== 搜索褚大山 ===')
cursor = conn.execute("SELECT chunk_id, from_char, to_char, type FROM chunk_relations WHERE from_char LIKE '%褚%' OR to_char LIKE '%褚%'")
for row in cursor.fetchall():
    print(f'  chunk {row[0]}: {row[1]} -> {row[2]} ({row[3]})')

cursor = conn.execute("SELECT chunk_id, name, action FROM chunk_characters WHERE name LIKE '%褚%'")
print('\n=== chunk_characters中的褚姓人物 ===')
for row in cursor.fetchall():
    print(f'  chunk {row[0]}: {row[1]} - {row[2][:40] if row[2] else ""}...')

conn.close()
