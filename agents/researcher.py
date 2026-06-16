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
        "优先使用 web_search 工具搜索信息（速度最快），需要详细内容时再用 web_summary 获取特定网页。\n"
        "搜集信息后，以结构化的方式整理要点，注明信息来源。\n"
        "跟随用户的输入语言回答，简洁且有条理。"
    )
    allowed_skills = ["web_search", "web_summary", "run_shell"]
    max_turns = 5
