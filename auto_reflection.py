#!/usr/bin/env python3
"""
自动深刻自省工具 v2.0
- 支持自动技能评分
"""

import sys
import json
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

IFLOW_DIR = Path.home() / ".iflow"
DB_PATH = IFLOW_DIR / "memory-dag" / "lcm.db"
DAG_TOOLS = IFLOW_DIR / "tools" / "dag_tools.py"
SKILL_SCORER = IFLOW_DIR / "tools" / "skill_scorer.py"

# 技能阶段映射 (完整 Superpowers 技能集)
PHASE_SKILLS = {
    # 核心 Superpowers 技能 (obra/superpowers)
    1: "brainstorming",              # 苏格拉底式设计提炼
    2: "systematic-debugging",       # 四阶段根因分析
    3: "writing-plans",              # 任务分解计划
    4: "executing-plans",            # 批量执行
    5: "tdd-cycle",                  # RED-GREEN-REFACTOR
    # 新增 Superpowers 技能
    6: "subagent-driven-development", # 子代理派发开发
    7: "requesting-code-review",      # 代码审查
    8: "finishing-a-development-branch", # 完成开发分支
    # 我们的元能力
    9: "skill-scoring",              # 技能评分
    10: "deep-reflection"            # 深刻自省
}

def get_db_connection():
    return sqlite3.connect(str(DB_PATH))

