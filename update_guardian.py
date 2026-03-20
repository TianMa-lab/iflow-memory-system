#!/usr/bin/env python3
"""Update Guardian to v3.9 with auto-reflection"""

from pathlib import Path

guardian_path = Path.home() / ".iflow" / "tools" / "iflow_guardian.ps1"
content = guardian_path.read_text(encoding='utf-8')

# Update version
content = content.replace('v3.8', 'v3.9')

# Find the health check section and modify it
idx = content.find('# 汇报结果')
if idx == -1:
    print("ERROR: Could not find health check section")
    exit(1)

# Find the return statement after this section
return_idx = content.find('return @{ issues = $issues; fixed = $fixed }', idx)
if return_idx == -1:
    print("ERROR: Could not find return statement")
    exit(1)

# Find the end of the else block (where we want to insert)
# Look for the closing brace before the return
brace_start = content.rfind('}', idx, return_idx)
closing_brace = content.rfind('}', idx, return_idx)

# Insert auto-reflection before the closing brace of the else block
# Actually, we want to insert it after the DAG record line

dag_line = content.find('# 记录健康检查结果到 DAG', idx)
if dag_line == -1:
    print("ERROR: Could not find DAG line")
    exit(1)

# Find the end of the python command line
python_end = content.find('\n', dag_line)
next_line_start = python_end + 1

# Insert the auto-reflection code after the python command
insertion = '''
        # 触发自动深刻自省
        Log("Triggering auto-reflection due to issues...")
        $reflectionResult = python "$env:USERPROFILE\.iflow\tools\auto_reflection.py" guardian 2>&1
        Log("Auto-reflection: $reflectionResult")'''

# Check if already inserted
if 'auto_reflection' in content:
    print("Auto-reflection already present")
else:
    content = content[:next_line_start] + insertion + content[next_line_start:]
    print("Inserted auto-reflection code")

guardian_path.write_text(content, encoding='utf-8')
print("Guardian updated to v3.9")