#!/usr/bin/env python3
"""
ContextAssembler v2.0 - 上下文组装器
借鉴 lossless-claw 的设计理念

功能:
1. 根据 ordinal 排序选择上下文
2. 根据可用 token 空间选择合适的摘要层级
3. 优先保留最新消息 (freshTailCount)
4. 用摘要填充剩余空间
5. 支持 depth-aware prompt 模板
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

IFLOW_DIR = Path.home() / ".iflow"
DB_PATH = IFLOW_DIR / "memory-dag" / "lcm.db"

# 配置参数 (借鉴 lossless-claw)
FRESH_TAIL_COUNT = 32  # 保护最近 N 条消息
CONTEXT_THRESHOLD = 0.75  # 上下文使用阈值
MAX_TOKENS_DEFAULT = 128000  # 默认最大 token 数

# Depth-aware 配置
DEPTH_WEIGHTS = {
    'root': 0.3,      # root 摘要权重较低（更压缩）
    'branch': 0.5,    # branch 摘要中等权重
    'leaf': 0.7,      # leaf 摘要较高权重
    'message': 1.0    # 原始消息最高权重
}


def get_db_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def estimate_tokens(text: str) -> int:
    """估算文本 token 数 (粗略: 4 字符 = 1 token)"""
    if not text:
        return 0
    return len(text) // 4


def get_recent_messages(
    conn: sqlite3.Connection, 
    conversation_id: str, 
    count: int,
    use_ordinal: bool = True
) -> List[Dict[str, Any]]:
    """
    获取最近的 N 条消息
    按 ordinal 排序（如果存在），否则按 created_at
    """
    cursor = conn.cursor()
    
    # 检查是否存在 ordinal 列
    cursor.execute("PRAGMA table_info(messages)")
    columns = [col[1] for col in cursor.fetchall()]
    has_ordinal = 'ordinal' in columns
    
    if use_ordinal and has_ordinal:
        cursor.execute("""
            SELECT message_id, role, content, created_at, ordinal
            FROM messages
            WHERE conversation_id = ?
            ORDER BY ordinal DESC, created_at DESC
            LIMIT ?
        """, (conversation_id, count))
    else:
        cursor.execute("""
            SELECT message_id, role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (conversation_id, count))
    
    messages = []
    for row in cursor.fetchall():
        msg = {
            'message_id': row[0],
            'role': row[1],
            'content': row[2],
            'created_at': row[3]
        }
        if len(row) > 4 and row[4] is not None:
            msg['ordinal'] = row[4]
        messages.append(msg)
    
    return list(reversed(messages))  # 按时间正序返回


