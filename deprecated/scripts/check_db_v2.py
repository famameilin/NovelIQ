"""
检查数据库结构
2026-03-11 创建
"""
import sqlite3

db_path = r'E:\projects\python-projects\novel quantitative analysis\data\uploads\ed83162a.db'
conn = sqlite3.connect(db_path)

print('=== 数据库表结构 ===\n')

# 列出所有表
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]
print(f'表列表: {tables}\n')

# 检查关系相关表
for table in tables:
    if 'relation' in table.lower() or 'character' in table.lower():
        print(f'【{table}】')
        cursor = conn.execute(f'PRAGMA table_info({table})')
        cols = [row[1] for row in cursor.fetchall()]
        print(f'  列: {cols}')
        cursor = conn.execute(f'SELECT COUNT(*) FROM {table}')
        print(f'  记录数: {cursor.fetchone()[0]}')
        print()

# 检查chunk_relations表的自环
if 'chunk_relations' in tables:
    print('【chunk_relations自环检查】')
    cursor = conn.execute('SELECT COUNT(*) FROM chunk_relations WHERE from_char = to_char')
    count = cursor.fetchone()[0]
    print(f'  自环数量: {count}')
    if count > 0:
        cursor = conn.execute('SELECT chunk_id, from_char, to_char, type, change FROM chunk_relations WHERE from_char = to_char LIMIT 5')
        for row in cursor.fetchall():
            print(f'  chunk_{row[0]}: {row[1]} -> {row[2]}, type={row[3]}, change={row[4]}')

conn.close()
