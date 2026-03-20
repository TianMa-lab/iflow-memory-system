#!/usr/bin/env python3
"""修复 dag_tools.py 添加 compress 和 context 命令"""
from pathlib import Path

dag_tools_path = Path.home() / '.iflow' / 'tools' / 'dag_tools.py'
content = dag_tools_path.read_text(encoding='utf-8')

# 找到 elif cmd == "maintain" 或最后一个 elif，在其后添加
maintain_idx = content.find('elif cmd == "maintain"')
if maintain_idx != -1:
    # 找到该 elif 块结束的位置（下一个 elif 或文件末尾）
    # 找到该行的末尾
    line_end = content.find('\n', maintain_idx)
    # 找到整个块的结束
    # 简单方法：找到下一个 'elif cmd' 或文件末尾
    next_elif = content.find('\n    elif cmd ==', line_end)
    if next_elif == -1:
        next_elif = content.find('\n\nif __name__', line_end)
    
    if next_elif != -1:
        insert_pos = next_elif
    else:
        insert_pos = line_end
    
    new_commands = '''
    elif cmd == "compress":
        result = cmd_compress()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif cmd == "context":
        result = cmd_context()
        if 'formatted' in result:
            print(result['formatted'])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
'''
    
    content = content[:insert_pos] + new_commands + content[insert_pos:]
    dag_tools_path.write_text(content, encoding='utf-8')
    print('dag_tools.py fixed with compress and context commands')
else:
    print('Could not find maintain command')
