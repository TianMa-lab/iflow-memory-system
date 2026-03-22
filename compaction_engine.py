#!/usr/bin/env python3
"""
CompactionEngine v2.0 - 自动压缩消息为多级摘要
借鉴 lossless-claw 的三阶段压缩设计

功能:
1. 检测需要压缩的消息块
2. 调用 LLM 生成摘要 (支持 LM Studio API)
3. 创建多级 summary 节点 (leaf -> branch -> root)
4. 建立 DAG 边关系
5. 三阶段压缩 escalation 机制
"""

import sqlite3
import json
import subprocess
import requests
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

IFLOW_DIR = Path.home() / ".iflow"
DB_PATH = IFLOW_DIR / "memory-dag" / "lcm.db"

# ============ 配置参数 (借鉴 lossless-claw) ============
LEAF_MIN_FANOUT = 8       # leaf 最少消息数才触发压缩
BRANCH_MIN_FANOUT = 4     # branch 最少 leaf 数才触发升级
ROOT_MIN_FANOUT = 3       # root 最少 branch 数

LEAF_TARGET_TOKENS = 1200    # leaf 目标摘要 token 数
BRANCH_TARGET_TOKENS = 800   # branch 目标摘要 token 数
ROOT_TARGET_TOKENS = 500     # root 目标摘要 token 数

FRESH_TAIL_COUNT = 32     # 保护最近 N 条消息不被压缩
MAX_LEAF_SIZE = 16        # 单个 leaf 最大消息数

# LM Studio API 配置
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_STUDIO_TIMEOUT = 60


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


