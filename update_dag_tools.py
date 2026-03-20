#!/usr/bin/env python3
"""更新 dag_tools.py 添加压缩和上下文命令"""
from pathlib import Path

dag_tools_path = Path.home() / '.iflow' / 'tools' / 'dag_tools.py'
content = dag_tools_path.read_text(encoding='utf-8')

# 在文件末尾添加新命令
new_commands = '''

def cmd_compress():
    """压缩消息并构建层级摘要"""
    import subprocess
    
    # 压缩消息
    result = subprocess.run(
        ['python', str(Path.home() / '.iflow' / 'tools' / 'compaction_engine.py'), '--all'],
        capture_output=True, text=True
    )
    compaction = json.loads(result.stdout) if result.returncode == 0 else {'error': result.stderr}
    
    # 构建层级
    result = subprocess.run(
        ['python', str(Path.home() / '.iflow' / 'tools' / 'condensation_engine.py'), '--all'],
        capture_output=True, text=True
    )
    condensation = json.loads(result.stdout) if result.returncode == 0 else {'error': result.stderr}
    
    # 组装上下文
    result = subprocess.run(
        ['python', str(Path.home() / '.iflow' / 'tools' / 'context_assembler.py'), '--summaries'],
        capture_output=True, text=True
    )
    context = json.loads(result.stdout) if result.returncode == 0 else {'error': result.stderr}
    
    return {
        'compaction': compaction,
        'condensation': condensation,
        'context': context
    }

def cmd_context():
    """获取当前上下文"""
    import subprocess
    result = subprocess.run(
        ['python', str(Path.home() / '.iflow' / 'tools' / 'context_assembler.py'), '--format'],
        capture_output=True, text=True
    )
    return json.loads(result.stdout) if result.returncode == 0 else {'error': result.stderr}
'''

# 找到 main 函数的 if __name__ == '__main__' 部分之前插入
main_idx = content.find('if __name__')
if main_idx != -1:
    content = content[:main_idx] + new_commands + '\n' + content[main_idx:]

# 在 main 函数中添加新命令处理
old_main = '''    elif command == 'audit':
        result = cmd_audit()'''
new_main = '''    elif command == 'audit':
        result = cmd_audit()
    elif command == 'compress':
        result = cmd_compress()
    elif command == 'context':
        result = cmd_context()'''

content = content.replace(old_main, new_main)

dag_tools_path.write_text(content, encoding='utf-8')
print('dag_tools.py updated with compress and context commands')
