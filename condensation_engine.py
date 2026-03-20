#!/usr/bin/env python3
"""
CondensationEngine - 层级摘要构建
借鉴 lossless-claw 的设计理念

功能:
1. 检测同级别的 summary 节点是否足够多
2. 将多个低级 summary 压缩成更高级别的 summary
3. 建立 DAG 边关系 (parent -> children)
4. 支持 leaf → L1 → L2 → L3 无限层级
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

IFLOW_DIR = Path.home() / ".iflow"
DB_PATH = IFLOW_DIR / "memory-dag" / "lcm.db"

# 配置参数 (借鉴 lossless-claw)
CONDENSED_MIN_FANOUT = 4  # 最少子节点数才触发压缩
CONDENSED_TARGET_TOKENS = 2000  # 目标摘要 token 数


def get_db_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    return sqlite3.connect(str(DB_PATH))


def get_uncondensed_nodes(conn: sqlite3.Connection, level: int) -> List[Dict[str, Any]]:
    """获取未被压缩到更高层的节点"""
    cursor = conn.cursor()
    
    # 获取该级别所有节点
    cursor.execute("""
        SELECT node_id, conversation_id, topic, content, token_count, created_at
        FROM summary_nodes
        WHERE level = ?
        ORDER BY created_at ASC
    """, (level,))
    
    all_nodes = cursor.fetchall()
    
    # 检查哪些节点已经有父节点
    cursor.execute("""
        SELECT DISTINCT child_id FROM summary_edges
        WHERE relation = 'summarizes'
    """)
    has_parent = set(row[0] for row in cursor.fetchall())
    
    # 过滤出没有父节点的
    uncondensed = []
    for row in all_nodes:
        if row[0] not in has_parent:
            uncondensed.append({
                'node_id': row[0],
                'conversation_id': row[1],
                'topic': row[2],
                'content': row[3],
                'token_count': row[4],
                'created_at': row[5]
            })
    
    return uncondensed


def generate_condensed_summary(nodes: List[Dict[str, Any]], level: int) -> str:
    """生成压缩摘要"""
    # 收集所有内容
    all_topics = []
    all_content_parts = []
    
    for node in nodes:
        if node.get('topic'):
            all_topics.append(node['topic'])
        if node.get('content'):
            all_content_parts.append(f"[{node['node_id']}] {node['content'][:200]}")
    
    # 生成层级摘要
    summary = f"=== L{level} Summary ===\n"
    summary += f"包含 {len(nodes)} 个子节点\n"
    
    if all_topics:
        summary += f"主题: {' | '.join(all_topics[:5])}\n"
    
    if all_content_parts:
        summary += f"内容概要:\n"
        for part in all_content_parts[:10]:
            summary += f"  - {part[:100]}...\n"
    
    return summary


def create_condensed_node(
    conn: sqlite3.Connection,
    level: int,
    children: List[Dict[str, Any]],
    summary_content: str
) -> str:
    """创建压缩节点并建立边关系"""
    cursor = conn.cursor()
    
    # 生成节点 ID
    today = datetime.now().strftime('%Y-%m-%d')
    level_prefix = f'l{level}'
    
    cursor.execute(
        "SELECT COUNT(*) FROM summary_nodes WHERE node_id LIKE ?",
        (f'{level_prefix}-{today}-%',)
    )
    count = cursor.fetchone()[0]
    node_id = f'{level_prefix}-{today}-{count+1:03d}'
    
    # 确定话题
    topics = [c['topic'] for c in children if c.get('topic')]
    topic = topics[0][:50] if topics else f"L{level} Summary"
    
    # 创建节点
    cursor.execute("""
        INSERT INTO summary_nodes
        (node_id, conversation_id, node_type, level, topic, content, token_count, created_at)
        VALUES (?, NULL, 'summary', ?, ?, ?, ?, ?)
    """, (
        node_id,
        level,
        topic,
        summary_content,
        len(summary_content) // 4,
        datetime.now().isoformat()
    ))
    
    # 建立边关系
    for child in children:
        cursor.execute("""
            INSERT INTO summary_edges (parent_id, child_id, relation, created_at)
            VALUES (?, ?, 'summarizes', ?)
        """, (node_id, child['node_id'], datetime.now().isoformat()))
    
    conn.commit()
    return node_id


def condense_level(level: int) -> Dict[str, Any]:
    """压缩指定级别的节点"""
    conn = get_db_connection()
    
    try:
        # 获取未压缩的节点
        nodes = get_uncondensed_nodes(conn, level)
        
        if len(nodes) < CONDENSED_MIN_FANOUT:
            return {
                'status': 'skipped',
                'reason': f'节点数不足 {CONDENSED_MIN_FANOUT}',
                'node_count': len(nodes),
                'level': level
            }
        
        # 生成摘要
        summary = generate_condensed_summary(nodes, level + 1)
        
        # 创建压缩节点
        node_id = create_condensed_node(conn, level + 1, nodes, summary)
        
        return {
            'status': 'success',
            'node_id': node_id,
            'children_count': len(nodes),
            'new_level': level + 1,
            'summary_length': len(summary)
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'level': level
        }
    finally:
        conn.close()


def condense_all_levels() -> Dict[str, Any]:
    """从 level 0 开始，递归压缩所有级别"""
    results = []
    level = 0
    max_level = 10  # 防止无限循环
    
    while level < max_level:
        result = condense_level(level)
        results.append(result)
        
        if result.get('status') != 'success':
            break
        
        level += 1
    
    return {
        'total_levels_processed': len(results),
        'results': results
    }


def get_dag_overview() -> Dict[str, Any]:
    """获取 DAG 结构概览"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 统计各级别节点数
    cursor.execute("""
        SELECT level, node_type, COUNT(*) 
        FROM summary_nodes 
        GROUP BY level, node_type
        ORDER BY level
    """)
    level_stats = cursor.fetchall()
    
    # 统计边数
    cursor.execute("SELECT COUNT(*) FROM summary_edges")
    edge_count = cursor.fetchone()[0]
    
    # 获取最大层级
    cursor.execute("SELECT MAX(level) FROM summary_nodes")
    max_level = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return {
        'level_stats': [
            {'level': row[0], 'type': row[1], 'count': row[2]}
            for row in level_stats
        ],
        'edge_count': edge_count,
        'max_level': max_level
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            result = condense_all_levels()
        elif sys.argv[1] == '--overview':
            result = get_dag_overview()
        else:
            level = int(sys.argv[1])
            result = condense_level(level)
    else:
        result = condense_all_levels()
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
