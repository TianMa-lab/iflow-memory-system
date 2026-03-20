#!/usr/bin/env python3
"""Fix Guardian - proper insertion with correct escaping"""

from pathlib import Path

guardian_path = Path.home() / ".iflow" / "tools" / "iflow_guardian.ps1"
content = guardian_path.read_text(encoding='utf-8')

# First, remove any corrupted auto-reflection code that was inserted wrong
# Look for the pattern and remove it
import re

# Remove any existing broken auto-reflection insertion
bad_pattern = r'\n        # 触发自动深刻自省.*?\$reflectionResult.*?Auto-reflection:.*?\)'
content = re.sub(bad_pattern, '', content, flags=re.DOTALL)

# Now find the correct insertion point
# We want to insert AFTER the Out-Null at the end of the DAG record line
idx = content.find('# 记录健康检查结果到 DAG')
if idx == -1:
    print("ERROR: Could not find DAG line")
    exit(1)

# Find the line that ends with Out-Null
out_null_idx = content.find('| Out-Null', idx)
if out_null_idx == -1:
    print("ERROR: Could not find Out-Null")
    exit(1)

# Find the newline after Out-Null
newline_idx = content.find('\n', out_null_idx)

# Insert the auto-reflection code
# Using raw string to avoid escape issues
insertion = r'''
        # 触发自动深刻自省
        Log("Triggering auto-reflection due to issues...")
        $reflectionResult = python "$env:USERPROFILE\.iflow\tools\auto_reflection.py" guardian 2>&1
        Log("Auto-reflection: $reflectionResult")
'''

# Check if already correctly inserted
if r'auto_reflection.py' in content or 'auto_reflection.py' in content:
    print("Auto-reflection already present (correctly)")
else:
    content = content[:newline_idx] + insertion + content[newline_idx:]
    print("Inserted auto-reflection code")

guardian_path.write_text(content, encoding='utf-8')
print("Guardian fixed")
