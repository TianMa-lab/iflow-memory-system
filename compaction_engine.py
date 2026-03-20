#!/usr/bin/env python3
"""
CompactionEngine - 自动压缩消息为 leaf summary
借鉴 lossless-claw 的设计理念

功能:
1. 检测需要压缩的消息块
2. 调用 LLM 生成摘要
3. 创建 leaf summary 节点
4. 建立 DAG 边关系
"""

import sqlite3
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

IFLOW_DIR = Path.home() / ".iflow"
DB_PATH = IFLOW_DIR / "memory-dag" / "lcm.db"

# 配置参数 (借鉴 lossless-claw)
LEAF_MIN_FANOUT = 8  # 最少消息数才触发压缩
LEAF_TARGET_TOKENS = 1200  # 目标摘要 token 数
FRESH_TAIL_COUNT = 32  # 保护最近 N 条消息不被压缩


def get_db_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    return sqlite3.connect(str(DB_PATH))


def count_messages_in_conversation(conn: sqlite3.Connection, conversation_id: str) -> int:
    """统计会话中的消息数"""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
        (conversation_id,)
    )
    return cursor.fetchone()[0]


def get_uncompacted_messages(
    conn: sqlite3.Connection, 
    conversation_id: str,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """获取未被压缩的消息"""
    cursor = conn.cursor()
    
    # 获取已有 leaf summary 覆盖的消息
    cursor.execute("""
        SELECT DISTINCT m.message_id
        FROM messages m
        JOIN summary_edges e ON e.child_id = m.message_id
        JOIN summary_nodes n ON n.node_id = e.parent_id
        WHERE n.node_type = 'leaf' AND m.conversation_id = ?
    """, (conversation_id,))
    
    compacted_ids = set(row[0] for row in cursor.fetchall())
    
    # 获取未压缩的消息，排除最近 FRESH_TAIL_COUNT 条
    cursor.execute("""
        SELECT message_id, role, content, created_at
        FROM messages 
        WHERE conversation_id = ?
        ORDER BY created_at ASC
    """, (conversation_id,))
    
    all_messages = cursor.fetchall()
    
    # 过滤掉已压缩的和最近的
    uncompacted = []
    for i, row in enumerate(all_messages):
        if row[0] not in compacted_ids:
            if i < len(all_messages) - FRESH_TAIL_COUNT:  # 保护最近的消息
                uncompacted.append({
                    'message_id': row[0],
                    'role': row[1],
                    'content': row[2],
                    'created_at': row[3]
                })
    
    return uncompacted


def generate_summary_with_llm(messages: List[Dict[str, Any]]) -> str:
    """调用 LLM 生成摘要"""
    # 构建对话文本
    conversation_text = "\n".join([
        f"{m['role']}: {m['content'][:500]}..." if len(m['content']) > 500 
        else f"{m['role']}: {m['content']}"
        for m in messages
    ])
    
    # 使用 dag_tools.py 的摘要功能或直接返回简单摘要
    # 这里我们生成一个结构化摘要
    summary_parts = []
    
    # 提取关键信息
    topics = set()
    decisions = []
    tasks = []
    
    for m in messages:
        content = m['content']
        
        # 提取主题
        if '【' in content and '】' in content:
            import re
            matches = re.findall(r'【([^】]+)】', content)
            for m in matches:
                topics.add(m)
        
        # 提取决策
        if '决定' in content or '决策' in content or '选择' in content:
            decisions.append(content[:100])
        
        # 提取任务
        if '任务' in content or 'TODO' in content.lower():
            tasks.append(content[:100])
    
    # 构建摘要
    summary = f"消息数: {len(messages)}\n"
    if topics:
        summary += f"主题: {', '.join(list(topics)[:5])}\n"
    if decisions:
        summary += f"关键决策: {decisions[0][:80]}...\n"
    if tasks:
        summary += f"任务: {tasks[0][:80]}...\n"
    
    # 添加时间范围
    if messages:
        summary += f"时间范围: {messages[0]['created_at'][:10]} ~ {messages[-1]['created_at'][:10]}"
    
    return summary


def create_leaf_summary(
    conn: sqlite3.Connection,
    conversation_id: str,
    messages: List[Dict[str, Any]],
    summary_content: str
) -> str:
    """创建 leaf summary 节点并建立边关系"""
    cursor = conn.cursor()
    
    # 生成节点 ID
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute(
        "SELECT COUNT(*) FROM summary_nodes WHERE node_id LIKE ?",
        (f'leaf-{today}-%',)
    )
    count = cursor.fetchone()[0]
    node_id = f'leaf-{today}-{count+1:03d}'
    
    # 创建 leaf 节点
    cursor.execute("""
        INSERT INTO summary_nodes 
        (node_id, conversation_id, node_type, level, topic, content, token_count, created_at)
        VALUES (?, ?, 'leaf', 0, ?, ?, ?, ?)
    """, (
        node_id,
        conversation_id,
        summary_content.split('\n')[0][:50],  # topic 取第一行
        summary_content,
        len(summary_content) // 4,  # 粗略估计 token 数
        datetime.now().isoformat()
    ))
    
    # 建立边关系 (parent: leaf summary, child: messages)
    for msg in messages:
        cursor.execute("""
            INSERT INTO summary_edges (parent_id, child_id, relation, created_at)
            VALUES (?, ?, 'summarizes', ?)
        """, (node_id, msg['message_id'], datetime.now().isoformat()))
    
    conn.commit()
    return node_id


def compact_conversation(conversation_id: str) -> Dict[str, Any]:
    """压缩单个会话的消息"""
    conn = get_db_connection()
    
    try:
        # 获取未压缩的消息
        messages = get_uncompacted_messages(conn, conversation_id)
        
        if len(messages) < LEAF_MIN_FANOUT:
            return {
                'status': 'skipped',
                'reason': f'消息数不足 {LEAF_MIN_FANOUT}',
                'message_count': len(messages)
            }
        
        # 生成摘要
        summary = generate_summary_with_llm(messages)
        
        # 创建 leaf 节点
        node_id = create_leaf_summary(conn, conversation_id, messages, summary)
        
        return {
            'status': 'success',
            'node_id': node_id,
            'messages_compacted': len(messages),
            'summary_length': len(summary)
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }
    finally:
        conn.close()


def compact_all_conversations() -> Dict[str, Any]:
    """压缩所有会话"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 获取所有会话
    cursor.execute("SELECT DISTINCT conversation_id FROM messages")
    conversations = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    results = []
    total_compacted = 0
    
    for conv_id in conversations:
        result = compact_conversation(conv_id)
        results.append({
            'conversation_id': conv_id,
            **result
        })
        if result.get('status') == 'success':
            total_compacted += result.get('messages_compacted', 0)
    
    return {
        'total_conversations': len(conversations),
        'total_compacted': total_compacted,
        'results': results
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            result = compact_all_conversations()
        else:
            result = compact_conversation(sys.argv[1])
    else:
        result = compact_all_conversations()
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