def get_summaries_at_level(
    conn: sqlite3.Connection, 
    level: int,
    conversation_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """获取指定级别的所有摘要，按时间排序"""
    cursor = conn.cursor()
    
    if conversation_id:
        cursor.execute("""
            SELECT node_id, conversation_id, topic, content, token_count, created_at
            FROM summary_nodes
            WHERE level = ? AND conversation_id = ?
            ORDER BY created_at ASC
        """, (level, conversation_id))
    else:
        cursor.execute("""
            SELECT node_id, conversation_id, topic, content, token_count, created_at
            FROM summary_nodes
            WHERE level = ?
            ORDER BY created_at ASC
        """, (level,))
    
    summaries = []
    for row in cursor.fetchall():
        summaries.append({
            'node_id': row[0],
            'conversation_id': row[1],
            'topic': row[2],
            'content': row[3],
            'token_count': row[4],
            'created_at': row[5]
        })
    
    return summaries


def get_summaries_by_type(
    conn: sqlite3.Connection,
    node_type: str,
    conversation_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """获取指定类型的所有摘要"""
    cursor = conn.cursor()
    
    if conversation_id:
        cursor.execute("""
            SELECT node_id, conversation_id, node_type, topic, content, token_count, level, created_at
            FROM summary_nodes
            WHERE node_type = ? AND conversation_id = ?
            ORDER BY created_at ASC
        """, (node_type, conversation_id))
    else:
        cursor.execute("""
            SELECT node_id, conversation_id, node_type, topic, content, token_count, level, created_at
            FROM summary_nodes
            WHERE node_type = ?
            ORDER BY created_at ASC
        """, (node_type,))
    
    summaries = []
    for row in cursor.fetchall():
        summaries.append({
            'node_id': row[0],
            'conversation_id': row[1],
            'node_type': row[2],
            'topic': row[3],
            'content': row[4],
            'token_count': row[5],
            'level': row[6],
            'created_at': row[7]
        })
    
    return summaries


def get_hierarchical_summaries(
    conn: sqlite3.Connection,
    conversation_id: Optional[str] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """
    获取层级化摘要
    返回: {'root': [...], 'branch': [...], 'leaf': [...]}
    """
    return {
        'root': get_summaries_by_type(conn, 'root', conversation_id),
        'branch': get_summaries_by_type(conn, 'branch', conversation_id),
        'leaf': get_summaries_by_type(conn, 'leaf', conversation_id)
    }


def calculate_depth_weight(content_length: int, node_type: str) -> float:
    """
    计算深度权重
    更高层级的摘要（更压缩）使用更低的权重
    """
    base_weight = DEPTH_WEIGHTS.get(node_type, 0.5)
    # 长内容稍微增加权重
    length_factor = min(1.0, content_length / 1000)
    return base_weight * (0.8 + 0.2 * length_factor)


def select_context_items(
    conn: sqlite3.Connection,
    max_tokens: int,
    conversation_id: Optional[str] = None,
    fresh_tail_count: int = FRESH_TAIL_COUNT
) -> List[Dict[str, Any]]:
    """
    智能选择上下文项
    策略：优先保留 fresh tail，然后用层级摘要填充剩余空间
    """
    context_items = []
    used_tokens = 0
    reserved_tokens = 0
    fresh_messages = []
    
    # 1. 预留空间给 fresh tail
    if conversation_id:
        fresh_messages = get_recent_messages(conn, conversation_id, fresh_tail_count)
        reserved_tokens = sum(estimate_tokens(m['content']) for m in fresh_messages)
        
        # 限制预留空间不超过总空间的 40%
        max_reserved = int(max_tokens * 0.4)
        if reserved_tokens > max_reserved:
            # 截断 fresh messages 以适应预留空间
            while fresh_messages and reserved_tokens > max_reserved:
                removed = fresh_messages.pop(0)  # 移除最早的
                reserved_tokens -= estimate_tokens(removed['content'])
    
    available_for_summaries = max_tokens - reserved_tokens
    
    # 2. 选择摘要填充空间 (从最高层级开始)
    hierarchy = get_hierarchical_summaries(conn, conversation_id)
    
    # 优先使用 root (最高压缩)
    for summary in hierarchy.get('root', []):
        tokens = estimate_tokens(summary.get('content', ''))
        if used_tokens + tokens <= available_for_summaries:
            weight = calculate_depth_weight(tokens, 'root')
            context_items.append({
                'type': 'summary',
                'node_type': 'root',
                'node_id': summary['node_id'],
                'topic': summary.get('topic', ''),
                'content': summary.get('content', ''),
                'tokens': tokens,
                'weight': weight
            })
            used_tokens += tokens
    
    # 然后 branch
    for summary in hierarchy.get('branch', []):
        tokens = estimate_tokens(summary.get('content', ''))
        if used_tokens + tokens <= available_for_summaries:
            weight = calculate_depth_weight(tokens, 'branch')
            context_items.append({
                'type': 'summary',
                'node_type': 'branch',
                'node_id': summary['node_id'],
                'topic': summary.get('topic', ''),
                'content': summary.get('content', ''),
                'tokens': tokens,
                'weight': weight
            })
            used_tokens += tokens
    
    # 最后 leaf (如果还有空间)
    remaining = available_for_summaries - used_tokens
    if remaining > 200:  # 至少留 200 tokens 才值得添加
        for summary in hierarchy.get('leaf', []):
            tokens = estimate_tokens(summary.get('content', ''))
            if used_tokens + tokens <= available_for_summaries:
                weight = calculate_depth_weight(tokens, 'leaf')
                context_items.append({
                    'type': 'summary',
                    'node_type': 'leaf',
                    'node_id': summary['node_id'],
                    'topic': summary.get('topic', ''),
                    'content': summary.get('content', ''),
                    'tokens': tokens,
                    'weight': weight
                })
                used_tokens += tokens
    
    # 3. 添加 fresh messages
    if conversation_id and fresh_messages:
        for msg in fresh_messages:
            tokens = estimate_tokens(msg['content'])
            context_items.append({
                'type': 'message',
                'node_type': 'message',
                'message_id': msg['message_id'],
                'role': msg['role'],
                'content': msg['content'],
                'tokens': tokens,
                'weight': DEPTH_WEIGHTS['message'],
                'ordinal': msg.get('ordinal', 0)
            })
    
    return context_items


def assemble_context(
    conversation_id: Optional[str] = None,
    max_tokens: int = MAX_TOKENS_DEFAULT,
    fresh_tail_count: int = FRESH_TAIL_COUNT
) -> Dict[str, Any]:
    """组装上下文"""
    conn = get_db_connection()
    
    try:
        # 选择上下文项
        context_items = select_context_items(
            conn, max_tokens, conversation_id, fresh_tail_count
        )
        
        # 分类统计
        by_type = {'root': [], 'branch': [], 'leaf': [], 'message': []}
        for item in context_items:
            node_type = item.get('node_type', 'unknown')
            if node_type in by_type:
                by_type[node_type].append(item)
        total_tokens = sum(item.get('tokens', 0) for item in context_items)
        
        return {
            'conversation_id': conversation_id,
            'total_tokens': total_tokens,
            'max_tokens': max_tokens,
            'usage_ratio': round(total_tokens / max_tokens, 2) if max_tokens > 0 else 0,
            'items_by_type': {
                k: len(v) for k, v in by_type.items()
            },
            'context_items': context_items,
            'summaries': {
                'root': by_type['root'],
                'branch': by_type['branch'],
                'leaf': by_type['leaf']
            },
            'recent_messages': by_type['message']
        }
        
    finally:
        conn.close()


def format_context_for_prompt(assembled: Dict[str, Any], style: str = 'default') -> str:
    """
    格式化上下文为 prompt 格式
    
    支持多种格式:
    - default: 标准格式
    - compact: 紧凑格式
    - depth-aware: 深度感知格式（根据权重调整详细程度）
    """
    lines = []
    context_items = assembled.get('context_items', [])
    
    if style == 'compact':
        # 紧凑格式：只显示 topic
        if context_items:
            lines.append("=== 上下文摘要 ===")
            for item in context_items:
                if item['type'] == 'summary':
                    lines.append(f"[{item['node_type']}] {item.get('topic', '')}")
                else:
                    role = item.get('role', 'user')
                    content = (item.get('content') or '')[:50] + "..."
                    lines.append(f"[{role}] {content}")
    
    elif style == 'depth-aware':
        # 深度感知格式：根据权重调整详细程度
        lines.append("=== 历史上下文 ===")
        
        for item in context_items:
            if item['type'] == 'summary':
                weight = item.get('weight', 0.5)
                node_type = item['node_type']
                topic = item.get('topic', '')
                content = item.get('content') or ''
                
                if weight > 0.6:
                    # 高权重：显示完整内容
                    lines.append(f"\n[{node_type.upper()}] {topic}")
                    lines.append(content[:500])
                elif weight > 0.4:
                    # 中等权重：显示摘要
                    lines.append(f"[{node_type}] {topic}")
                    lines.append(f"  {content[:200]}...")
                else:
                    # 低权重：只显示主题
                    lines.append(f"[{node_type}] {topic}")
            else:
                # 原始消息
                role = item.get('role', 'user')
                content = item.get('content') or ''
                lines.append(f"\n{role}: {content}")
    
    else:
        # 默认格式
        summaries = assembled.get('summaries', {})
        
        # 添加 root 摘要
        if summaries.get('root'):
            lines.append("=== 项目总览 ===")
            for s in summaries['root']:
                content = s.get('content') or ''
                lines.append(f"[ROOT] {s.get('topic', '')}")
                lines.append(f"  {content[:300]}...")
        
        # 添加 branch 摘要
        if summaries.get('branch'):
            lines.append("\n=== 阶段摘要 ===")
            for s in summaries['branch']:
                content = s.get('content') or ''
                lines.append(f"[BRANCH] {s.get('topic', '')}")
                lines.append(f"  {content[:200]}...")
        
        # 添加 leaf 摘要
        if summaries.get('leaf'):
            lines.append("\n=== 详细记录 ===")
            for s in summaries['leaf']:
                content = s.get('content') or ''
                lines.append(f"[LEAF] {s.get('topic', '')}")
                lines.append(f"  {content[:150]}...")
        
        # 添加最近消息
        messages = assembled.get('recent_messages', [])
        if messages:
            lines.append("\n=== 最近对话 ===")
            for msg in messages[-10:]:
                role = msg.get('role', 'user')
                content = msg.get('content') or ''
                content = content[:100] + "..." if len(content) > 100 else content
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
        
        # 按类型统计
        cursor.execute("""
            SELECT node_type, COUNT(*), SUM(COALESCE(token_count, 0))
            FROM summary_nodes
            GROUP BY node_type
            ORDER BY 
                CASE node_type 
                    WHEN 'root' THEN 1 
                    WHEN 'branch' THEN 2 
                    WHEN 'leaf' THEN 3 
                    ELSE 4 
                END
        """)
        
        type_stats = []
        for row in cursor.fetchall():
            type_stats.append({
                'type': row[0],
                'count': row[1],
                'total_tokens': row[2] or 0
            })
        
        # 获取层级深度
        cursor.execute("SELECT MAX(level) FROM summary_nodes")
        max_level = cursor.fetchone()[0] or 0
        
        return {
            'types': type_stats,
            'total_nodes': sum(s['count'] for s in type_stats),
            'total_tokens': sum(s['total_tokens'] for s in type_stats),
            'max_level': max_level
        }
        
    finally:
        conn.close()


def get_context_for_query(query: str, max_tokens: int = 4000) -> str:
    """
    根据查询获取相关上下文
    用于检索增强生成
    """
    # 简单实现：返回最近上下文的格式化版本
    assembled = assemble_context(max_tokens=max_tokens)
    return format_context_for_prompt(assembled, style='depth-aware')


def build_depth_aware_system_prompt(context_items: List[Dict[str, Any]]) -> str:
    """
    构建 depth-aware 系统提示
    借鉴 lossless-claw 的设计：当存在摘要时，添加 LCM 使用指导
    
    Guidance 只在存在摘要时生成，且深度越深提示越详细
    """
    summaries = [item for item in context_items if item.get('type') == 'summary']
    
    if not summaries:
        return ""
    
    # 计算最大深度
    max_depth = 0
    condensed_count = 0
    for s in summaries:
        node_type = s.get('node_type', 'leaf')
        if node_type == 'root':
            depth = 2
        elif node_type == 'branch':
            depth = 1
        else:
            depth = 0
        max_depth = max(max_depth, depth)
        if node_type in ('root', 'branch'):
            condensed_count += 1
    
    heavily_compacted = max_depth >= 2 or condensed_count >= 2
    
    sections = []
    
    # 核心召回工作流 - 总是存在
    sections.extend([
        "## LCM Recall",
        "",
        "上面的摘要是压缩的上下文 - 是细节的映射，而非细节本身。",
        "",
        "**召回优先级：** 优先使用 LCM 工具查询压缩的对话历史。如果 LCM 未覆盖所需数据，优先使用可用的记忆/召回工具，最后才回退到原始文本搜索。",
        "",
        "**工具升级链：**",
        "1. `dag_grep` - 按正则或全文搜索消息和摘要",
        "2. `dag_describe` - 查看特定摘要详情（低成本）",
        "3. `dag_tools.py` - 深度召回，扩展 DAG",
        "",
        "**精确性原则：** 不要从压缩摘要中猜测确切的命令、文件路径、时间戳、配置值或因果声明。需要时先扩展，或说明不确定。",
    ])
    
    # 深度压缩时的额外警告
    if heavily_compacted:
        sections.extend([
            "",
            "⚠ **深度压缩上下文 - 在断言细节前先扩展。**",
            "",
            "精确工作的默认召回流程：",
            "1) `dag_grep` 定位相关摘要/消息 ID",
            "2) 扩展查询获取具体内容",
            "3) 回答时引用使用的摘要 ID",
            "",
            "**不确定性检查清单（回答前运行）：**",
            "- 我是否从压缩摘要中做出精确的事实声明？",
            "- 压缩是否可能遗漏了关键细节？",
            "- 如果用户要求证据，这个答案会失败吗？",
            "",
            "如果以上任一为是 → 先扩展。",
        ])
    else:
        sections.extend([
            "",
            "**对于精确性/证据问题**（确切命令、路径、时间戳、配置值、根因链）：回答前先扩展。",
            "不要从压缩摘要中猜测 - 先扩展或说明不确定。",
        ])
    
    return "\n".join(sections)


def get_full_context_with_guidance(
    conversation_id: Optional[str] = None,
    max_tokens: int = MAX_TOKENS_DEFAULT
) -> Dict[str, Any]:
    """
    获取完整上下文，包含 depth-aware 系统提示指导
    用于实际对话场景
    """
    assembled = assemble_context(conversation_id=conversation_id, max_tokens=max_tokens)
    context_items = assembled.get('context_items', [])
    
    # 构建 depth-aware 系统提示
    system_prompt_addition = build_depth_aware_system_prompt(context_items)
    
    # 格式化上下文
    formatted_context = format_context_for_prompt(assembled, style='depth-aware')
    
    return {
        'context': formatted_context,
        'system_prompt_addition': system_prompt_addition,
        'stats': {
            'total_tokens': assembled['total_tokens'],
            'items_by_type': assembled['items_by_type'],
            'has_summaries': len([i for i in context_items if i.get('type') == 'summary']) > 0,
            'heavily_compacted': '⚠' in system_prompt_addition
        }
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--summaries':
            result = get_all_summaries()
        elif sys.argv[1] == '--format':
            style = sys.argv[2] if len(sys.argv) > 2 else 'default'
            assembled = assemble_context()
            result = {
                'formatted': format_context_for_prompt(assembled, style=style),
                'stats': {
                    'total_tokens': assembled['total_tokens'],
                    'items': assembled['items_by_type']
                }
            }
        elif sys.argv[1] == '--compact':
            assembled = assemble_context()
            result = {'formatted': format_context_for_prompt(assembled, style='compact')}
        elif sys.argv[1] == '--depth-aware':
            assembled = assemble_context()
            result = {'formatted': format_context_for_prompt(assembled, style='depth-aware')}
        elif sys.argv[1] == '--with-guidance':
            result = get_full_context_with_guidance()
        else:
            conversation_id = sys.argv[1]
            result = get_conversation_context(conversation_id)
    else:
        result = assemble_context()
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
