#!/usr/bin/env python3
"""
更新 Guardian 添加 DAG 压缩功能
"""
from pathlib import Path

guardian_path = Path.home() / '.iflow' / 'tools' / 'iflow_guardian.ps1'
content = guardian_path.read_text(encoding='utf-8')

# 更新版本号
content = content.replace('v3.9', 'v4.0')

# 在 Scan-SessionHistory 函数之前插入新函数
new_function = '''
function Invoke-DAGCompaction {
    Log("Running DAG compaction...")
    
    # 1. 压缩消息为 leaf summaries
    $compactionResult = python "$env:USERPROFILE\.iflow\tools\compaction_engine.py" --all 2>&1 | ConvertFrom-Json
    Log("Compaction: $($compactionResult.total_compacted) messages compacted")
    
    # 2. 构建层级摘要
    $condensationResult = python "$env:USERPROFILE\.iflow\tools\condensation_engine.py" --all 2>&1 | ConvertFrom-Json
    Log("Condensation: $($condensationResult.total_levels_processed) levels processed")
    
    # 3. 记录到 DAG
    $summary = "【DAG压缩】消息压缩: $($compactionResult.total_compacted), 层级构建: $($condensationResult.total_levels_processed)"
    python "$env:USERPROFILE\.iflow\tools\dag_tools.py" add --content="$summary" --topic="DAG维护" 2>&1 | Out-Null
    
    return @{ compaction = $compactionResult; condensation = $condensationResult }
}

'''

# 在 Scan-SessionHistory 函数之前插入
insert_point = content.find('function Scan-SessionHistory')
if insert_point != -1:
    content = content[:insert_point] + new_function + content[insert_point:]

# 在主循环中添加 DAG 压缩调用 (每 6 小时执行一次)
# 找到主循环中的健康检查部分，在其后添加 DAG 压缩
dag_compaction_code = '''
    # === DAG 压缩检查 (每 6 小时) ===
    $lastDagCompaction = if (Test-Path "$env:USERPROFILE\.iflow\.last_dag_compaction") { 
        Get-Content "$env:USERPROFILE\.iflow\.last_dag_compaction" 
    } else { 
        "2020-01-01 00:00:00" 
    }
    $hoursSinceCompaction = ((Get-Date) - [DateTime]::Parse($lastDagCompaction)).TotalHours
    if ($hoursSinceCompaction -ge 6) {
        Log("Triggering DAG compaction (last: $([int]$hoursSinceCompaction)h ago)")
        $dagResult = Invoke-DAGCompaction
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Out-File "$env:USERPROFILE\.iflow\.last_dag_compaction"
    }

'''

# 在健康检查后插入
health_check_marker = '$lastHealthCheckTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"'
if health_check_marker in content:
    insert_idx = content.find(health_check_marker) + len(health_check_marker)
    # 找到下一行的结束位置
    next_newline = content.find('\n', insert_idx)
    insert_idx = content.find('\n', next_newline + 1)  # 跳过两行
    content = content[:insert_idx] + dag_compaction_code + content[insert_idx:]

# 保存
guardian_path.write_text(content, encoding='utf-8')
print('Guardian updated to v4.0 with DAG compaction')
