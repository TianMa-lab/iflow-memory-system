#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
semantic_match.py - 语义匹配工具

功能：
1. match - 判断两个文本是否语义相关
2. batch - 批量匹配，返回排序结果
3. cluster - 文本聚类（可选）

调用示例：
    python semantic_match.py match "文本A" "文本B"
    python semantic_match.py batch "查询文本" --candidates "候选1|候选2|候选3"
    python semantic_match.py match "文本A" "文本B" --threshold 0.7

设计者：iFlow CLI
版本：v1.0
"""

import sys
import os
import json
import re
import argparse
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# LLM 配置（LM Studio 默认端口）
LLM_CONFIG = {
    "base_url": "http://localhost:1234/v1",
    "model": "qwen/qwen3.5-9b",  # 默认使用 qwen，中文能力强
    "timeout": 30
}


def call_llm(prompt: str, system_prompt: str = "", temperature: float = 0.1) -> str:
    """调用 LLM API"""
    if not REQUESTS_AVAILABLE:
        raise RuntimeError("requests 库未安装")
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    response = requests.post(
        f"{LLM_CONFIG['base_url']}/chat/completions",
        json={
            "model": LLM_CONFIG["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 500
        },
        timeout=LLM_CONFIG["timeout"]
    )
    
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"].strip()
    else:
        raise RuntimeError(f"LLM API 调用失败: {response.status_code}")


def extract_json(text: str) -> Dict:
    """从文本中提取 JSON"""
    # 尝试匹配 JSON 块
    json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    
    # 尝试匹配多行 JSON
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    
    return {}


def semantic_match(text_a: str, text_b: str, context: str = "") -> Dict:
    """
    判断两个文本是否语义相关
    
    Args:
        text_a: 文本A
        text_b: 文本B
        context: 可选的上下文说明
    
    Returns:
        {
            "related": bool,
            "confidence": float,
            "reason": str,
            "relationship": str  # 关系类型
        }
    """
    context_hint = f"\n上下文：{context}" if context else ""
    
    prompt = f"""请判断以下两个文本是否语义相关，直接输出结论。

文本A：{text_a}
文本B：{text_b}{context_hint}

请回答以下问题并按格式输出：
1. related: 是否相关（true或false）
2. confidence: 置信度（0到1之间的数字）
3. reason: 判断原因（一句话）
4. relationship: 关系类型（相同/相似/相关/无关之一）

必须严格按以下JSON格式输出，不要输出其他任何内容：
{{"related":true,"confidence":0.9,"reason":"两个文本都是关于监控程序运行","relationship":"相似"}}
"""

    try:
        response = call_llm(prompt, system_prompt="你是语义分析器，只输出JSON格式的结果，不要输出思考过程。")
        
        # 尝试从响应中提取 JSON（处理思维链模型的输出）
        result = extract_json(response)
        
        if not result:
            # 如果无法解析，尝试从文本中提取关键信息
            related = "相关" in response or "相似" in response or "相同" in response
            unrelated = "无关" in response or "不相关" in response
            
            # 提取置信度
            confidence_match = re.search(r'(?:confidence|置信度)[：:]\s*([\d.]+)', response)
            confidence = float(confidence_match.group(1)) if confidence_match else (0.8 if related and not unrelated else 0.3)
            
            return {
                "related": related and not unrelated,
                "confidence": confidence,
                "reason": "从文本分析推断" if not result else result.get("reason", ""),
                "relationship": "相似" if related and not unrelated else "无关"
            }
        
        # 确保 confidence 是浮点数
        if isinstance(result.get("confidence"), str):
            try:
                result["confidence"] = float(result["confidence"])
            except:
                result["confidence"] = 0.5
        
        return {
            "related": result.get("related", False),
            "confidence": result.get("confidence", 0),
            "reason": result.get("reason", ""),
            "relationship": result.get("relationship", "未知")
        }
    
    except Exception as e:
        return {
            "related": False,
            "confidence": 0,
            "reason": f"LLM 调用失败: {str(e)}",
            "relationship": "错误"
        }


def batch_match(query: str, candidates: List[str], top_k: int = 5) -> List[Dict]:
    """
    批量匹配，返回排序结果
    
    Args:
        query: 查询文本
        candidates: 候选文本列表
        top_k: 返回前 k 个结果
    
    Returns:
        排序后的匹配结果列表
    """
    if not candidates:
        return []
    
    results = []
    
    # 批量处理（可以优化为单次 LLM 调用）
    prompt = f"""判断查询文本与以下候选文本的语义相关性。

查询文本：{query}

候选文本：
{chr(10).join([f'{i+1}. {c}' for i, c in enumerate(candidates)])}

