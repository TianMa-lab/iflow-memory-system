#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lesson_manager.py - 经验教训管理工具

功能：
1. add - 添加新教训（包含完整故事）
2. check - 检查当前方案是否匹配历史教训
3. list - 列出所有教训
4. get - 获取特定教训详情

调用示例：
    python lesson_manager.py add --lesson "..." --story "..." --triggers "..."
    python lesson_manager.py check "技术障碍 监控方案"
    python lesson_manager.py list
    python lesson_manager.py get lesson-001

设计者：iFlow CLI
版本：v1.1 (添加 LLM 语义判断)
"""

import sys
import os
import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
import argparse

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

# 路径配置
LESSONS_DIR = os.path.dirname(os.path.abspath(__file__))
LESSONS_FILE = os.path.join(LESSONS_DIR, "lessons.json")
EMBEDDINGS_FILE = os.path.join(LESSONS_DIR, "lesson_embeddings.json")
CHROMA_DIR = os.path.join(LESSONS_DIR, "chroma_db")

# LLM 配置（LM Studio 默认端口）
LLM_CONFIG = {
    "base_url": "http://localhost:1234/v1",
    "model": "local-model",
    "embedding_model": "text-embedding-bge-m3",
    "timeout": 30
}


@dataclass
class Lesson:
    """教训数据结构"""
    id: str
    lesson: str                    # 教训摘要（一句话）
    story: Dict[str, Any]          # 完整故事
    triggers: List[str]            # 触发关键词
    related_topics: List[str]      # 相关主题
    created: str
    times_matched: int = 0         # 被匹配次数
    last_matched: Optional[str] = None


@dataclass
class Story:
    """故事结构"""
    context: str           # 背景：当时想做什么
    approaches: List[str]  # 尝试过的方案
    breakthrough: str      # 突破点：什么改变了思路
    result: str            # 结果：最终方案


def load_lessons() -> List[Dict]:
    """加载所有教训"""
    if not os.path.exists(LESSONS_FILE):
        return []
    with open(LESSONS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_lessons(lessons: List[Dict]):
    """保存教训"""
    with open(LESSONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(lessons, f, ensure_ascii=False, indent=2)


def generate_id() -> str:
    """生成唯一ID"""
    date_str = datetime.now().strftime("%Y%m%d")
    lessons = load_lessons()
    count = len([l for l in lessons if l['id'].startswith(f"lesson-{date_str}")]) + 1
    return f"lesson-{date_str}-{count:03d}"


# === 向量嵌入功能 ===

def get_embedding(text: str) -> Optional[List[float]]:
    """获取文本的向量嵌入"""
    if not REQUESTS_AVAILABLE:
        return None
    
    try:
        response = requests.post(
            f"{LLM_CONFIG['base_url']}/embeddings",
            json={
                "model": LLM_CONFIG["embedding_model"],
                "input": text
            },
            timeout=30
        )
        if response.status_code == 200:
            return response.json()["data"][0]["embedding"]
    except Exception as e:
        print(f"获取嵌入失败: {e}")
    return None


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """计算余弦相似度"""
    if not NUMPY_AVAILABLE:
        # 纯 Python 实现
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)
    else:
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))


def load_embeddings() -> Dict[str, List[float]]:
    """加载所有嵌入"""
    if not os.path.exists(EMBEDDINGS_FILE):
        return {}
    with open(EMBEDDINGS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_embeddings(embeddings: Dict[str, List[float]]):
    """保存嵌入"""
    with open(EMBEDDINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(embeddings, f)


def embed_all_lessons():
    """为所有教训生成嵌入"""
    lessons = load_lessons()
    embeddings = load_embeddings()
    
    new_count = 0
    for lesson in lessons:
        lesson_id = lesson["id"]
        if lesson_id in embeddings:
            continue
        
        # 组合文本用于嵌入
        text = f"{lesson['lesson']} {lesson['story'].get('context', '')}"
        embedding = get_embedding(text)
        
        if embedding:
            embeddings[lesson_id] = embedding
            new_count += 1
            print(f"✓ 已嵌入: {lesson_id}")
            
            # 同时存入 ChromaDB
            if CHROMA_AVAILABLE:
                metadata = {
                    "lesson": lesson["lesson"],
                    "triggers": ",".join(lesson.get("triggers", [])),
                    "created": lesson.get("created", "")
                }
                chroma_add_lesson(lesson_id, text, embedding, metadata)
    
    if new_count > 0:
        save_embeddings(embeddings)
        print(f"\n✓ 新增 {new_count} 个嵌入")
        if CHROMA_AVAILABLE:
            print(f"✓ 已同步到 ChromaDB")
    else:
        print("所有教训已有嵌入")
    
    return len(embeddings)


def vector_search(query: str, top_k: int = 3) -> List[Dict]:
    """向量检索最相关的教训"""
    query_embedding = get_embedding(query)
    if not query_embedding:
        return []
    
    embeddings = load_embeddings()
    lessons = load_lessons()
    
    # 计算相似度
    scores = []
    for lesson_id, emb in embeddings.items():
        sim = cosine_similarity(query_embedding, emb)
        scores.append((lesson_id, sim))
    
    # 排序取 top_k
    scores.sort(key=lambda x: x[1], reverse=True)
    
    results = []
    for lesson_id, score in scores[:top_k]:
        lesson = next((l for l in lessons if l["id"] == lesson_id), None)
        if lesson:
            results.append({
                "lesson": lesson,
                "similarity": score
            })
    
    return results


# === ChromaDB 向量数据库 ===

def get_chroma_client():
    """获取 ChromaDB 客户端"""
    if not CHROMA_AVAILABLE:
        return None
    return chromadb.PersistentClient(path=CHROMA_DIR)


def get_lessons_collection():
    """获取教训集合"""
    client = get_chroma_client()
    if not client:
        return None
    return client.get_or_create_collection(
        name="lessons",
        metadata={"description": "经验教训向量库", "hnsw:space": "cosine"}
    )


def chroma_add_lesson(lesson_id: str, text: str, embedding: List[float], metadata: Dict = None):
    """添加教训到 ChromaDB"""
    collection = get_lessons_collection()
    if not collection:
        return False
    
    try:
        collection.upsert(
            ids=[lesson_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata or {}]
        )
        return True
    except Exception as e:
        print(f"ChromaDB 添加失败: {e}")
        return False


def chroma_search(query_embedding: List[float], top_k: int = 3) -> List[Dict]:
    """ChromaDB 向量检索"""
    collection = get_lessons_collection()
    if not collection:
        return []
    
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )
        
        matches = []
        for i, lesson_id in enumerate(results['ids'][0]):
            # ChromaDB 返回的是距离，转换为相似度
            distance = results['distances'][0][i]
            similarity = 1 - distance  # 余弦距离转相似度
            
            matches.append({
                "lesson_id": lesson_id,
                "similarity": similarity,
                "document": results['documents'][0][i] if results['documents'] else "",
                "metadata": results['metadatas'][0][i] if results['metadatas'] else {}
            })
        
        return matches
    except Exception as e:
        print(f"ChromaDB 检索失败: {e}")
        return []


def migrate_to_chroma():
    """迁移 JSON 嵌入到 ChromaDB"""
    if not CHROMA_AVAILABLE:
        print("ChromaDB 未安装")
        return 0
    
    lessons = load_lessons()
    embeddings = load_embeddings()
    
    if not embeddings:
        print("无嵌入数据可迁移")
        return 0
    
    collection = get_lessons_collection()
    if not collection:
        print("无法创建 ChromaDB 集合")
        return 0
    
    migrated = 0
    for lesson in lessons:
        lesson_id = lesson["id"]
        if lesson_id not in embeddings:
            continue
        
        text = f"{lesson['lesson']} {lesson['story'].get('context', '')}"
        metadata = {
            "lesson": lesson["lesson"],
            "triggers": ",".join(lesson.get("triggers", [])),
            "created": lesson.get("created", "")
        }
        
        if chroma_add_lesson(lesson_id, text, embeddings[lesson_id], metadata):
            migrated += 1
            print(f"✓ 迁移: {lesson_id}")
    
    print(f"\n✓ 迁移完成: {migrated} 条教训")
    return migrated


def vector_search_chroma(query: str, top_k: int = 3) -> List[Dict]:
    """使用 ChromaDB 进行向量检索"""
    query_embedding = get_embedding(query)
    if not query_embedding:
        return []
    
    chroma_results = chroma_search(query_embedding, top_k)
    if not chroma_results:
        # 回退到 JSON 检索
        return vector_search(query, top_k)
    
    lessons = load_lessons()
    results = []
    for match in chroma_results:
        lesson = next((l for l in lessons if l["id"] == match["lesson_id"]), None)
        if lesson:
            results.append({
                "lesson": lesson,
                "similarity": match["similarity"]
            })
    
    return results


def cmd_add(args):
    """添加新教训"""
    lesson_id = generate_id()
    
    # 解析 story
    story = {
        "context": args.context or "",
        "approaches": args.approaches.split("|") if args.approaches else [],
        "breakthrough": args.breakthrough or "",
        "result": args.result or ""
    }
    
    # 解析 triggers
    triggers = args.triggers.split(",") if args.triggers else []
    topics = args.topics.split(",") if args.topics else []
    
    lesson = {
        "id": lesson_id,
        "lesson": args.lesson,
        "story": story,
        "triggers": triggers,
        "related_topics": topics,
        "created": datetime.now().isoformat(),
        "times_matched": 0,
        "last_matched": None
    }
    
    lessons = load_lessons()
    lessons.append(lesson)
    save_lessons(lessons)
    
    print(f"✓ 教训已添加: {lesson_id}")
    print(f"  摘要: {args.lesson}")
    return lesson_id


# === 语义触发器 ===

# 同义词词典
SYNONYMS = {
    "监控": ["盯着", "监听", "跟踪", "观测", "监视", "监控", "观察", "看守"],
    "拦截": ["捕获", "截获", "阻断", "拦截", "截取", "钩子", "hook"],
    "绕过": ["避开", "突破", "绕过", "绕开", "跳过", "bypass"],
    "外部程序": ["外部进程", "守护进程", "守护程序", "daemon", "外部工具"],
    "技术障碍": ["碰壁", "失败", "不行", "不支持", "无法", "限制"],
    "复杂方案": ["复杂的", "繁琐", "多步骤", "大工程", "过度设计"],
    "主动": ["主动", "自愿", "自发", "自己", "自动"],
    "被动": ["被动", "强制", "被监控", "被拦截"],
}

# 规则模式（高优先级，直接匹配语义模式）
RULE_PATTERNS = [
    {
        "pattern": r"(想|要|准备|打算).*(用|通过).*(外部|守护|daemon).*监控",
        "lesson_hint": "技术障碍,监控,外部程序",
        "description": "想用外部程序监控"
    },
    {
        "pattern": r"(怎么|如何).*(拦截|捕获|截获).*(输出|请求)",
        "lesson_hint": "拦截,监控",
        "description": "想拦截输出或请求"
    },
    {
        "pattern": r"(绕过|避开|突破).*(限制|障碍|困难)",
        "lesson_hint": "绕过,技术障碍",
        "description": "想绕过限制"
    },
    {
        "pattern": r"(太|好).*(复杂|繁琐|麻烦)",
        "lesson_hint": "复杂方案",
        "description": "方案太复杂"
    },
]


def expand_synonyms(text: str) -> List[str]:
    """从文本中提取并扩展同义词"""
    expanded = []
    for key, synonyms in SYNONYMS.items():
        # 检查文本中是否包含关键词或其同义词
        all_words = [key] + synonyms
        for word in all_words:
            if word in text:
                expanded.extend(all_words)
                break
    return list(set(expanded))


def match_rule_patterns(text: str) -> List[Dict]:
    """匹配规则模式"""
    matches = []
    for rule in RULE_PATTERNS:
        if re.search(rule["pattern"], text, re.IGNORECASE):
            matches.append(rule)
    return matches


def llm_semantic_check(input_text: str, lesson: Dict) -> Dict:
    """
    Level 3: 使用 LLM 进行语义判断
    
    返回:
        {
            "related": True/False,
            "confidence": 0.0-1.0,
            "reason": "判断原因"
        }
    """
    if not REQUESTS_AVAILABLE:
        return {"related": False, "confidence": 0, "reason": "requests 库未安装"}
    
    prompt = f"""你是一个经验教训审核器。判断当前用户方案是否与历史教训相关。

