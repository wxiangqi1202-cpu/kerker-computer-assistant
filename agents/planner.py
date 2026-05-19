"""子智能体：任务拆解 —— 输出结构化任务列表"""

from agents.base import SubAgent
from agents import register_agent


@register_agent
class Planner(SubAgent):
    name = "planner"
    description = "把复杂任务拆解为子步骤(返回JSON)。调用后根据规划结果立刻调度其他agent执行，不要停下来"
    model = "deepseek-v4-flash"
    system_prompt = (
        "你是一个任务拆解专家。\n"
        "接收到一个复杂任务后，你需要拆解为 2-7 个具体的、可执行的子步骤。\n\n"
        "你必须严格按以下 JSON 格式输出，不要输出其他任何内容：\n"
        '{"tasks": [{"step": "步骤简述(10字以内)"}, ...]}\n\n'
        "示例：\n"
        '{"tasks": [{"step": "调研技术方案"}, {"step": "编写核心代码"}, {"step": "测试验证"}]}\n\n'
        "要求：每个 step 控制在 10 个字以内，简洁明确。只输出 JSON，不要解释。"
    )
    allowed_skills = []
    max_turns = 1
