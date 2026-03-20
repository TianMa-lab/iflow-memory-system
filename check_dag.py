import sqlite3
from pathlib import Path

db_path = Path.home() / '.iflow' / 'memory-dag' / 'lcm.db'
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# 检查 leaf 节点的 content
print('=== leaf 节点内容检查 ===')
cursor.execute("SELECT node_id, topic, LENGTH(content) as content_len FROM summary_nodes WHERE node_type='leaf'")
for row in cursor.fetchall():
    print(f'{row[0]}: topic="{row[1]}", content_len={row[2]}')

# 检查 summary 节点
print('\n=== summary 节点内容检查 ===')
cursor.execute("SELECT node_id, level, topic, LENGTH(content) as content_len FROM summary_nodes WHERE node_type='summary'")
for row in cursor.fetchall():
    print(f'{row[0]}: level={row[1]}, topic="{row[2]}", content_len={row[3]}')

# 检查边
print('\n=== DAG 边 ===')
cursor.execute('SELECT * FROM summary_edges')
for row in cursor.fetchall():
    print(row)

# 检查消息分布
print('\n=== 消息按会话分布 ===')
cursor.execute('SELECT conversation_id, COUNT(*) FROM messages GROUP BY conversation_id')
for row in cursor.fetchall():
    print(row)

conn.close()