【历史教训】
摘要: {lesson['lesson']}
背景: {lesson['story'].get('context', 'N/A')}
尝试过的方案: {', '.join(lesson['story'].get('approaches', []))}
突破点: {lesson['story'].get('breakthrough', 'N/A')}
结果: {lesson['story'].get('result', 'N/A')}

【当前方案】
{input_text}

【判断标准】
1. 当前方案是否与教训中"尝试过的方案"相似？
2. 当前方案是否可能遇到同样的困境？
3. 当前方案是否需要类似的"突破点"来改变思路？

【输出格式】（严格 JSON）
{{"related": true/false, "confidence": 0.0-1.0, "reason": "一句话说明为什么相关或不相关"}}
"""

    try:
        response = requests.post(
            f"{LLM_CONFIG['base_url']}/chat/completions",
            json={
                "model": LLM_CONFIG["model"],
                "messages": [
                    {"role": "system", "content": "你是一个精确的判断器，只输出 JSON，不要其他文字。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 200
            },
            timeout=LLM_CONFIG["timeout"]
        )
        
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"].strip()
            # 提取 JSON
            json_match = re.search(r'\{[^}]+\}', content)
            if json_match:
                result = json.loads(json_match.group())
                return result
    except Exception as e:
        pass
    
    return {"related": False, "confidence": 0, "reason": "LLM 调用失败"}


def cmd_check(args):
    """检查当前方案是否匹配历史教训"""
    input_text = args.keywords
    lessons = load_lessons()
    use_llm = getattr(args, 'llm', False)  # 是否使用 LLM
    use_vector = getattr(args, 'vector', False)  # 是否使用向量检索
    
    if not lessons:
        print("OK: 暂无历史教训")
        return

    # Level 1: 规则模式匹配
    rule_matches = match_rule_patterns(input_text)
    
    # Level 2: 同义词扩展（直接从文本中提取）
    expanded_keywords = expand_synonyms(input_text)
    
    matches = []
    for lesson in lessons:
        trigger_words = lesson.get('triggers', [])
        lesson_text = lesson.get('lesson', '').lower()
        
        match_score = 0
        matched_reasons = []
        
        # 规则模式匹配（高分）
        for rule in rule_matches:
            hint_keywords = rule["lesson_hint"].split(",")
            for hint in hint_keywords:
                if hint in trigger_words:
                    match_score += 5  # 规则匹配高分
                    matched_reasons.append(f"规则匹配: {rule['description']}")
        
        # 同义词扩展匹配
        for kw in expanded_keywords:
            kw_lower = kw.lower()
            for trigger in trigger_words:
                if kw_lower in trigger.lower() or trigger.lower() in kw_lower:
                    match_score += 1
                    if f"关键词: {kw}" not in matched_reasons:
                        matched_reasons.append(f"关键词: {kw}")
                    break
            # 匹配教训文本
            if kw_lower in lesson_text:
                match_score += 0.5
                if f"文本匹配: {kw}" not in matched_reasons:
                    matched_reasons.append(f"文本匹配: {kw}")
        
        if match_score > 0:
            matches.append({
                "lesson": lesson,
                "score": match_score,
                "reasons": matched_reasons
            })
    
    # Level 3a: 向量检索（当 Level 1/2 无匹配且启用 --vector 时）
    if not matches and use_vector:
        print("\n[Level 3a] 启用向量检索...")
        vector_results = vector_search(input_text, top_k=3)
        for vr in vector_results:
            if vr["similarity"] >= 0.6:  # 相似度阈值
                matches.append({
                    "lesson": vr["lesson"],
                    "score": vr["similarity"] * 10,  # 归一化分数
                    "reasons": [f"向量相似度: {vr['similarity']:.0%}"]
                })
    
    # Level 3b: LLM 语义判断（当 Level 1/2 无匹配且启用 --llm 时）
    if not matches and use_llm and REQUESTS_AVAILABLE:
        print("\n[Level 3b] 启用 LLM 语义判断...")
        for lesson in lessons:
            llm_result = llm_semantic_check(input_text, lesson)
            if llm_result.get("related") and llm_result.get("confidence", 0) >= 0.5:
                matches.append({
                    "lesson": lesson,
                    "score": llm_result["confidence"] * 5,  # 转换为分数
                    "reasons": [f"LLM判断({llm_result['confidence']:.0%}): {llm_result['reason']}"]
                })
    
    if not matches:
        print("OK: 无相关历史教训")
        return
    
    # 按分数排序
    matches.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\n{'='*60}")
    print(f" ⚠️  发现 {len(matches)} 条相关教训")
    print(f"{'='*60}")
    
    for i, match in enumerate(matches[:3], 1):  # 最多显示3条
        lesson = match['lesson']
        story = lesson.get('story', {})
        
        print(f"\n【教训 {i}】{lesson['id']}")
        print(f"摘要: {lesson['lesson']}")
        print(f"匹配原因: {', '.join(match['reasons'])}")
        print(f"\n故事:")
        print(f"  背景: {story.get('context', 'N/A')}")
        
        approaches = story.get('approaches', [])
        if approaches:
            print(f"  尝试过的方案:")
            for ap in approaches:
                print(f"    - {ap}")
        
        print(f"  突破点: {story.get('breakthrough', 'N/A')}")
        print(f"  结果: {story.get('result', 'N/A')}")
        print(f"\n  创建时间: {lesson['created'][:10]}")
        print(f"  被匹配次数: {lesson.get('times_matched', 0)}")
        
        # 更新匹配统计
        for l in lessons:
            if l['id'] == lesson['id']:
                l['times_matched'] = l.get('times_matched', 0) + 1
                l['last_matched'] = datetime.now().isoformat()
                break
    
    save_lessons(lessons)
    
    print(f"\n{'='*60}")
    print(" 请仔细阅读以上教训，确认当前方案不会重蹈覆辙")
    print(f"{'='*60}")


def cmd_list(args):
    """列出所有教训"""
    lessons = load_lessons()
    
    if not lessons:
        print("暂无历史教训")
        return
    
    print(f"\n{'='*60}")
    print(f" 经验教训库 ({len(lessons)} 条)")
    print(f"{'='*60}")
    
    for lesson in sorted(lessons, key=lambda x: x['created'], reverse=True):
        times = lesson.get('times_matched', 0)
        print(f"\n[{lesson['id']}] {lesson['lesson']}")
        print(f"  触发词: {', '.join(lesson.get('triggers', []))}")
        print(f"  匹配次数: {times}")


def cmd_get(args):
    """获取特定教训详情"""
    lessons = load_lessons()
    
    for lesson in lessons:
        if lesson['id'] == args.lesson_id:
            story = lesson.get('story', {})
            print(f"\n{'='*60}")
            print(f" 教训详情: {lesson['id']}")
            print(f"{'='*60}")
            print(f"\n摘要: {lesson['lesson']}")
            print(f"\n【完整故事】")
            print(f"背景: {story.get('context', 'N/A')}")
            
            approaches = story.get('approaches', [])
            if approaches:
                print(f"\n尝试过的方案:")
                for i, ap in enumerate(approaches, 1):
                    print(f"  {i}. {ap}")
            
            print(f"\n突破点: {story.get('breakthrough', 'N/A')}")
            print(f"\n结果: {story.get('result', 'N/A')}")
            print(f"\n【元信息】")
            print(f"触发词: {', '.join(lesson.get('triggers', []))}")
            print(f"相关主题: {', '.join(lesson.get('related_topics', []))}")
            print(f"创建时间: {lesson['created']}")
            print(f"匹配次数: {lesson.get('times_matched', 0)}")
            print(f"上次匹配: {lesson.get('last_matched', 'N/A')}")
            return
    
    print(f"未找到教训: {args.lesson_id}")


def cmd_export(args):
    """导出教训到 AGENTS.md 格式"""
    lessons = load_lessons()
    
    if not lessons:
        print("暂无教训可导出")
        return
    
    print("\n## 📚 经验教训库\n")
    for lesson in sorted(lessons, key=lambda x: x['created'], reverse=True)[:10]:
        print(f"- **{lesson['lesson']}**")
        print(f"  - 触发: {', '.join(lesson.get('triggers', []))}")
        print(f"  - ID: {lesson['id']}")
        print()


def cmd_embed(args):
    """为所有教训生成向量嵌入"""
    print("正在为教训生成向量嵌入...")
    print(f"使用模型: {LLM_CONFIG['embedding_model']}")
    print()
    
    total = embed_all_lessons()
    print(f"\n总计 {total} 个嵌入已保存")


def cmd_search(args):
    """向量检索相关教训"""
    print(f"\n{'='*60}")
    print(f" 向量检索: {args.query}")
    print(f"{'='*60}")
    
    # 优先使用 ChromaDB，回退到 JSON
    if CHROMA_AVAILABLE:
        results = vector_search_chroma(args.query, top_k=args.top_k)
    else:
        results = vector_search(args.query, top_k=args.top_k)
    
    if not results:
        print("无匹配结果（可能没有嵌入）")
        print("提示: 先运行 'python lesson_manager.py embed' 生成嵌入")
        return
    
    for i, result in enumerate(results, 1):
        lesson = result["lesson"]
        story = lesson.get("story", {})
        
        print(f"\n【{i}】{lesson['id']}")
        print(f"相似度: {result['similarity']:.2%}")
        print(f"摘要: {lesson['lesson']}")
        print(f"背景: {story.get('context', 'N/A')}")
    
    print(f"\n{'='*60}")


def cmd_migrate(args):
    """迁移嵌入到 ChromaDB"""
    if not CHROMA_AVAILABLE:
        print("✗ ChromaDB 未安装")
        print("安装: pip install chromadb")
        return
    
    print("迁移嵌入到 ChromaDB...")
    print(f"存储路径: {CHROMA_DIR}")
    print()
    
    migrate_to_chroma()


def main():
    parser = argparse.ArgumentParser(description="经验教训管理工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    
    # add 命令
    add_parser = subparsers.add_parser("add", help="添加新教训")
    add_parser.add_argument("--lesson", required=True, help="教训摘要")
    add_parser.add_argument("--context", help="背景故事")
    add_parser.add_argument("--approaches", help="尝试过的方案（用|分隔）")
    add_parser.add_argument("--breakthrough", help="突破点")
    add_parser.add_argument("--result", help="最终结果")
    add_parser.add_argument("--triggers", help="触发关键词（用,分隔）")
    add_parser.add_argument("--topics", help="相关主题（用,分隔）")
    
    # check 命令
    check_parser = subparsers.add_parser("check", help="检查是否匹配历史教训")
    check_parser.add_argument("keywords", help="当前方案描述")
    check_parser.add_argument("--llm", action="store_true", help="启用 LLM 语义判断（Level 3）")
    check_parser.add_argument("--vector", action="store_true", help="启用向量检索（Level 3a）")
    
    # list 命令
    subparsers.add_parser("list", help="列出所有教训")
    
    # get 命令
    get_parser = subparsers.add_parser("get", help="获取特定教训详情")
    get_parser.add_argument("lesson_id", help="教训ID")
    
    # export 命令
    subparsers.add_parser("export", help="导出到 AGENTS.md 格式")
    
    # embed 命令
    subparsers.add_parser("embed", help="为所有教训生成向量嵌入")
    
    # search 命令
    search_parser = subparsers.add_parser("search", help="向量检索相关教训")
    search_parser.add_argument("query", help="查询文本")
    search_parser.add_argument("--top-k", type=int, default=3, help="返回数量")
    
    # migrate 命令
    subparsers.add_parser("migrate", help="迁移嵌入到 ChromaDB")
    
    args = parser.parse_args()
    
    if args.command == "add":
        cmd_add(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "get":
        cmd_get(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "embed":
        cmd_embed(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "migrate":
        cmd_migrate(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
