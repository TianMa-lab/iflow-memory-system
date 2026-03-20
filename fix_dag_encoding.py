#!/usr/bin/env python3
"""修复 dag_tools.py 的编码问题"""
from pathlib import Path

dag_tools_path = Path.home() / '.iflow' / 'tools' / 'dag_tools.py'
content = dag_tools_path.read_text(encoding='utf-8')

# 修复 cmd_compress 函数
old_compress = '''def cmd_compress():
    """压缩消息并构建层级摘要"""
    import subprocess
    
    # 压缩消息
    result = subprocess.run(
        ['python', str(Path.home() / '.iflow' / 'tools' / 'compaction_engine.py'), '--all'],
        capture_output=True, text=True
    )
    compaction = json.loads(result.stdout) if result.returncode == 0 else {'error': result.stderr}'''

new_compress = '''def cmd_compress():
    """压缩消息并构建层级摘要"""
    import subprocess
    import sys
    
    # 压缩消息
    try:
        result = subprocess.run(
            [sys.executable, str(Path.home() / '.iflow' / 'tools' / 'compaction_engine.py'), '--all'],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        compaction = json.loads(result.stdout) if result.returncode == 0 and result.stdout else {'error': result.stderr or 'No output'}
    except Exception as e:
        compaction = {'error': str(e)}'''

content = content.replace(old_compress, new_compress)

# 修复 condensation 部分
old_cond = '''    # 构建层级
    result = subprocess.run(
        ['python', str(Path.home() / '.iflow' / 'tools' / 'condensation_engine.py'), '--all'],
        capture_output=True, text=True
    )
    condensation = json.loads(result.stdout) if result.returncode == 0 else {'error': result.stderr}'''

new_cond = '''    # 构建层级
    try:
        result = subprocess.run(
            [sys.executable, str(Path.home() / '.iflow' / 'tools' / 'condensation_engine.py'), '--all'],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        condensation = json.loads(result.stdout) if result.returncode == 0 and result.stdout else {'error': result.stderr or 'No output'}
    except Exception as e:
        condensation = {'error': str(e)}'''

content = content.replace(old_cond, new_cond)

# 修复 context 部分
old_ctx = '''    # 组装上下文
    result = subprocess.run(
        ['python', str(Path.home() / '.iflow' / 'tools' / 'context_assembler.py'), '--summaries'],
        capture_output=True, text=True
    )
    context = json.loads(result.stdout) if result.returncode == 0 else {'error': result.stderr}'''

new_ctx = '''    # 组装上下文
    try:
        result = subprocess.run(
            [sys.executable, str(Path.home() / '.iflow' / 'tools' / 'context_assembler.py'), '--summaries'],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        context = json.loads(result.stdout) if result.returncode == 0 and result.stdout else {'error': result.stderr or 'No output'}
    except Exception as e:
        context = {'error': str(e)}'''

content = content.replace(old_ctx, new_ctx)

# 修复 cmd_context 函数
old_context = '''def cmd_context():
    """获取当前上下文"""
    import subprocess
    result = subprocess.run(
        ['python', str(Path.home() / '.iflow' / 'tools' / 'context_assembler.py'), '--format'],
        capture_output=True, text=True
    )
    return json.loads(result.stdout) if result.returncode == 0 else {'error': result.stderr}'''

new_context = '''def cmd_context():
    """获取当前上下文"""
    import subprocess
    import sys
    try:
        result = subprocess.run(
            [sys.executable, str(Path.home() / '.iflow' / 'tools' / 'context_assembler.py'), '--format'],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        return json.loads(result.stdout) if result.returncode == 0 and result.stdout else {'error': result.stderr or 'No output'}
    except Exception as e:
        return {'error': str(e)}'''

content = content.replace(old_context, new_context)

dag_tools_path.write_text(content, encoding='utf-8')
print('dag_tools.py encoding fixed')