def call_llm_for_summary(messages: List[Dict[str, Any]], target_tokens: int = 500) -> str:
    """
    调用 LLM 生成摘要
    支持两种方式：
    1. LM Studio API (优先)
    2. OpenClaw CLI (fallback)
    """
    # 构建对话文本
    conversation_text = "\n".join([
        f"{m.get('role', 'user')}: {m.get('content', '')[:800]}"
        for m in messages[:20]  # 限制输入长度
    ])
    
    prompt = f"""请将以下对话压缩为简洁的摘要（约 {target_tokens} tokens）。

要求：
1. 提取关键决策、重要信息、任务进度
2. 使用简洁的中文
3. 保留重要的事实和数据
4. 格式：【主题】关键要点

对话内容：
{conversation_text}

摘要："""
    
    # 方式1: 尝试 LM Studio API
    try:
        response = requests.post(
            LM_STUDIO_URL,
            json={
                "model": "local-model",
                "messages": [
                    {"role": "system", "content": "你是一个专业的对话摘要助手。"},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": target_tokens * 2,
                "temperature": 0.3
            },
            timeout=LM_STUDIO_TIMEOUT
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                return content.strip()
    except requests.exceptions.ConnectionError:
        pass  # LM Studio 未启动，尝试其他方式
    except requests.exceptions.Timeout:
        pass  # 超时，尝试其他方式
    except Exception:
        pass
    
    # 方式2: 尝试 OpenClaw CLI
    try:
        result = subprocess.run(
            ["openclaw", "chat", "--prompt", prompt],
            capture_output=True,
            text=True,
            timeout=LM_STUDIO_TIMEOUT
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:target_tokens * 4]
    except FileNotFoundError:
        pass  # openclaw 未安装
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    
    # 方式3: 本地简单摘要 (fallback)
    return generate_local_summary(messages)


def generate_local_summary(messages: List[Dict[str, Any]]) -> str:
    """本地生成简单摘要（不依赖 LLM）"""
    summary_parts = []
    
    # 提取关键信息
    topics = set()
    decisions = []
    tasks = []
    key_facts = []
    
    for m in messages:
        content = m.get('content', '')
        
        # 提取主题
        topic_matches = re.findall(r'【([^】]+)】', content)
        topics.update(topic_matches[:3])
        
        # 提取决策
        if any(kw in content for kw in ['决定', '决策', '选择', '采用', '确定']):
            decisions.append(content[:150])
        
        # 提取任务
        if any(kw in content for kw in ['任务', 'TODO', '待办', '完成', '进度']):
            tasks.append(content[:150])
        
        # 提取关键事实
        if any(kw in content for kw in ['版本', '配置', '修复', '功能', '更新']):
            key_facts.append(content[:100])
    
    
    # 构建摘要
    if topics:
        summary_parts.append(f"【主题】{', '.join(list(topics)[:5])}")
    
    if decisions:
        summary_parts.append(f"【决策】{decisions[0][:100]}...")
    
    if tasks:
        summary_parts.append(f"【任务】{tasks[0][:100]}...")
    
    if key_facts:
        summary_parts.append(f"【关键】{key_facts[0][:80]}...")
    
    summary_parts.append(f"【消息数】{len(messages)}")
    
    # 添加时间范围
    if messages:
        first_time = messages[0].get('created_at', '')[:10]
        last_time = messages[-1].get('created_at', '')[:10]
        if first_time and last_time:
            summary_parts.append(f"【时间】{first_time} ~ {last_time}")
    
    
    return "\n".join(summary_parts) if summary_parts else f"摘要：{len(messages)} 条消息"


def count_messages_in_conversation(conn: sqlite3.Connection, conversation_id: str) -> int:
    """统计会话中的消息数"""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
        (conversation_id,)
    )
    return cursor.fetchone()[0]


def get_all_conversations(conn: sqlite3.Connection) -> List[str]:
    """获取所有会话 ID"""
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT conversation_id FROM messages")
    return [row[0] for row in cursor.fetchall()]


def get_uncompacted_messages(
    conn: sqlite3.Connection, 
    conversation_id: str,
    fresh_tail_count: int = FRESH_TAIL_COUNT
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    获取未被压缩的消息
    返回: (可压缩的消息, 受保护的新消息)
    
    修复: fresh tail protection 应该保护最后 N 条消息，
         而不是按索引位置判断
    """
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
    
    # 获取所有消息，按时间排序
    cursor.execute("""
        SELECT message_id, role, content, created_at, ordinal
        FROM messages 
        WHERE conversation_id = ?
        ORDER BY ordinal ASC, created_at ASC
    """, (conversation_id,))
    
    all_messages = []
    for row in cursor.fetchall():
        all_messages.append({
            'message_id': row[0],
            'role': row[1],
            'content': row[2],
            'created_at': row[3],
            'ordinal': row[4] if len(row) > 4 else 0
        })
    
    # 分离：可压缩的 + 受保护的
    total_count = len(all_messages)
    protected_start = max(0, total_count - fresh_tail_count)
    
    uncompacted = []
    protected = []
    
    for i, msg in enumerate(all_messages):
        if msg['message_id'] in compacted_ids:
            continue  # 已压缩，跳过
        
        if i >= protected_start:
            protected.append(msg)  # 受保护的 fresh tail
        else:
            uncompacted.append(msg)  # 可压缩的
    
    return uncompacted, protected


def create_summary_node(
    conn: sqlite3.Connection,
    conversation_id: str,
    node_type: str,
    level: int,
    content: str,
    child_ids: List[str],
    topic: str = ""
) -> str:
    """创建摘要节点并建立边关系"""
    cursor = conn.cursor()
    
    # 生成节点 ID
    today = datetime.now().strftime('%Y-%m-%d')
    prefix = node_type  # leaf, branch, root
    
    cursor.execute(
        "SELECT COUNT(*) FROM summary_nodes WHERE node_id LIKE ?",
        (f'{prefix}-{today}-%',)
    )
    count = cursor.fetchone()[0]
    node_id = f'{prefix}-{today}-{count+1:03d}'
    
    # 计算 token 数
    token_count = estimate_tokens(content)
    
    # 创建节点
    cursor.execute("""
        INSERT INTO summary_nodes 
        (node_id, conversation_id, node_type, level, topic, content, token_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        node_id,
        conversation_id,
        node_type,
        level,
        topic or content[:50],
        content,
        token_count,
        datetime.now().isoformat()
    ))
    
    # 建立边关系 (parent: summary, child: messages or sub-summaries)
    for child_id in child_ids:
        cursor.execute("""
            INSERT INTO summary_edges (parent_id, child_id, relation, created_at)
            VALUES (?, ?, 'summarizes', ?)
        """, (node_id, child_id, datetime.now().isoformat()))
    
    conn.commit()
    return node_id


def get_leaf_nodes_for_branch(
    conn: sqlite3.Connection,
    conversation_id: str,
    min_count: int = BRANCH_MIN_FANOUT
) -> List[Dict[str, Any]]:
    """获取可用于创建 branch 的 leaf 节点"""
    cursor = conn.cursor()
    
    # 获取未被 branch 包含的 leaf 节点
    cursor.execute("""
        SELECT n.node_id, n.topic, n.content, n.token_count, n.created_at
        FROM summary_nodes n
        WHERE n.conversation_id = ?
        AND n.node_type = 'leaf'
        AND n.node_id NOT IN (
            SELECT DISTINCT e.child_id 
            FROM summary_edges e 
            JOIN summary_nodes pn ON pn.node_id = e.parent_id
            WHERE pn.node_type = 'branch'
        )
        ORDER BY n.created_at ASC
    """, (conversation_id,))
    
    leaves = []
    for row in cursor.fetchall():
        leaves.append({
            'node_id': row[0],
            'topic': row[1],
            'content': row[2],
            'token_count': row[3],
            'created_at': row[4]
        })
    
    return leaves


def get_branch_nodes_for_root(
    conn: sqlite3.Connection,
    conversation_id: str,
    min_count: int = ROOT_MIN_FANOUT
) -> List[Dict[str, Any]]:
    """获取可用于创建 root 的 branch 节点"""
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT n.node_id, n.topic, n.content, n.token_count, n.created_at
        FROM summary_nodes n
        WHERE n.conversation_id = ?
        AND n.node_type = 'branch'
        AND n.node_id NOT IN (
            SELECT DISTINCT e.child_id 
            FROM summary_edges e 
            JOIN summary_nodes pn ON pn.node_id = e.parent_id
            WHERE pn.node_type = 'root'
        )
        ORDER BY n.created_at ASC
    """, (conversation_id,))
    
    branches = []
    for row in cursor.fetchall():
        branches.append({
            'node_id': row[0],
            'topic': row[1],
            'content': row[2],
            'token_count': row[3],
            'created_at': row[4]
        })
    
    return branches


def compact_to_leaf(conversation_id: str, use_llm: bool = True) -> Dict[str, Any]:
    """
    阶段1: 压缩消息到 leaf summary
    """
    conn = get_db_connection()
    
    try:
        uncompacted, protected = get_uncompacted_messages(conn, conversation_id)
        
        if len(uncompacted) < LEAF_MIN_FANOUT:
            return {
                'status': 'skipped',
                'reason': f'消息数不足 {LEAF_MIN_FANOUT}',
                'available': len(uncompacted),
                'protected': len(protected)
            }
        
        # 分批压缩 (每批最多 MAX_LEAF_SIZE 条消息)
        results = []
        batches = [uncompacted[i:i+MAX_LEAF_SIZE] for i in range(0, len(uncompacted), MAX_LEAF_SIZE)]
        
        for batch in batches:
            if len(batch) < LEAF_MIN_FANOUT:
                continue
            
            # 生成摘要
            if use_llm:
                summary = call_llm_for_summary(batch, LEAF_TARGET_TOKENS)
            else:
                summary = generate_local_summary(batch)
            
            # 创建 leaf 节点
            message_ids = [m['message_id'] for m in batch]
            node_id = create_summary_node(
                conn, conversation_id, 'leaf', 0, summary, message_ids
            )
            
            results.append({
                'node_id': node_id,
                'messages_compacted': len(batch),
                'summary_length': len(summary)
            })
        
        return {
            'status': 'success',
            'type': 'leaf',
            'batches': len(results),
            'total_compacted': sum(r['messages_compacted'] for r in results),
            'protected': len(protected),
            'results': results
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }
    finally:
        conn.close()


def escalate_to_branch(conversation_id: str, use_llm: bool = True) -> Dict[str, Any]:
    """
    阶段2: 升级 leaf 节点到 branch summary
    """
    conn = get_db_connection()
    
    try:
        leaves = get_leaf_nodes_for_branch(conn, conversation_id)
        
        if len(leaves) < BRANCH_MIN_FANOUT:
            return {
                'status': 'skipped',
                'reason': f'leaf 节点数不足 {BRANCH_MIN_FANOUT}',
                'available': len(leaves)
            }
        
        # 合并 leaf 节点为 branch
        results = []
        batches = [leaves[i:i+BRANCH_MIN_FANOUT*2] for i in range(0, len(leaves), BRANCH_MIN_FANOUT*2)]
        
        for batch in batches:
            if len(batch) < BRANCH_MIN_FANOUT:
                continue
            
            # 使用 leaf 摘要生成更高层摘要
            leaf_summaries = [{'role': 'summary', 'content': l['content']} for l in batch]
            
            if use_llm:
                summary = call_llm_for_summary(leaf_summaries, BRANCH_TARGET_TOKENS)
            else:
                summary = generate_local_summary(leaf_summaries)
            
            # 创建 branch 节点
            leaf_ids = [l['node_id'] for l in batch]
            node_id = create_summary_node(
                conn, conversation_id, 'branch', 1, summary, leaf_ids
            )
            
            results.append({
                'node_id': node_id,
                'leaves_compacted': len(batch),
                'summary_length': len(summary)
            })
        
        return {
            'status': 'success',
            'type': 'branch',
            'batches': len(results),
            'total_leaves': sum(r['leaves_compacted'] for r in results),
            'results': results
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }
    finally:
        conn.close()


def escalate_to_root(conversation_id: str, use_llm: bool = True) -> Dict[str, Any]:
    """
    阶段3: 升级 branch 节点到 root summary
    """
    conn = get_db_connection()
    
    try:
        branches = get_branch_nodes_for_root(conn, conversation_id)
        
        if len(branches) < ROOT_MIN_FANOUT:
            return {
                'status': 'skipped',
                'reason': f'branch 节点数不足 {ROOT_MIN_FANOUT}',
                'available': len(branches)
            }
        
        
        # 合并 branch 节点为 root
        branch_summaries = [{'role': 'summary', 'content': b['content']} for b in branches]
        
        if use_llm:
            summary = call_llm_for_summary(branch_summaries, ROOT_TARGET_TOKENS)
        else:
            summary = generate_local_summary(branch_summaries)
        
        # 创建 root 节点
        branch_ids = [b['node_id'] for b in branches]
        node_id = create_summary_node(
            conn, conversation_id, 'root', 2, summary, branch_ids
        )
        
        return {
            'status': 'success',
            'type': 'root',
            'node_id': node_id,
            'branches_compacted': len(branches),
            'summary_length': len(summary)
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }
    finally:
        conn.close()


def run_full_compaction(conversation_id: str, use_llm: bool = True) -> Dict[str, Any]:
    """
    执行完整的三阶段压缩流程
    """
    results = {
        'conversation_id': conversation_id,
        'stages': {}
    }
    
    # 阶段1: 消息 -> leaf
    leaf_result = compact_to_leaf(conversation_id, use_llm)
    results['stages']['leaf'] = leaf_result
    
    # 阶段2: leaf -> branch (如果阶段1有产出)
    if leaf_result.get('status') == 'success':
        branch_result = escalate_to_branch(conversation_id, use_llm)
        results['stages']['branch'] = branch_result
        
        # 阶段3: branch -> root (如果阶段2有产出)
        if branch_result.get('status') == 'success':
            root_result = escalate_to_root(conversation_id, use_llm)
            results['stages']['root'] = root_result
    
    return results


def compact_all_conversations(use_llm: bool = True) -> Dict[str, Any]:
    """压缩所有会话"""
    conn = get_db_connection()
    conversations = get_all_conversations(conn)
    conn.close()
    
    results = []
    total_stats = {
        'leaf_created': 0,
        'branch_created': 0,
        'root_created': 0,
        'messages_compacted': 0
    }
    
    for conv_id in conversations:
        result = run_full_compaction(conv_id, use_llm)
        results.append(result)
        
        # 统计
        for stage, stage_result in result.get('stages', {}).items():
            if stage_result.get('status') == 'success':
                if stage == 'leaf':
                    total_stats['leaf_created'] += stage_result.get('batches', 0)
                    total_stats['messages_compacted'] += stage_result.get('total_compacted', 0)
                elif stage == 'branch':
                    total_stats['branch_created'] += stage_result.get('batches', 0)
                elif stage == 'root':
                    total_stats['root_created'] += 1
    
    return {
        'total_conversations': len(conversations),
        'stats': total_stats,
        'results': results
    }


def get_compaction_status() -> Dict[str, Any]:
    """获取压缩状态统计"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 按类型统计节点
        cursor.execute("""
            SELECT node_type, COUNT(*), SUM(COALESCE(token_count, 0))
            FROM summary_nodes
            GROUP BY node_type
        """)
        
        node_stats = {}
        for row in cursor.fetchall():
            node_stats[row[0]] = {
                'count': row[1],
                'total_tokens': row[2] or 0
            }
        
        # 统计消息覆盖率
        cursor.execute("SELECT COUNT(*) FROM messages")
        total_messages = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(DISTINCT e.child_id)
            FROM summary_edges e
            JOIN summary_nodes n ON n.node_id = e.parent_id
            WHERE n.node_type = 'leaf'
        """)
        compacted_messages = cursor.fetchone()[0]
        
        return {
            'nodes': node_stats,
            'messages': {
                'total': total_messages,
                'compacted': compacted_messages,
                'coverage': round(compacted_messages / max(total_messages, 1) * 100, 1)
            }
        }
        
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    
    # 解析参数
    use_llm = "--no-llm" not in sys.argv
    
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        
        if arg == '--all':
            result = compact_all_conversations(use_llm)
        elif arg == '--status':
            result = get_compaction_status()
        elif arg == '--test-llm':
            # 测试 LLM 连接
            test_messages = [{'role': 'user', 'content': '这是一个测试消息'}]
            summary = call_llm_for_summary(test_messages, 100)
            result = {'llm_test': summary}
        else:
            conversation_id = arg
            result = run_full_compaction(conversation_id, use_llm)
    else:
        result = compact_all_conversations(use_llm)
    
    print(json.dumps(result, ensure_ascii=False, indent=2))