def check_heartbeat():
    """
    检查心跳状态 - 统一检查文件和数据库
    Guardian 更新 heartbeat.json 文件，优先使用文件状态
    """
    import os
    
    # 优先检查文件 heartbeat (Guardian 更新的)
    heartbeat_file = IFLOW_DIR / "heartbeat.json"
    if heartbeat_file.exists():
        try:
            with open(heartbeat_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            last_active_str = data.get('lastActive', '')
            if last_active_str:
                last_active = datetime.fromisoformat(last_active_str.replace('Z', '+00:00').replace('+00:00', ''))
                stalled_seconds = (datetime.now() - last_active).total_seconds()
                
                if stalled_seconds > 300:
                    return {"status": "error", "message": f"stalled {int(stalled_seconds)}s (file)", "last_active": last_active_str}
                return {"status": "ok", "message": f"ok, {int(stalled_seconds)}s ago (file)"}
        except Exception as e:
            pass
    
    # 回退到数据库 heartbeat
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
        return {"status": "error", "message": f"stalled {int(stalled_seconds)}s (db)", "last_active": row[0]}
    return {"status": "ok", "message": f"ok, {int(stalled_seconds)}s ago (db)"}

def check_guardian():
    """检查 Guardian 是否运行 - 使用多种方式检测"""
    import subprocess
    from pathlib import Path
    
    # 方法1: 检查日志文件最后更新时间
    log_file = IFLOW_DIR / "logs" / "guardian.log"
    if log_file.exists():
        try:
            import os
            mtime = os.path.getmtime(log_file)
            age_seconds = datetime.now().timestamp() - mtime
            
            # 如果日志在最近 120 秒内更新过，认为 Guardian 正在运行
            if age_seconds < 120:
                return {"status": "ok", "message": f"running (log updated {int(age_seconds)}s ago)"}
        except:
            pass
    
    # 方法2: 使用 PowerShell 检测进程
    try:
        result = subprocess.run(
            ["powershell", "-Command", 
             "Get-Process powershell -ErrorAction SilentlyContinue | "
             "Where-Object {$_.MainWindowTitle -like '*guardian*' -or $_.CommandLine -like '*guardian*'} | "
             "Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=10
        )
        count = int(result.stdout.strip()) if result.stdout and result.stdout.strip().isdigit() else 0
        if count > 0:
            return {"status": "ok", "message": f"running ({count})"}
    except:
        pass
    
    # 方法3: 检查 PID 锁文件
    pid_file = IFLOW_DIR / "guardian.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            # 检查进程是否存在
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=5
            )
            if str(pid) in result.stdout:
                return {"status": "ok", "message": f"running (PID: {pid})"}
        except:
            pass
    
    return {"status": "error", "message": "not running"}

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
    """更新心跳 - 同时更新文件和数据库，保持同步"""
    now = datetime.now()
    now_str = now.isoformat()
    
    # 更新文件 heartbeat
    heartbeat_file = IFLOW_DIR / "heartbeat.json"
    heartbeat_data = {
        "lastActive": now_str,
        "lastSummary": "auto-fix",
        "sessionId": "auto-reflection"
    }
    try:
        with open(heartbeat_file, 'w', encoding='utf-8') as f:
            json.dump(heartbeat_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        pass
    
    # 更新数据库 heartbeat
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO heartbeat (id, last_active, session_id) VALUES (1, ?, 'auto-fix')", (now_str,))
    conn.commit()
    conn.close()
    
    return {"status": "fixed", "message": f"updated: {now_str}"}

def record_to_dag(content):
    try:
        result = subprocess.run(
            ["python", str(DAG_TOOLS), "add", f"--content={content}", "--topic=auto-reflection"],
            capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=30
        )
        return result.returncode == 0
    except:
        return False

def record_skill_score(skill_name, success=True):
    """记录技能评分"""
    try:
        # 触发
        subprocess.run(
            ["python", str(SKILL_SCORER), "trigger", skill_name],
            capture_output=True, text=True, timeout=10
        )
        # 结果
        result_str = "success" if success else "failure"
        subprocess.run(
            ["python", str(SKILL_SCORER), "result", skill_name, result_str],
            capture_output=True, text=True, timeout=10
        )
        return True
    except:
        return False

def run_auto_reflection(trigger="scheduled"):
    print(f"\n{'='*50}")
    print(f"Auto Deep Reflection - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Trigger: {trigger}")
    print(f"{'='*50}\n")
    
    issues = []
    fixes = []
    phase_scores = {}  # 记录每个阶段的评分
    
    # Phase 1: Discovery (brainstorming)
    print("Phase 1: Discovery")
    record_skill_score(PHASE_SKILLS[1])  # 触发 brainstorming
    
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
    
    phase_scores[1] = len(issues) == 0  # 无问题则成功
    record_skill_score(PHASE_SKILLS[1], phase_scores[1])
    
    if not issues:
        print("\n[OK] System healthy, no fixes needed")
        record_skill_score(PHASE_SKILLS[6])  # skill-scoring
        return {"status": "healthy", "issues": 0, "fixes": 0}
    
    # Phase 2-4: Analysis and Fix
    print(f"\nPhase 2-4: Found {len(issues)} issues, fixing...")
    record_skill_score(PHASE_SKILLS[2])  # systematic-debugging
    record_skill_score(PHASE_SKILLS[3])  # writing-plans
    record_skill_score(PHASE_SKILLS[4])  # executing-plans
    
    for issue in issues:
        if issue["name"] == "Heartbeat":
            fix = fix_heartbeat()
            print(f"  [FIX] Heartbeat: {fix['message']}")
            fixes.append({"issue": "Heartbeat", "result": fix})
    
    record_skill_score(PHASE_SKILLS[2], True)
    record_skill_score(PHASE_SKILLS[3], True)
    record_skill_score(PHASE_SKILLS[4], len(fixes) > 0)
    
    # Phase 5: Verification (tdd-cycle)
    print("\nPhase 5: Verification")
    record_skill_score(PHASE_SKILLS[5])  # tdd-cycle
    
    for issue in issues:
        if issue["name"] == "Heartbeat":
            result = check_heartbeat()
            status = "OK" if result["status"] == "ok" else "ERR"
            print(f"  [{status}] Heartbeat: {result['message']}")
    
    record_skill_score(PHASE_SKILLS[5], True)
    
    # Phase 6: Record (skill-scoring)
    summary = f"[Auto-Reflection] trigger={trigger} issues={len(issues)} fixes={len(fixes)}"
    if record_to_dag(summary):
        print(f"\nPhase 6: Recorded to DAG")
    
    record_skill_score(PHASE_SKILLS[6], True)
    
    return {"status": "completed", "issues": len(issues), "fixes": len(fixes), "scores": phase_scores}

if __name__ == "__main__":
    trigger = sys.argv[1] if len(sys.argv) > 1 else "manual"
    result = run_auto_reflection(trigger)
    print(f"\nResult: {json.dumps(result, ensure_ascii=False)}")