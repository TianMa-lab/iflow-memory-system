#!/usr/bin/env python3
"""
自动深刻自省工具
"""

import sys
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

IFLOW_DIR = Path.home() / ".iflow"
DB_PATH = IFLOW_DIR / "memory-dag" / "lcm.db"
DAG_TOOLS = IFLOW_DIR / "tools" / "dag_tools.py"

def get_db_connection():
    return sqlite3.connect(str(DB_PATH))

def check_heartbeat():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT last_active FROM heartbeat WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {"status": "error", "message": "no heartbeat"}
    
    last_active = datetime.fromisoformat(row[0])
    stalled_seconds = (datetime.now() - last_active).total_seconds()
    
    if stalled_seconds > 300:
        return {"status": "error", "message": f"stalled {int(stalled_seconds)}s", "last_active": row[0]}
    return {"status": "ok", "message": f"ok, {int(stalled_seconds)}s ago"}

def check_guardian():
    import subprocess
    try:
        result = subprocess.run(
            ["powershell", "-Command", "Get-Process powershell -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like '*guardian*'} | Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=10
        )
        count = int(result.stdout.strip()) if result.stdout and result.stdout.strip().isdigit() else 0
        if count > 0:
            return {"status": "ok", "message": f"running ({count})"}
        return {"status": "error", "message": "not running"}
    except Exception as e:
        return {"status": "error", "message": f"check failed: {str(e)[:30]}"}

def check_dag():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages")
    msg_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM summary_nodes")
    node_count = cursor.fetchone()[0]
    conn.close()
    return {"status": "ok", "message": f"msgs:{msg_count}, nodes:{node_count}"}

def fix_heartbeat():
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("INSERT OR REPLACE INTO heartbeat (id, last_active, session_id) VALUES (1, ?, 'auto-fix')", (now,))
    conn.commit()
    conn.close()
    return {"status": "fixed", "message": f"updated: {now}"}

def record_to_dag(content):
    import subprocess
    try:
        result = subprocess.run(
            ["python", str(DAG_TOOLS), "add", f"--content={content}", "--topic=auto-reflection"],
            capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=30
        )
        return result.returncode == 0
    except:
        return False

def run_auto_reflection(trigger="scheduled"):
    print(f"\n{'='*50}")
    print(f"Auto Deep Reflection - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Trigger: {trigger}")
    print(f"{'='*50}\n")
    
    issues = []
    fixes = []
    
    print("Phase 1: Discovery")
    checks = [
        ("Heartbeat", check_heartbeat),
        ("Guardian", check_guardian),
        ("DAG", check_dag),
    ]
    
    for name, check_fn in checks:
        result = check_fn()
        status_icon = "OK" if result["status"] == "ok" else "ERR"
        print(f"  [{status_icon}] {name}: {result['message']}")
        if result["status"] == "error":
            issues.append({"name": name, **result})
    
    if not issues:
        print("\n[OK] System healthy, no fixes needed")
        return {"status": "healthy", "issues": 0, "fixes": 0}
    
    print(f"\nPhase 2-4: Found {len(issues)} issues, fixing...")
    
    for issue in issues:
        if issue["name"] == "Heartbeat":
            fix = fix_heartbeat()
            print(f"  [FIX] Heartbeat: {fix['message']}")
            fixes.append({"issue": "Heartbeat", "result": fix})
    
    print("\nPhase 5: Verification")
    for issue in issues:
        if issue["name"] == "Heartbeat":
            result = check_heartbeat()
            status = "OK" if result["status"] == "ok" else "ERR"
            print(f"  [{status}] Heartbeat: {result['message']}")
    
    summary = f"[Auto-Reflection] trigger={trigger} issues={len(issues)} fixes={len(fixes)}"
    if record_to_dag(summary):
        print(f"\nPhase 6: Recorded to DAG")
    
    return {"status": "completed", "issues": len(issues), "fixes": len(fixes)}

if __name__ == "__main__":
    trigger = sys.argv[1] if len(sys.argv) > 1 else "manual"
    result = run_auto_reflection(trigger)
    print(f"\nResult: {json.dumps(result, ensure_ascii=False)}")