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
        "使用 read_file 工具读取代码文件，使用 run_shell 运行测试或检查工具。\n"
        "审查时关注：\n"
        "1. 逻辑错误和潜在 bug\n"
        "2. 安全隐患\n"
        "3. 性能瓶颈\n"
        "4. 代码风格和可读性\n"
        "给出具体的行号和修改建议，跟随用户输入语言回答。"
    )
    allowed_skills = ["read_file", "run_shell"]
    max_turns = 5
