"""子智能体：搜索调研"""

from agents.base import SubAgent
from agents import register_agent


@register_agent
class Researcher(SubAgent):
    name = "researcher"
    description = "联网搜索信息并整理摘要，适合查资料、了解最新动态"
    model = "deepseek-v4-flash"
    system_prompt = (
        "你是一个高效的搜索调研助手。\n\n"
        "工作流程：\n"
        "1. 用 web_search 搜索信息（速度最快，优先使用）\n"
        "2. 对最相关的 1-2 条结果用 web_summary 获取详细内容\n"
        "3. 整理为结构化摘要，注明信息来源\n\n"
        "输出要求：\n"
        "- 按重要性排列要点，每条标注来源\n"
        "- 区分事实与推测，不确定的信息标注\n"
        "- 信息矛盾时列出不同观点\n"
        "- 跟随用户的输入语言回答"
    )
    allowed_skills = ["web_search", "web_summary", "run_shell"]
    max_turns = 5
