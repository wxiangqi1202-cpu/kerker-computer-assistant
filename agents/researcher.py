"""子智能体：搜索调研"""

from agents.base import SubAgent
from agents import register_agent


@register_agent
class Researcher(SubAgent):
    name = "researcher"
    description = "联网搜索信息并整理摘要，适合查资料、了解最新动态"
    model = "deepseek-v4-flash"
    system_prompt = (
        "你是一个高效的搜索调研助手。\n"
        "使用 web_summary 工具获取网页内容，使用 run_shell 执行搜索命令。\n"
        "搜集信息后，以结构化的方式整理要点，注明信息来源。\n"
        "回答使用中文，简洁有条理。"
    )
    allowed_skills = ["web_summary", "run_shell"]
    max_turns = 5