请为每个候选文本评分，输出 JSON 数组：
[{{"index": 1, "related": true/false, "confidence": 0.0-1.0, "reason": "原因"}}, ...]
"""

    try:
        response = call_llm(prompt, system_prompt="你是一个精确的语义分析器，只输出 JSON 数组，不要其他文字。")
        
        # 尝试解析 JSON 数组
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                for item in parsed:
                    idx = item.get("index", 0) - 1
                    if 0 <= idx < len(candidates):
                        results.append({
                            "candidate": candidates[idx],
                            "index": idx,
                            "related": item.get("related", False),
                            "confidence": item.get("confidence", 0),
                            "reason": item.get("reason", "")
                        })
            except json.JSONDecodeError:
                pass
        
        # 如果解析失败，逐个匹配
        if not results:
            for i, candidate in enumerate(candidates):
                result = semantic_match(query, candidate)
                results.append({
                    "candidate": candidate,
                    "index": i,
                    **result
                })
    
    except Exception as e:
        # 逐个匹配作为备选
        for i, candidate in enumerate(candidates):
            result = semantic_match(query, candidate)
            results.append({
                "candidate": candidate,
                "index": i,
                **result
            })
    
    # 按 confidence 排序
    results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    
    return results[:top_k]


def find_duplicates(texts: List[str], threshold: float = 0.8) -> List[Dict]:
    """
    在文本列表中查找语义重复
    
    Args:
        texts: 文本列表
        threshold: 重复判定阈值
    
    Returns:
        重复对列表
    """
    duplicates = []
    
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            result = semantic_match(texts[i], texts[j])
            if result["related"] and result["confidence"] >= threshold:
                duplicates.append({
                    "text_a": texts[i],
                    "text_b": texts[j],
                    "index_a": i,
                    "index_b": j,
                    "confidence": result["confidence"],
                    "reason": result["reason"]
                })
    
    return duplicates


# ============================================================
# CLI 命令
# ============================================================

def cmd_match(args):
    """match 命令：判断两个文本是否语义相关"""
    result = semantic_match(args.text_a, args.text_b, args.context or "")
    
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f" 语义匹配结果")
        print(f"{'='*50}")
        print(f"文本A: {args.text_a[:50]}...")
        print(f"文本B: {args.text_b[:50]}...")
        print(f"\n结果: {'相关' if result['related'] else '不相关'}")
        print(f"置信度: {result['confidence']:.0%}")
        print(f"关系: {result['relationship']}")
        print(f"原因: {result['reason']}")
        print(f"{'='*50}\n")
    
    return 0 if result["related"] or not args.fail_on_unrelated else 1


def cmd_batch(args):
    """batch 命令：批量匹配"""
    candidates = args.candidates.split("|")
    results = batch_match(args.query, candidates, args.top_k)
    
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f" 批量语义匹配结果")
        print(f"{'='*50}")
        print(f"查询: {args.query}")
        print(f"\n前 {len(results)} 个匹配结果：\n")
        
        for i, r in enumerate(results, 1):
            status = "✓" if r["related"] else "✗"
            print(f"{i}. [{status}] {r['confidence']:.0%} - {r['candidate'][:40]}...")
            print(f"   原因: {r['reason']}")
        
        print(f"\n{'='*50}\n")
    
    return 0


def cmd_duplicates(args):
    """duplicates 命令：查找重复"""
    texts = args.texts.split("|")
    duplicates = find_duplicates(texts, args.threshold)
    
    if args.json:
        print(json.dumps(duplicates, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f" 语义重复检测")
        print(f"{'='*50}")
        print(f"检测 {len(texts)} 个文本，阈值 {args.threshold:.0%}")
        
        if duplicates:
            print(f"\n发现 {len(duplicates)} 对重复：\n")
            for i, d in enumerate(duplicates, 1):
                print(f"{i}. [{d['confidence']:.0%}]")
                print(f"   A: {d['text_a'][:50]}...")
                print(f"   B: {d['text_b'][:50]}...")
                print()
        else:
            print("\n未发现语义重复")
        
        print(f"{'='*50}\n")
    
    return 0


def cmd_test(args):
    """test 命令：测试 LLM 连接"""
    print("测试 LLM 连接...")
    
    try:
        response = call_llm("请回复 OK", temperature=0)
        print(f"✓ LLM 连接正常")
        print(f"  响应: {response}")
        return 0
    except Exception as e:
        print(f"✗ LLM 连接失败: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(description="语义匹配工具")
    parser.add_argument("--model", default="qwen/qwen3.5-9b", help="指定 LLM 模型")
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    
    # match 命令
    match_parser = subparsers.add_parser("match", help="判断两个文本是否语义相关")
    match_parser.add_argument("text_a", help="文本A")
    match_parser.add_argument("text_b", help="文本B")
    match_parser.add_argument("--context", help="上下文说明")
    match_parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    match_parser.add_argument("--fail-on-unrelated", action="store_true", help="不相关时返回非零退出码")
    
    # batch 命令
    batch_parser = subparsers.add_parser("batch", help="批量匹配")
    batch_parser.add_argument("query", help="查询文本")
    batch_parser.add_argument("--candidates", required=True, help="候选文本（用|分隔）")
    batch_parser.add_argument("--top-k", type=int, default=5, help="返回前 k 个结果")
    batch_parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    
    # duplicates 命令
    dup_parser = subparsers.add_parser("duplicates", help="查找语义重复")
    dup_parser.add_argument("texts", help="文本列表（用|分隔）")
    dup_parser.add_argument("--threshold", type=float, default=0.8, help="重复判定阈值")
    dup_parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    
    # test 命令
    subparsers.add_parser("test", help="测试 LLM 连接")
    
    args = parser.parse_args()
    
    # 设置模型
    if hasattr(args, "model") and args.model:
        LLM_CONFIG["model"] = args.model
    
    if args.command == "match":
        return cmd_match(args)
    elif args.command == "batch":
        return cmd_batch(args)
    elif args.command == "duplicates":
        return cmd_duplicates(args)
    elif args.command == "test":
        return cmd_test(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
