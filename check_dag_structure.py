#!/usr/bin/env python3
"""Check DAG structure for deep reflection"""
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / '.iflow' / 'memory-dag' / 'lcm.db'
conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()

print("=== DAG Structure Analysis ===\n")

# Leaf nodes
cursor.execute("""
    SELECT node_id, conversation_id, topic 
    FROM summary_nodes 
    WHERE node_type = 'leaf'
    ORDER BY created_at
""")
print("Leaf nodes:")
for row in cursor.fetchall():
    topic = (row[2] or 'N/A')[:40]
    print(f"  {row[0]}: {topic}...")

# Summary nodes (older type)
cursor.execute("""
    SELECT node_id, topic 
    FROM summary_nodes 
    WHERE node_type = 'summary'
""")
print("\nSummary nodes:")
for row in cursor.fetchall():
    topic = (row[1] or 'N/A')[:40]
    print(f"  {row[0]}: {topic}...")

# Check free leaves (not covered by branch)
cursor.execute("""
    SELECT COUNT(*) FROM summary_nodes n
    WHERE n.node_type = 'leaf'
    AND n.node_id NOT IN (
        SELECT DISTINCT e.child_id 
        FROM summary_edges e 
        JOIN summary_nodes pn ON pn.node_id = e.parent_id
        WHERE pn.node_type = 'branch'
    )
""")
free_leaves = cursor.fetchone()[0]
print(f"\nLeaves available for branch upgrade: {free_leaves}")

# Check messages coverage
cursor.execute("SELECT COUNT(*) FROM messages")
total_msgs = cursor.fetchone()[0]

cursor.execute("""
    SELECT COUNT(DISTINCT e.child_id)
    FROM summary_edges e
    JOIN summary_nodes n ON n.node_id = e.parent_id
    WHERE n.node_type = 'leaf'
""")
compacted_msgs = cursor.fetchone()[0]

print(f"\nMessages: {total_msgs} total, {compacted_msgs} compacted ({round(compacted_msgs/max(total_msgs,1)*100,1)}%)")

# Try to escalate leaves to branch
print("\n=== Attempting Branch Escalation ===")

# Get conversations with leaf nodes
cursor.execute("""
    SELECT DISTINCT conversation_id FROM summary_nodes 
    WHERE node_type = 'leaf' AND conversation_id IS NOT NULL
""")
conv_ids = [row[0] for row in cursor.fetchall()]

from compaction_engine import escalate_to_branch

for conv_id in conv_ids:
    result = escalate_to_branch(conv_id, use_llm=False)
    status = result.get('status', 'unknown')
    if status == 'success':
        print(f"  {conv_id}: Created {result.get('batches', 0)} branch node(s)")
    else:
        print(f"  {conv_id}: {result.get('reason', result)}")

conn.close()
