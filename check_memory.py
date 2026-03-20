import sqlite3
from pathlib import Path

db_path = Path.home() / '.iflow' / 'memory-dag' / 'lcm.db'
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# 获取所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print('=== 表结构 ===')
for t in tables:
    cursor.execute(f'SELECT COUNT(*) FROM {t[0]}')
    count = cursor.fetchone()[0]
    print(f'{t[0]}: {count} 条记录')

# 查看 summary_nodes 结构
print('\n=== summary_nodes 结构 ===')
cursor.execute('PRAGMA table_info(summary_nodes)')
for col in cursor.fetchall():
    print(col)

# 查看 summary_edges 结构
print('\n=== summary_edges 结构 ===')
cursor.execute('PRAGMA table_info(summary_edges)')
for col in cursor.fetchall():
    print(col)

# 查看实际的 summary_nodes 数据
print('\n=== summary_nodes 数据 ===')
cursor.execute('SELECT * FROM summary_nodes')
for row in cursor.fetchall():
    print(row)

# 查看消息时间分布
print('\n=== 消息时间分布 ===')
cursor.execute("SELECT datetime(timestamp, 'unixepoch', 'localtime') as ts FROM messages ORDER BY timestamp LIMIT 5")
print('最早5条:')
for row in cursor.fetchall():
    print(row)
cursor.execute("SELECT datetime(timestamp, 'unixepoch', 'localtime') as ts FROM messages ORDER BY timestamp DESC LIMIT 5")
print('最新5条:')
for row in cursor.fetchall():
    print(row)

conn.close()
