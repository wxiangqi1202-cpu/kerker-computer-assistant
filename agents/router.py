"""
自动路由层 —— 中英文双语支持
根据用户输入特征 + 对话上下文决定：直接回答 / 自动注入 planner / 指定单个 agent

评分体系：
  结构信号（然后/then/first...）           每命中 +1
  动作词（搜索/search/分析/analyze...）    ≥2个 +2, 1个 +1
  逗号/and/then ≥2                        +1
  长文本 >60字符                           +1
  询问类（介绍/what is/explain...）        -2
  总分 ≥2 → PLAN
"""

import re

_I = re.IGNORECASE

_STRUCTURE_SIGNALS = [
    re.compile(r"(首先|然后|接着|最后|第[一二三四五六七]|分别)"),
    re.compile(r"(先|再|接下来|之后|完成后)"),
    re.compile(r"(并且|同时|以及).+(并且|同时|以及|还要)"),
    re.compile(r"(从.+到.+再到)"),
    re.compile(r"(写一个|开发一个|实现一个|搭建一个|构建).{4,}"),
    re.compile(r"包括.{2,}(和|、|以及|还有|与)"),
    re.compile(r"(、).{1,6}(、)"),
    re.compile(r"(步骤|流程|方案|计划|阶段)"),
    re.compile(r"\b(first|then|after that|finally|next|step \d|phase)\b", _I),
    re.compile(r"\b(and then|before|once done|afterward)\b", _I),
    re.compile(r"\b(including|consists? of)\b.+(and|,)", _I),
    re.compile(r"\b(build|create|develop|implement|write)\b.{10,}", _I),
]

_ACTION_WORDS_ZH = re.compile(
    r"(分析|对比|调研|设计|规划|评估|总结|整理|梳理|编写|实现|测试|部署"
    r"|搭建|优化|重构|审查|开发|撰写|生成|选型|排查"
    r"|搜索|查找|查询|检索|翻译|转换|发送|推送|通知"
    r"|下载|上传|导入|导出|读取|写入|创建|删除|修改"
    r"|安装|配置|编译|运行|调试|监控|备份|迁移|清理)"
)

_ACTION_WORDS_EN = re.compile(
    r"\b(analy[zs]e|compare|research|design|plan|evaluate|summarize|organize"
    r"|write|implement|test|deploy|build|optimize|refactor|review|develop|generate"
    r"|search|find|translate|convert|send|notify|push"
    r"|download|upload|import|export|read|create|delete|modify|update"
    r"|install|configure|compile|run|debug|monitor|backup|migrate|clean"
    r"|fetch|scrape|parse|format|check|fix|setup|connect)\b", _I
)

_INQUIRY_PATTERNS = [
    re.compile(r"(介绍|解释|说明|描述|讲解|讲一下|说一下|是什么|什么是|怎么理解|有哪些|区别)"),
    re.compile(r"^(什么|哪些|怎么|如何|为什么|能不能).{0,6}(步骤|流程|方案|阶段|区别|概念|原理)"),
    re.compile(r"\b(what is|what are|explain|describe|tell me about|how does)\b", _I),
    re.compile(r"^(what|how|why|can you)\b.{0,15}\??\s*$", _I),
]

_DIRECT_AGENT_KEYWORDS = {
    "code_reviewer": [
        re.compile(r"(审查|代码检查|帮我看看.{0,6}代码|检查.{0,6}代码)"),
        re.compile(r"\b(review|code review|check.{0,8}code|audit.{0,8}code)\b", _I),
    ],
    "ascend_dev": [
        re.compile(r"(算子开发|AscendC|ascendc|写一个算子|Tiling|tiling)", _I),
    ],
    "ascend_debug": [
        re.compile(r"(算子调试|算子报错|编译.{0,6}错|npu.{0,4}error|ccec)", _I),
    ],
    "researcher": [
        re.compile(r"(搜索|搜一下|查一下|查找|调研|了解一下|最新|新闻|动态)"),
        re.compile(r"\b(search|look up|find out|latest|news|trending)\b", _I),
    ],
}

