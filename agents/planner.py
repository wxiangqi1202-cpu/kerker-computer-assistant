"""子智能体：任务拆解 —— 输出结构化任务列表（含 agent 绑定）"""

from agents.base import SubAgent
from agents import register_agent

_PLANNER_PROMPT_TEMPLATE = """\
你是一个任务拆解与调度专家。
接收到一个复杂任务后，你需要拆解为 2-7 个具体的、可执行的子步骤，并为每个步骤指定最合适的执行 agent 和依赖关系。

可用的 agent 列表：
{agent_list}
- (空字符串): 不需要特定 agent，由主模型处理

你必须严格按以下 JSON 格式输出，不要输出其他任何内容：
{{"tasks": [{{"step": "步骤简述(15字以内)", "agent": "agent名称", "deps": [依赖的步骤索引]}}, ...]}}

拆解策略：
- 按能力边界拆分：不同类型的工作分给不同 agent
- 尽量并行：没有数据依赖的步骤 deps 设为 []，让框架并行执行
- 避免过细：一个 agent 能一次完成的工作不要拆成多步
- 信息收集类步骤排在前面，依赖其结果的步骤通过 deps 串联

deps 规则：
- deps 是该步骤所依赖的前序步骤索引（0开始），空数组表示可立即执行
- 只有当步骤确实需要前一步的输出才标记依赖
- 不可自引用

示例1（有依赖）：
{{"tasks": [{{"step": "调研技术方案", "agent": "researcher", "deps": []}}, {{"step": "编写核心代码", "agent": "", "deps": [0]}}, {{"step": "代码审查", "agent": "code_reviewer", "deps": [1]}}]}}

示例2（可并行）：
{{"tasks": [{{"step": "搜索前端框架资料", "agent": "researcher", "deps": []}}, {{"step": "搜索后端框架资料", "agent": "researcher", "deps": []}}, {{"step": "整合方案文档", "agent": "", "deps": [0, 1]}}]}}

要求：
- 每个步骤必须不同，禁止重复
- agent 字段必须是上面列表中的名称，或空字符串
- 没有合适 agent 的步骤用空字符串（由主模型处理）
- 只输出 JSON，不要解释\
"""


def _build_agent_list():
    """动态构建可用 agent 清单（含实际 skill 列表）"""
    from agents import get_all_agents
    lines = []
    for name, agent in get_all_agents().items():
        if name == "planner":
            continue
        skills_desc = ""
        if agent.allowed_skills:
            skills_desc = f"  可用工具: {', '.join(agent.allowed_skills)}"
        lines.append(f"- {name}: {agent.description}{skills_desc}")
    return "\n".join(lines)


@register_agent
class Planner(SubAgent):
    name = "planner"
    description = "把复杂任务拆解为子步骤并指定执行agent(返回JSON)。调用后根据规划结果立刻调度其他agent执行，不要停下来"
    model = "deepseek-v4-flash"
    system_prompt = ""
    allowed_skills = []
    max_turns = 1

    async def _execute(self, task, on_status=None):
        prompt = _PLANNER_PROMPT_TEMPLATE.format(
            agent_list=_build_agent_list()
        )
        orig = self.system_prompt
        self.system_prompt = prompt
        try:
            return await super()._execute(task, on_status=on_status)
        finally:
            self.system_prompt = orig
