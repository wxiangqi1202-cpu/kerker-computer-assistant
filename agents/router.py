"""
自动路由层 —— 程序级判定是否需要规划，替代纯 prompt 暗示
根据用户输入特征 + 对话上下文决定：直接回答 / 自动注入 planner / 指定单个 agent

判定优先级：
  0. 上下文继承（上轮刚完成规划，短指令继承 plan 模式）
  1. 简单对话 → DIRECT
  2. 复杂度评分 ≥ 2 → PLAN
  3. 专属 Agent 关键词 → SINGLE_AGENT
  4. 默认 → DIRECT
"""

import re

_COMPLEX_SIGNALS = [
    re.compile(r"(帮我|请你|麻烦).{0,8}(分析|对比|调研|设计|规划|评估|总结|整理|梳理)"),
    re.compile(r"(步骤|流程|方案|计划|阶段)"),
    re.compile(r"(首先|然后|接着|最后|第[一二三四五六七]|分别)"),
    re.compile(r"(并且|同时|以及).+(并且|同时|以及|还要)"),
    re.compile(r"(从.+到.+再到)"),
    re.compile(r"(写一个|开发一个|实现一个|搭建一个|构建).{4,}"),
    re.compile(r"包括.{2,}(和|、|以及|还有|与)"),
    re.compile(r"(、).{1,6}(、)"),
    re.compile(r"(先|再|接下来|之后|完成后)"),
]

_INQUIRY_PATTERNS = [
    re.compile(r"(介绍|解释|说明|描述|讲解|讲一下|说一下|是什么|什么是|怎么理解|有哪些|区别)"),
    re.compile(r"^(什么|哪些|怎么|如何|为什么|能不能).{0,6}(步骤|流程|方案|阶段|区别|概念|原理)"),
]

_DIRECT_AGENT_KEYWORDS = {
    "code_reviewer": [
        re.compile(r"(审查|review|代码检查|code review|帮我看看.{0,6}代码|检查.{0,6}代码)"),
    ],
    "ascend_dev": [
        re.compile(r"(算子开发|AscendC|ascendc|写一个算子|Tiling|tiling)"),
    ],
    "ascend_debug": [
        re.compile(r"(算子调试|算子报错|编译.{0,6}错|npu.{0,4}error|ccec)"),
    ],
    "researcher": [
        re.compile(r"(搜索|搜一下|查一下|查找|调研|了解一下|最新|新闻|动态)"),
    ],
}

_SIMPLE_PATTERNS = [
    re.compile(r"^.{0,8}$"),
    re.compile(r"^(你好|hi|hello|谢谢|ok|好的|嗯|是的|不是|什么是)"),
    re.compile(r"^(几点|时间|天气|日期)"),
]

_CONTINUE_PATTERNS = [
    re.compile(r"^(好的|ok|开始|继续|执行|go|来吧|干吧|开搞|走起|开始吧|那就).{0,10}$"),
    re.compile(r"^(按照|按|根据).{0,8}(方案|规划|计划|步骤|执行|做|来)"),
]


class RouteDecision:
    DIRECT = "direct"
    PLAN = "plan"
    SINGLE_AGENT = "single_agent"

    def __init__(self, action, agent_name=None, reason=""):
        self.action = action
        self.agent_name = agent_name
        self.reason = reason

    def __repr__(self):
        if self.action == self.SINGLE_AGENT:
            return f"Route({self.action} -> {self.agent_name}, {self.reason})"
        return f"Route({self.action}, {self.reason})"


def _calc_complexity(text):
    score = 0
    for pat in _COMPLEX_SIGNALS:
        if pat.search(text):
            score += 1
    if len(text) > 80:
        score += 1
    if text.count("，") + text.count(",") >= 3:
        score += 1

    for pat in _INQUIRY_PATTERNS:
        if pat.search(text):
            score -= 2
            break

    return max(score, 0)


def _check_continue(text):
    """检测是否为继续/确认类指令"""
    for pat in _CONTINUE_PATTERNS:
        if pat.search(text.strip()):
            return True
    return False


def route(user_input, available_agents=None, context=None):
    """
    判定优先级: 上下文继承 → 简单对话 → 复杂任务 → agent关键词 → 默认
    context: AgentContext 实例，用于感知上一轮状态
    """
    text = user_input.strip()

    if context and context.has_plan and _check_continue(text):
        return RouteDecision(RouteDecision.PLAN, reason="继承上轮规划")

    if context and context.has_plan:
        pending = [s for s in context.plan_steps if s.status == "pending"]
        if pending:
            return RouteDecision(RouteDecision.PLAN, reason=f"上轮规划有 {len(pending)} 步未完成")

    for pat in _SIMPLE_PATTERNS:
        if pat.search(text):
            return RouteDecision(RouteDecision.DIRECT, reason="简单对话")

    complexity = _calc_complexity(text)
    if complexity >= 2:
        return RouteDecision(RouteDecision.PLAN, reason=f"复杂度信号 {complexity}")

    for agent_name, patterns in _DIRECT_AGENT_KEYWORDS.items():
        if available_agents and agent_name not in available_agents:
            continue
        for pat in patterns:
            if pat.search(text):
                return RouteDecision(
                    RouteDecision.SINGLE_AGENT,
                    agent_name=agent_name,
                    reason=f"关键词匹配 {agent_name}",
                )

    return RouteDecision(RouteDecision.DIRECT, reason="默认直接回答")
