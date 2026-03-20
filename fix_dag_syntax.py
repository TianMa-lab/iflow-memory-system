#!/usr/bin/env python3
"""修复 dag_tools.py 的语法错误"""
from pathlib import Path

dag_tools_path = Path.home() / '.iflow' / 'tools' / 'dag_tools.py'
content = dag_tools_path.read_text(encoding='utf-8')

# 修复空的 maintain 块
old_broken = '''    elif cmd == "maintain":
    elif cmd == "compress":'''

new_fixed = '''    elif cmd == "maintain":
        result = dag_maintain(dry_run="--auto" not in sys.argv)
        mode = "执行" if "--auto" in sys.argv else "预览"
        print(f"维护 {mode}: {result}")
    
    elif cmd == "compress":'''

content = content.replace(old_broken, new_fixed)

dag_tools_path.write_text(content, encoding='utf-8')
print('dag_tools.py syntax fixed')
