#!/usr/bin/env python3
"""
ContextAssembler - 上下文组装器
借鉴 lossless-claw 的设计理念

功能:
1. 根据可用 token 空间选择合适的摘要层级
2. 优先保留最新消息 (freshTailCount)
3. 用摘要填充剩余空间
4. 支持按需展开详情
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

IFLOW_DIR = Path.home() / ".iflow"
DB_PATH = IFLOW_DIR / "memory-dag" / "lcm.db"

# 配置参数 (借鉴 lossless-claw)
FRESH_TAIL_COUNT = 32  # 保护最近 N 条消息
CONTEXT_THRESHOLD = 0.75  # 上下文使用阈值
MAX_TOKENS_DEFAULT = 128000  # 默认最大 token 数


def get_db_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    return sqlite3.connect(str(DB_PATH))


def estimate_tokens(text: str) -> int:
    """估算文本 token 数 (粗略: 4 字符 = 1 token)"""
    if not text:
        return 0
    return len(text) // 4


def get_recent_messages(conn: sqlite3.Connection, conversation_id: str, count: int) -> List[Dict[str, Any]]:
    """获取最近的 N 条消息"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT message_id, role, content, created_at
        FROM messages
        WHERE conversation_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (conversation_id, count))
    
    messages = []
    for row in cursor.fetchall():
        messages.append({
            'message_id': row[0],
            'role': row[1],
            'content': row[2],
            'created_at': row[3]
        })
    
    return list(reversed(messages))  # 按时间正序返回


def get_summaries_at_level(conn: sqlite3.Connection, level: int) -> List[Dict[str, Any]]:
    """获取指定级别的所有摘要"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT node_id, topic, content, token_count, created_at
        FROM summary_nodes
        WHERE level = ?
        ORDER BY created_at ASC
    """, (level,))
    
    summaries = []
    for row in cursor.fetchall():
        summaries.append({
            'node_id': row[0],
            'topic': row[1],
            'content': row[2],
            'token_count': row[3],
            'created_at': row[4]
        })
    
    return summaries


def get_highest_summaries(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """获取最高级别的摘要 (优先使用更压缩的内容)"""
    cursor = conn.cursor()
    
    # 获取最大层级
    cursor.execute("SELECT MAX(level) FROM summary_nodes")
    max_level = cursor.fetchone()[0] or 0
    
    if max_level == 0:
        return []
    
    # 返回最高级别的摘要
    return get_summaries_at_level(conn, max_level)


def assemble_context(
    conversation_id: Optional[str] = None,
    max_tokens: int = MAX_TOKENS_DEFAULT,
    fresh_tail_count: int = FRESH_TAIL_COUNT
) -> Dict[str, Any]:
    """组装上下文"""
    conn = get_db_connection()
    
    try:
        context_parts = []
        total_tokens = 0
        
        # 1. 获取最高级别摘要 (历史背景)
        high_level_summaries = get_highest_summaries(conn)
        
        for summary in high_level_summaries:
            tokens = summary.get('token_count', 0) or estimate_tokens(summary.get('content', ''))
            if total_tokens + tokens < max_tokens * CONTEXT_THRESHOLD:
                context_parts.append({
                    'type': 'summary',
                    'level': 'high',
                    'node_id': summary['node_id'],
                    'topic': summary['topic'],
                    'content': summary['content'][:500] if summary.get('content') else '',
                    'tokens': tokens
                })
                total_tokens += tokens
        
        # 2. 如果有 conversation_id，获取最近消息
        recent_messages = []
        if conversation_id:
            recent_messages = get_recent_messages(conn, conversation_id, fresh_tail_count)
            
            # 保留 token 空间给最近消息
            reserved_for_recent = min(
                sum(estimate_tokens(m['content']) for m in recent_messages),
                max_tokens * (1 - CONTEXT_THRESHOLD)
            )
            
            # 如果最近消息超出预留空间，从摘要中扣除
            while total_tokens + reserved_for_recent > max_tokens and context_parts:
                removed = context_parts.pop(0)
                total_tokens -= removed['tokens']
        
        # 3. 组装最终上下文
        assembled = {
            'total_tokens': total_tokens + sum(estimate_tokens(m['content']) for m in recent_messages),
            'max_tokens': max_tokens,
            'context_parts': context_parts,
            'recent_messages': recent_messages,
            'summary_count': len(context_parts),
            'message_count': len(recent_messages)
        }
        
        return assembled
        
    finally:
        conn.close()


def format_context_for_prompt(assembled: Dict[str, Any]) -> str:
    """格式化上下文为 prompt 格式"""
    lines = []
    
    # 添加摘要
    if assembled.get('context_parts'):
        lines.append("=== 历史摘要 ===")
        for part in assembled['context_parts']:
            lines.append(f"[{part['node_id']}] {part['topic']}")
            if part.get('content'):
                lines.append(f"  {part['content'][:200]}...")
        lines.append("")
    
    # 添加最近消息
    if assembled.get('recent_messages'):
        lines.append("=== 最近对话 ===")
        for msg in assembled['recent_messages'][-10:]:  # 只显示最后10条
            role = msg['role']
            content = msg['content'][:100] + "..." if len(msg['content']) > 100 else msg['content']
            lines.append(f"{role}: {content}")
    
    return "\n".join(lines)


def get_conversation_context(conversation_id: str) -> Dict[str, Any]:
    """获取指定会话的完整上下文"""
    return assemble_context(conversation_id=conversation_id)


def get_all_summaries() -> Dict[str, Any]:
    """获取所有摘要概览"""
    conn = get_db_connection()
    
    try:
        cursor = conn.cursor()
        
        # 按级别统计
        cursor.execute("""
            SELECT level, COUNT(*), SUM(COALESCE(token_count, 0))
            FROM summary_nodes
            GROUP BY level
            ORDER BY level
        """)
        
        level_stats = []
        for row in cursor.fetchall():
            level_stats.append({
                'level': row[0],
                'node_count': row[1],
                'total_tokens': row[2] or 0
            })
        
        return {
            'levels': level_stats,
            'total_nodes': sum(s['node_count'] for s in level_stats),
            'total_tokens': sum(s['total_tokens'] for s in level_stats)
        }
        
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--summaries':
            result = get_all_summaries()
        elif sys.argv[1] == '--format':
            assembled = assemble_context()
            result = {'formatted': format_context_for_prompt(assembled), 'stats': assembled}
        else:
            conversation_id = sys.argv[1]
            result = get_conversation_context(conversation_id)
    else:
        result = assemble_context()
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
