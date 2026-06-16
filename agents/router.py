"""
路由层 v2 —— LLM 自主决策架构

设计哲学（参考 Claude Code / Kerminal / OpenClaw）：
  框架只负责确定性的快速分流，不做复杂度预判。
  任务复杂度的判断交给主 LLM（通过 system prompt 指导）。

框架职责（硬规则，确定性，0ms）：
  1. 简单问候/寒暄 → 标记为 DIRECT（可跳过工具注入，省 token）
  2. 算子强制规划 → 标记为 PLAN（业务硬性要求）
  3. "继续/开始" + 有未完成 plan → 标记为 PLAN（继承执行）
  4. 有未完成 plan + 新话题 → 清除 plan
  5. 其他所有输入 → PASS_THROUGH（交给 LLM 自己决定）

LLM 职责（通过 AGENT_DIRECTIVE 指导）：
  - 判断任务是否需要多步规划 → 自主调用 agent_planner
  - 判断是否需要工具 → 自主调用相应工具
  - 简单任务直接回答，复杂任务规划后执行
"""

import re

_I = re.IGNORECASE


class RouteDecision:
    DIRECT = "direct"
    PLAN = "plan"
    PASS_THROUGH = "pass_through"

    def __init__(self, action, reason="", _clear_plan=False):
        self.action = action
        self.reason = reason
        self.clear_plan = _clear_plan

    def __repr__(self):
        return f"Route({self.action}, {self.reason})"


_SIMPLE_PATTERNS = [
    re.compile(r"^.{0,5}$"),
    re.compile(r"^(你好|hi|hello|hey|thanks?|谢谢|ok|好的|嗯|是的|不是|yes|no|sure|nope)\s*[!！.。]?$", _I),
    re.compile(r"^(几点|时间|天气|日期|time|weather|date)\b", _I),
]

_TOOL_INTENT_PATTERNS = re.compile(
    r"(切换|换成|用|扮演|变成|成为|switch|use|become|act as).{0,8}"
    r"(角色|模式|翻译|代码|写作|助手|role|mode|translator|coder)"
    r"|创建|蒸馏|生成.*角色|记住|忘记|搜索|查一下|发送|发到",
    _I,
)

_CONTINUE_PATTERNS = [
    re.compile(r"^(好的|ok|开始|继续|执行|go|来吧|干吧|开搞|走起|开始吧|那就).{0,10}$", _I),
    re.compile(r"^(按照|按|根据).{0,8}(方案|规划|计划|步骤|执行|做|来)"),
    re.compile(r"^(go ahead|proceed|continue|start|do it|let'?s go|yes.{0,5}do it)\s*$", _I),
]

_FORCE_PLAN_PATTERNS = [
    re.compile(r"(算子开发|AscendC|ascendc|写一个算子|Tiling|tiling)", _I),
    re.compile(r"(算子调试|算子报错|编译.{0,6}错|npu.{0,4}error|ccec)", _I),
]


def _check_continue(text):
    for pat in _CONTINUE_PATTERNS:
        if pat.search(text.strip()):
            return True
    return False


def _is_step_pending(step):
    """兼容 ProgressStep (enum) 和 PlanStep (string) 的 pending 判断"""
    status = getattr(step, "status", "")
    if hasattr(status, "value"):
        return status.value == "pending"
    return status == "pending"


def route(user_input, available_agents=None, context=None):
    """
    最小化路由：只处理确定性硬规则，其余交给 LLM。

    返回:
      PLAN → 强制规划（算子/继承）
      DIRECT → 确定不需要工具和规划（简单问候）
      PASS_THROUGH → 交给 LLM 自行决定（大多数情况）
    """
    text = user_input.strip()
    has_active_plan = context and context.has_plan

    if has_active_plan and _check_continue(text):
        return RouteDecision(RouteDecision.PLAN, reason="继承上轮规划")

    for pat in _SIMPLE_PATTERNS:
        if pat.search(text):
            if _TOOL_INTENT_PATTERNS.search(text):
                break
            if has_active_plan:
                return RouteDecision(RouteDecision.DIRECT, reason="简单对话，清除旧规划",
                                     _clear_plan=True)
            return RouteDecision(RouteDecision.DIRECT, reason="简单对话")

    for pat in _FORCE_PLAN_PATTERNS:
        if pat.search(text):
            return RouteDecision(RouteDecision.PLAN, reason="算子任务强制规划")

    if has_active_plan:
        return RouteDecision(RouteDecision.PASS_THROUGH, reason="有旧规划但新话题",
                             _clear_plan=True)

    return RouteDecision(RouteDecision.PASS_THROUGH, reason="交由LLM判断")
