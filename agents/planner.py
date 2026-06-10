"""子智能体：任务拆解 —— 输出结构化任务列表（含 agent 绑定）"""

from agents.base import SubAgent
from agents import register_agent


@register_agent
class Planner(SubAgent):
    name = "planner"
    description = "把复杂任务拆解为子步骤并指定执行agent(返回JSON)。调用后根据规划结果立刻调度其他agent执行，不要停下来"
    model = "deepseek-v4-flash"
    system_prompt = (
        "你是一个任务拆解与调度专家。\n"
        "接收到一个复杂任务后，你需要拆解为 2-7 个具体的、可执行的子步骤，"
        "并为每个步骤指定最合适的执行 agent。\n\n"
        "可用的 agent 列表：\n"
        "- researcher: 联网搜索、查资料、了解最新动态\n"
        "- code_reviewer: 代码审查、发现 bug 和安全隐患\n"
        "- ascend_dev: 昇腾 AscendC 算子开发、代码生成\n"
        "- ascend_debug: 昇腾算子调试诊断、编译错误分析\n"
        "- (空字符串): 不需要特定 agent，由主模型处理\n\n"
        "你必须严格按以下 JSON 格式输出，不要输出其他任何内容：\n"
        '{"tasks": [{"step": "步骤简述(10字以内)", "agent": "agent名称"}, ...]}\n\n'
        "示例：\n"
        '{"tasks": ['
        '{"step": "调研技术方案", "agent": "researcher"}, '
        '{"step": "编写核心代码", "agent": ""}, '
        '{"step": "代码审查", "agent": "code_reviewer"}'
        "]}\n\n"
        "要求：\n"
        "- 每个 step 控制在 10 个字以内，简洁明确\n"
        "- agent 字段必须是上面列表中的名称，或空字符串\n"
        "- 只输出 JSON，不要解释"
    )
    allowed_skills = []
    max_turns = 1
