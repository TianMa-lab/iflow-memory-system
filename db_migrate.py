#!/usr/bin/env python3
"""
Database Migration Script for LCM (Lossless Context Memory)
添加 context_items 表和 ordinal 列支持
"""

import sqlite3
from pathlib import Path

IFLOW_DIR = Path.home() / ".iflow"
DB_PATH = IFLOW_DIR / "memory-dag" / "lcm.db"


def get_db_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    return sqlite3.connect(str(DB_PATH))


def check_table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    """检查表是否存在"""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def check_column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    """检查列是否存在"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [col[1] for col in cursor.fetchall()]
    return column_name in columns


def migrate_v1():
    """
    迁移版本 1: 
    - 添加 messages.ordinal 列
    - 创建 context_items 表
    - 创建索引
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    changes = []
    
    # 1. 添加 ordinal 列到 messages 表
    if check_table_exists(cursor, 'messages'):
        if not check_column_exists(cursor, 'messages', 'ordinal'):
            try:
                cursor.execute("""
                    ALTER TABLE messages ADD COLUMN ordinal INTEGER DEFAULT 0
                """)
                changes.append("Added 'ordinal' column to messages table")
                
                # 为现有消息设置 ordinal
                cursor.execute("""
                    UPDATE messages SET ordinal = (
                        SELECT COUNT(*) FROM messages m2 
                        WHERE m2.created_at <= messages.created_at
                    ) WHERE ordinal = 0
                """)
                changes.append("Initialized ordinal values for existing messages")
            except Exception as e:
                changes.append(f"Failed to add ordinal column: {e}")
    
    # 2. 创建 context_items 表
    if not check_table_exists(cursor, 'context_items'):
        cursor.execute("""
            CREATE TABLE context_items (
                item_id TEXT PRIMARY KEY,
                conversation_id TEXT,
                item_type TEXT NOT NULL,
                source_id TEXT,
                content TEXT,
                token_count INTEGER DEFAULT 0,
                weight REAL DEFAULT 1.0,
                depth_level INTEGER DEFAULT 0,
                created_at TEXT,
                metadata TEXT
            )
        """)
        changes.append("Created 'context_items' table")
    else:
        changes.append("'context_items' table already exists")
    
    # 3. 创建索引
    indexes = [
        ("idx_messages_ordinal", "CREATE INDEX IF NOT EXISTS idx_messages_ordinal ON messages(ordinal)"),
        ("idx_messages_conv_ordinal", "CREATE INDEX IF NOT EXISTS idx_messages_conv_ordinal ON messages(conversation_id, ordinal)"),
        ("idx_context_items_conv", "CREATE INDEX IF NOT EXISTS idx_context_items_conv ON context_items(conversation_id)"),
        ("idx_context_items_type", "CREATE INDEX IF NOT EXISTS idx_context_items_type ON context_items(item_type)"),
        ("idx_summary_nodes_type", "CREATE INDEX IF NOT EXISTS idx_summary_nodes_type ON summary_nodes(node_type)"),
        ("idx_summary_nodes_level", "CREATE INDEX IF NOT EXISTS idx_summary_nodes_level ON summary_nodes(level)"),
    ]
    
    for idx_name, idx_sql in indexes:
        try:
            cursor.execute(idx_sql)
            changes.append(f"Created index: {idx_name}")
        except Exception as e:
            changes.append(f"Index {idx_name}: {e}")
    
    # 4. 确保所有必要的表都存在
    required_tables = {
        'messages': """
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                created_at TEXT,
                ordinal INTEGER DEFAULT 0
            )
        """,
        'summary_nodes': """
            CREATE TABLE IF NOT EXISTS summary_nodes (
                node_id TEXT PRIMARY KEY,
                conversation_id TEXT,
                node_type TEXT NOT NULL,
                level INTEGER DEFAULT 0,
                topic TEXT,
                content TEXT,
                token_count INTEGER DEFAULT 0,
                created_at TEXT
            )
        """,
        'summary_edges': """
            CREATE TABLE IF NOT EXISTS summary_edges (
                edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id TEXT NOT NULL,
                child_id TEXT NOT NULL,
                relation TEXT DEFAULT 'summarizes',
                created_at TEXT
            )
        """
    }
    
    for table_name, create_sql in required_tables.items():
        if not check_table_exists(cursor, table_name):
            cursor.execute(create_sql)
            changes.append(f"Created missing table: {table_name}")
    
    conn.commit()
    conn.close()
    
    return changes


def get_db_version() -> int:
    """获取数据库版本"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if not check_table_exists(cursor, 'db_version'):
        conn.close()
        return 0
    
    cursor.execute("SELECT version FROM db_version ORDER BY version DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    
    return row[0] if row else 0


def set_db_version(version: int):
    """设置数据库版本"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if not check_table_exists(cursor, 'db_version'):
        cursor.execute("""
            CREATE TABLE db_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT
            )
        """)
    
    cursor.execute(
        "INSERT OR REPLACE INTO db_version (version, applied_at) VALUES (?, datetime('now'))",
        (version,)
    )
    
    conn.commit()
    conn.close()


def run_migrations():
    """运行所有迁移"""
    current_version = get_db_version()
    print(f"Current DB version: {current_version}")
    
    migrations = [
        (1, migrate_v1, "Add ordinal column, context_items table, indexes"),
    ]
    
    for version, migrate_func, description in migrations:
        if version > current_version:
            print(f"\nRunning migration v{version}: {description}")
            changes = migrate_func()
            for change in changes:
                print(f"  - {change}")
            set_db_version(version)
            print(f"Migration v{version} completed")
    
    print("\nAll migrations completed!")


def show_db_stats():
    """显示数据库统计信息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    print("\n=== Database Statistics ===\n")
    
    # 表统计
    tables = ['messages', 'summary_nodes', 'summary_edges', 'context_items']
    
    for table in tables:
        if check_table_exists(cursor, table):
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"{table}: {count} rows")
        else:
            print(f"{table}: NOT EXISTS")
    
    # 摘要节点按类型统计
    if check_table_exists(cursor, 'summary_nodes'):
        print("\n--- Summary Nodes by Type ---")
        cursor.execute("""
            SELECT node_type, COUNT(*), SUM(COALESCE(token_count, 0))
            FROM summary_nodes
            GROUP BY node_type
        """)
        for row in cursor.fetchall():
            print(f"  {row[0]}: {row[1]} nodes, {row[2]} tokens")
    
    conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--stats':
            show_db_stats()
        elif sys.argv[1] == '--version':
            print(f"DB Version: {get_db_version()}")
        else:
            print("Usage: python db_migrate.py [--stats|--version]")
    else:
        run_migrations()
        show_db_stats()
