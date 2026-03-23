#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
request_auditor.py - 请求审核器

功能：在 iFlow CLI 请求用户确认前，审核请求内容是否合规。
调用方式：
    python request_auditor.py "清理 MEMORY.md 吧？"
    python request_auditor.py "清理 MEMORY.md 吧？" --context "之前分析过根因"

返回：
    OK - 审核通过
    VIOLATION:规则ID:反馈内容 - 审核失败

设计者：iFlow CLI
版本：v1.0
"""

import sys
import re
import json
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class Rule:
    """审核规则定义"""
    id: str
    name: str
    description: str
    trigger_patterns: List[str]      # 触发模式（正则）
    required_patterns: List[str]     # 必须包含的模式（任一匹配即通过）
    excluded_patterns: List[str]     # 排除模式（匹配则跳过此规则）
    feedback: str
    suggestion: str


# === 审核规则定义 ===
RULES: List[Rule] = [
    Rule(
        id="skip_root_cause",
        name="跳过根因分析",
        description="清理/删除类请求未先说明原因",
        trigger_patterns=[
            r"清理", r"删除", r"移除", r"处理.*垃圾", r"清理掉",
            r"删掉", r"去除", r"清除"
        ],
        required_patterns=[
            r"因为", r"原因是", r"根因", r"为什么", r"导致",
            r"分析发现", r"发现.*原因", r"由于", r"结果发现",
            r"因[为是].*，", r"发现.*因"  # 添加：因XXX，/ 发现...因...
        ],
        excluded_patterns=[
            r"因为.*所以", r"原因是.*，", r"分析后", r"发现.*后",
            r"根因.*：", r"根因分析"
        ],
        feedback="检测到清理/删除类请求，但未先说明原因。规则：先分析根因，再采取行动。",
        suggestion="建议格式：发现[问题]是因为[根因]，所以[操作]？"
    ),
    Rule(
        id="no_plan",
        name="直接执行无计划",
        description="执行类请求未先展示计划或步骤",
        trigger_patterns=[
            r"开始执行", r"执行吧", r"实施吧", r"开始做",
            r"开干", r"动手吧", r"开始实施", r"执行计划"
        ],
        required_patterns=[
            r"计划", r"步骤", r"方案", r"流程", r"顺序",
            r"第一.*第二", r"1\. .* 2\.", r"先.*再"
        ],
        excluded_patterns=[
            r"按计划", r"根据计划", r"按照方案", r"步骤如下",
            r"方案：", r"计划："
        ],
        feedback="检测到执行类请求，但未先展示计划。规则：先规划，再执行。",
        suggestion="建议格式：计划：1.[步骤1] 2.[步骤2]。开始执行？"
    ),
    Rule(
        id="vague_request",
        name="请求过于模糊",
        description="请求内容过于模糊，缺乏具体操作对象",
        trigger_patterns=[
            r"^[^？?]{0,10}[？?]$",  # 很短的问题
            r"^做吧[？?]?$",
            r"^继续[？?]?$",
            r"^开始[？?]?$",
            r"^执行[？?]?$",
            r"^好的[？?]?$",
            r"^可以[？?]?$"
        ],
        required_patterns=[
            r".{15,}"  # 至少15个字符的具体描述
        ],
        excluded_patterns=[
            r"计划.*：", r"步骤.*：", r"修改.*为", r"创建.*文件",
            r"因为", r"原因是", r"根因"  # 带原因的不算模糊
        ],
        feedback="检测到请求过于模糊，缺乏具体内容。请明确操作对象和目的。",
        suggestion="建议格式：对[对象]执行[具体操作]？"
    ),
]


def match_any(text: str, patterns: List[str]) -> bool:
    """检查文本是否匹配任一模式"""
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def audit_request(request_text: str, context: Optional[str] = None) -> Dict:
    """
    审核请求内容
    
    Args:
        request_text: 将要请求用户确认的内容
        context: 可选的上下文信息（之前对话的摘要）
    
    Returns:
        {
            "status": "OK" | "VIOLATION",
            "rule_id": str | None,
            "rule_name": str | None,
            "feedback": str | None,
            "suggestion": str | None
        }
    """
    if not request_text or not request_text.strip():
        return {
            "status": "VIOLATION",
            "rule_id": "empty_request",
            "rule_name": "空请求",
            "feedback": "请求内容为空",
            "suggestion": "请提供具体的请求内容"
        }
    
    # 合并上下文进行审核
    full_text = request_text
    if context:
        full_text = f"{context}\n{request_text}"
    
    for rule in RULES:
        # 检查是否触发此规则
        if not match_any(full_text, rule.trigger_patterns):
            continue
        
        # 检查是否被排除
        if rule.excluded_patterns and match_any(full_text, rule.excluded_patterns):
            continue
        
        # 检查是否满足必需条件
        if not match_any(full_text, rule.required_patterns):
            return {
                "status": "VIOLATION",
                "rule_id": rule.id,
                "rule_name": rule.name,
                "feedback": rule.feedback,
                "suggestion": rule.suggestion
            }
    
    return {"status": "OK"}


def audit_request_cli(request_text: str, context: Optional[str] = None) -> str:
    """
    命令行接口：返回简洁字符串结果
    
    Returns:
        "OK" 或 "VIOLATION:规则ID:反馈内容"
    """
    result = audit_request(request_text, context)
    if result["status"] == "OK":
        return "OK"
    else:
        return f"VIOLATION:{result['rule_id']}:{result['feedback']}"


# ============================================================
# 单元测试
# ============================================================

class TestSkipRootCause:
    """测试规则：跳过根因分析"""
    
    @staticmethod
    def test_violation_simple_cleanup():
        """违规：简单清理请求"""
        result = audit_request("清理 MEMORY.md 吧？")
        assert result["status"] == "VIOLATION", f"期望 VIOLATION，实际 {result}"
        assert result["rule_id"] == "skip_root_cause", f"期望 skip_root_cause，实际 {result['rule_id']}"
        print("  ✓ test_violation_simple_cleanup")
    
    @staticmethod
    def test_violation_delete_request():
        """违规：删除请求无分析"""
        result = audit_request("删除这些文件？")
        assert result["status"] == "VIOLATION"
        assert result["rule_id"] == "skip_root_cause"
        print("  ✓ test_violation_delete_request")
    
    @staticmethod
    def test_pass_with_root_cause():
        """通过：带根因分析"""
        result = audit_request("发现垃圾因递归累积，清理 MEMORY.md？")
        assert result["status"] == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_pass_with_root_cause")
    
    @staticmethod
    def test_pass_with_analysis_word():
        """通过：带分析关键词"""
        result = audit_request("分析后发现X原因，所以删除？")
        assert result["status"] == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_pass_with_analysis_word")
    
    @staticmethod
    def test_pass_with_because():
        """通过：带'因为'关键词"""
        result = audit_request("因为是过期数据，清理掉？")
        assert result["status"] == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_pass_with_because")
    
    @staticmethod
    def test_pass_context_aware():
        """通过：上下文中已有根因分析"""
        result = audit_request("现在清理 MEMORY.md？", context="之前分析过根因是递归累积")
        assert result["status"] == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_pass_context_aware")


class TestNoPlan:
    """测试规则：直接执行无计划"""
    
    @staticmethod
    def test_violation_execute_without_plan():
        """违规：执行无计划"""
        result = audit_request("开始执行吧？")
        assert result["status"] == "VIOLATION", f"期望 VIOLATION，实际 {result}"
        assert result["rule_id"] == "no_plan", f"期望 no_plan，实际 {result.get('rule_id')}"
        print("  ✓ test_violation_execute_without_plan")
    
    @staticmethod
    def test_violation_letsgo():
        """违规：开干无计划"""
        result = audit_request("开干？")
        assert result["status"] == "VIOLATION"
        print("  ✓ test_violation_letsgo")
    
    @staticmethod
    def test_pass_with_plan():
        """通过：带计划"""
        result = audit_request("按计划执行：1.A 2.B？")
        assert result["status"] == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_pass_with_plan")
    
    @staticmethod
    def test_pass_with_steps():
        """通过：带步骤"""
        result = audit_request("步骤：先A再B，开始？")
        assert result["status"] == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_pass_with_steps")
    
    @staticmethod
    def test_pass_with_numbered_list():
        """通过：带编号列表"""
        result = audit_request("1. 修改配置 2. 重启服务，执行吧？")
        assert result["status"] == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_pass_with_numbered_list")


class TestVagueRequest:
    """测试规则：请求过于模糊"""
    
    @staticmethod
    def test_violation_too_vague():
        """违规：过于模糊"""
        result = audit_request("做吧？")
        assert result["status"] == "VIOLATION", f"期望 VIOLATION，实际 {result}"
        assert result["rule_id"] == "vague_request", f"期望 vague_request，实际 {result.get('rule_id')}"
        print("  ✓ test_violation_too_vague")
    
    @staticmethod
    def test_violation_just_continue():
        """违规：只有'继续'"""
        result = audit_request("继续？")
        assert result["status"] == "VIOLATION"
        print("  ✓ test_violation_just_continue")
    
    @staticmethod
    def test_violation_just_ok():
        """违规：只有'好的'"""
        result = audit_request("好的？")
        assert result["status"] == "VIOLATION"
        print("  ✓ test_violation_just_ok")
    
    @staticmethod
    def test_pass_specific_request():
        """通过：具体请求"""
        result = audit_request("修改 config.json 的端口为8080？")
        assert result["status"] == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_pass_specific_request")
    
    @staticmethod
    def test_pass_detailed_question():
        """通过：详细的问题"""
        result = audit_request("是否需要检查所有配置文件并更新过期的设置？")
        assert result["status"] == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_pass_detailed_question")


class TestIntegration:
    """集成测试"""
    
    @staticmethod
    def test_real_scenario_violation():
        """真实场景：违规请求"""
        result = audit_request("清理 MEMORY.md 吧？")
        assert result["status"] == "VIOLATION"
        assert "根因" in result["feedback"]
        assert result["suggestion"] != ""
        print("  ✓ test_real_scenario_violation")
    
    @staticmethod
    def test_real_scenario_pass():
        """真实场景：合规请求"""
        result = audit_request(
            "发现 MEMORY.md 垃圾是因递归累积导致，"
            "计划：1.修复Guardian 2.清理垃圾。执行？"
        )
        assert result["status"] == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_real_scenario_pass")
    
    @staticmethod
    def test_context_rescue():
        """上下文补救：上下文中有根因"""
        result = audit_request(
            "清理 MEMORY.md？",
            context="分析发现垃圾是因为Guardian递归累积bug"
        )
        assert result["status"] == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_context_rescue")
    
    @staticmethod
    def test_empty_request():
        """空请求处理"""
        result = audit_request("")
        assert result["status"] == "VIOLATION"
        assert result["rule_id"] == "empty_request"
        print("  ✓ test_empty_request")
    
    @staticmethod
    def test_whitespace_request():
        """纯空白请求"""
        result = audit_request("   \n\t  ")
        assert result["status"] == "VIOLATION"
        print("  ✓ test_whitespace_request")


class TestE2E:
    """端到端测试：模拟真实调用链"""
    
    @staticmethod
    def test_cli_interface_ok():
        """测试 CLI 接口：通过"""
        result = audit_request_cli("因为过期，删除文件？")
        assert result == "OK", f"期望 OK，实际 {result}"
        print("  ✓ test_cli_interface_ok")
    
    @staticmethod
    def test_cli_interface_violation():
        """测试 CLI 接口：违规"""
        result = audit_request_cli("清理吧？")
        assert result.startswith("VIOLATION:"), f"期望 VIOLATION:xxx，实际 {result}"
        print("  ✓ test_cli_interface_violation")
    
    @staticmethod
    def test_full_flow():
        """完整流程：违规→修改→通过"""
        # 1. 初始请求违规
        request = "清理 MEMORY.md 吧？"
        result = audit_request(request)
        assert result["status"] == "VIOLATION"
        
        # 2. 根据反馈修改请求（必须包含"因"或"根因"关键字）
        modified = f"发现因递归累积导致的问题，{request}"
        result2 = audit_request(modified)
        assert result2["status"] == "OK", f"修改后仍违规: {result2}"
        print("  ✓ test_full_flow")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print(" request_auditor.py 测试报告")
    print("="*60)
    
    test_count = 0
    pass_count = 0
    
    test_classes = [
        ("skip_root_cause 规则", TestSkipRootCause),
        ("no_plan 规则", TestNoPlan),
        ("vague_request 规则", TestVagueRequest),
        ("集成测试", TestIntegration),
        ("E2E 测试", TestE2E),
    ]
    
    for name, test_class in test_classes:
        print(f"\n【{name}】")
        for method_name in dir(test_class):
            if method_name.startswith('test_'):
                method = getattr(test_class, method_name)
                test_count += 1
                try:
                    method()
                    pass_count += 1
                except AssertionError as e:
                    print(f"  ✗ {method_name}: {e}")
                except Exception as e:
                    print(f"  ✗ {method_name}: 异常 {e}")
    
    print("\n" + "="*60)
    print(f" 测试结果: {pass_count}/{test_count} 通过")
    print("="*60 + "\n")
    
    return pass_count == test_count


# ============================================================
# 主入口
# ============================================================

def main():
    """主函数"""
    if len(sys.argv) < 2:
        # 无参数时运行测试
        success = run_all_tests()
        sys.exit(0 if success else 1)
    
    # 有参数时执行审核
    request_text = sys.argv[1]
    context = None
    
    # 解析可选的 context 参数
    if len(sys.argv) >= 4 and sys.argv[2] == "--context":
        context = sys.argv[3]
    
    result = audit_request_cli(request_text, context)
    print(result)
    
    # 返回码：0=通过，1=违规
    sys.exit(0 if result == "OK" else 1)


if __name__ == "__main__":
    main()
