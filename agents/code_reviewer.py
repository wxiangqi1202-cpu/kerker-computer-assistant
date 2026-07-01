"""子智能体：代码审查"""

from agents.base import SubAgent
from agents import register_agent


@register_agent
class CodeReviewer(SubAgent):
    name = "code_reviewer"
    description = "审查代码质量，发现 bug、安全隐患和优化空间"
    model = "deepseek-v4-pro"
    system_prompt = (
        "你是一个严格的代码审查专家。\n"
        "使用 read_file 读取代码，run_shell 运行测试或检查工具。\n\n"
        "审查维度（按严重性排列）：\n"
        "1. 🔴 严重：逻辑错误、安全漏洞（注入/越权/信息泄露）\n"
        "2. 🟡 警告：性能瓶颈、资源泄漏、并发问题\n"
        "3. 🔵 建议：代码风格、可读性、设计模式改进\n\n"
        "输出格式：\n"
        "- 每个问题标注严重性、文件名:行号、问题描述、修复建议\n"
        "- 没有问题的维度不需要提及\n"
        "- 最后给出整体评价（1-2句话）\n"
        "- 跟随用户输入语言回答"
    )
    allowed_skills = ["read_file", "run_shell"]
    max_turns = 5
