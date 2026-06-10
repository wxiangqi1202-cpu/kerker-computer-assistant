"""
自动路由层 —— 程序级判定是否需要规划，替代纯 prompt 暗示
根据用户输入特征决定：直接回答 / 自动注入 planner / 指定单个 agent
"""

import re

_COMPLEX_SIGNALS = [
    re.compile(r"(帮我|请你|麻烦).{0,8}(分析|对比|调研|设计|规划|评估|总结|整理|梳理)"),
    re.compile(r"(步骤|流程|方案|计划|阶段)"),
    re.compile(r"(首先|然后|接着|最后|第[一二三四五六七]|分别)"),
    re.compile(r"(并且|同时|以及).+(并且|同时|以及|还要)"),
    re.compile(r"(从.+到.+再到)"),
    re.compile(r"(写一个|开发一个|实现一个|搭建一个|构建).{4,}"),
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


class RouteDecision:
    """路由决策结果"""
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


def route(user_input, available_agents=None):
    """
    根据用户输入决定路由策略。
    返回 RouteDecision:
      - DIRECT: 主模型直接回答，不注入规划
      - PLAN: 自动先调用 planner
      - SINGLE_AGENT: 直接调用指定 agent
    """
    text = user_input.strip()

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

    for pat in _SIMPLE_PATTERNS:
        if pat.search(text):
            return RouteDecision(RouteDecision.DIRECT, reason="简单对话")

    complexity = 0
    for pat in _COMPLEX_SIGNALS:
        if pat.search(text):
            complexity += 1
    if len(text) > 80:
        complexity += 1
    if text.count("，") + text.count(",") >= 3:
        complexity += 1

    if complexity >= 2:
        return RouteDecision(RouteDecision.PLAN, reason=f"复杂度信号 {complexity}")

    return RouteDecision(RouteDecision.DIRECT, reason="默认直接回答")