_SIMPLE_PATTERNS = [
    re.compile(r"^.{0,5}$"),
    re.compile(r"^(你好|hi|hello|hey|thanks?|谢谢|ok|好的|嗯|是的|不是|什么是|yes|no|sure|nope)\s*$", _I),
    re.compile(r"^(几点|时间|天气|日期|time|weather|date)\b", _I),
]

_CONTINUE_PATTERNS = [
    re.compile(r"^(好的|ok|开始|继续|执行|go|来吧|干吧|开搞|走起|开始吧|那就).{0,10}$", _I),
    re.compile(r"^(按照|按|根据).{0,8}(方案|规划|计划|步骤|执行|做|来)"),
    re.compile(r"^(go ahead|proceed|continue|start|do it|let'?s go|yes.{0,5}do it)\s*$", _I),
]


def _is_step_pending(step):
    """兼容 ProgressStep (enum) 和 PlanStep (string) 的 pending 判断"""
    status = getattr(step, "status", "")
    if hasattr(status, "value"):
        return status.value == "pending"
    return status == "pending"


_INTENT_PLAN_PATTERNS = [
    re.compile(r"(创建|生成|打造|蒸馏|新建).{0,12}(角色|人设|persona|人格)", _I),
    re.compile(r"(角色|人设).{0,4}(创建|生成|蒸馏|定制)", _I),
    re.compile(r"\b(create|make|build|generate|craft).{0,20}(role|persona|character)\b", _I),
    re.compile(r".{2,}(然后|再|接着|之后).{2,}(发送|发到|推送|通知|发给)", _I),
    re.compile(r".{2,}(然后|再|接着|之后).{2,}(整理|总结|生成|写成|输出)", _I),
    re.compile(r"\b.{3,}(then|and).{3,}(send|push|notify|forward)\b", _I),
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

    for pat in _STRUCTURE_SIGNALS:
        if pat.search(text):
            score += 1

    actions_zh = set(_ACTION_WORDS_ZH.findall(text))
    actions_en = set(_ACTION_WORDS_EN.findall(text.lower()))
    action_hits = len(actions_zh) + len(actions_en)

    if action_hits >= 2:
        score += 2
    elif action_hits >= 1:
        score += 1

    if len(text) > 60:
        score += 1

    separators = text.count("，") + text.count(",") + text.lower().count(" and ") + text.lower().count(" then ")
    if separators >= 2:
        score += 1

    for pat in _INQUIRY_PATTERNS:
        if pat.search(text):
            score -= 2
            break

    return max(score, 0)


def _check_continue(text):
    for pat in _CONTINUE_PATTERNS:
        if pat.search(text.strip()):
            return True
    return False


def route(user_input, available_agents=None, context=None):
    """
    判定优先级:
    1. 明确继续指令 + 有未完成规划 → 继续
    2. 简单对话 → 直接回答（即使有未完成规划也不强制继续）
    3. 复杂任务 / agent 关键词 → 规划或单 agent
    4. 有未完成规划但用户发了新的复杂请求 → 新规划
    5. 默认直接回答
    """
    text = user_input.strip()

    if context and context.has_plan and _check_continue(text):
        return RouteDecision(RouteDecision.PLAN, reason="继承上轮规划")

    for pat in _SIMPLE_PATTERNS:
        if pat.search(text):
            return RouteDecision(RouteDecision.DIRECT, reason="简单对话")

    if context and context.has_plan:
        steps = context.plan_steps
        pending = [s for s in steps if _is_step_pending(s)]
        if pending and _calc_complexity(text) >= 2:
            return RouteDecision(RouteDecision.PLAN, reason=f"上轮规划有 {len(pending)} 步未完成")

    for pat in _INTENT_PLAN_PATTERNS:
        if pat.search(text):
            return RouteDecision(RouteDecision.PLAN, reason="意图匹配")

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
