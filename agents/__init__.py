"""
子智能体系统 v2 —— 注册表 + 自动路由 + 共享上下文 + 任务面板

核心改进：
- AgentContext 共享工作记忆，planner 结果注入后续 agent
- 步骤-Agent 绑定，planner 指定谁执行
- 自动路由层判定是否需要规划
- agent 执行结果自动摘要写入共享记忆
"""

import json
import importlib
import pkgutil

import skills as skills_module
from agents.base import SubAgent
from agents.context import get_context, reset_context

_registry = {}
_active_spinner = None
_active_taskboard = None
_planner_used = False


def set_spinner(spinner):
    global _active_spinner
    _active_spinner = spinner


def set_taskboard(taskboard):
    global _active_taskboard
    _active_taskboard = taskboard


def register_agent(agent_class):
    instance = agent_class()
    _registry[instance.name] = instance
    _register_as_skill(instance)
    return agent_class


def get_agent(name):
    return _registry.get(name)


def get_all_agents():
    return dict(_registry)


def _is_similar(a, b):
    """判断两个步骤名是否重复（精确 / 包含 / 去标点 / 字符重叠度高）"""
    if a == b:
        return True
    if a in b or b in a:
        return True
    strip_chars = " \t.,，。、!！?？~·"
    sa, sb = a.strip(strip_chars), b.strip(strip_chars)
    if sa == sb:
        return True
    if len(sa) >= 3 and len(sb) >= 3:
        common = sum(1 for c in sa if c in sb)
        ratio = common / max(len(sa), len(sb))
        if ratio >= 0.6:
            return True
    return False


def _extract_first_json(text):
    """从文本中提取第一个完整的 JSON 对象（括号配对）"""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _parse_planner_result(text):
    """从 planner 返回文本中提取第一个完整 JSON，解析任务列表，模糊去重"""
    try:
        json_str = _extract_first_json(text)
        if not json_str:
            return []
        data = json.loads(json_str)
        tasks = data.get("tasks", [])
        result = []
        for t in tasks:
            step = t.get("step", "").strip()
            if not step:
                continue
            duplicate = False
            for existing in result:
                if _is_similar(step, existing["step"]):
                    duplicate = True
                    break
            if not duplicate:
                result.append({"step": step, "agent": t.get("agent", "")})
        return result
    except Exception:
        pass
    return []


def _summarize_result(text, max_len=200):
    """提取 agent 返回结果的首行摘要"""
    if not text:
        return ""
    first_line = text.strip().split("\n")[0]
    if len(first_line) > max_len:
        return first_line[:max_len] + "..."
    return first_line


def _sync_taskboard():
    """将 AgentContext 的步骤状态完整同步到 taskboard（全量替换，非追加）"""
    if not _active_taskboard:
        return
    ctx = get_context()
    items = ctx.to_taskboard_items()
    _active_taskboard.replace_all(items)


def _register_as_skill(agent):
    def _on_status(text):
        if _active_spinner:
            _active_spinner.update_sub(agent.name, [text])

    async def _run_agent(task):
        global _planner_used
        ctx = get_context()

        if agent.name == "planner" and _planner_used:
            return "规划已完成，请根据现有规划继续执行。"

        if _active_spinner:
            from display.spinner import AGENT_TIPS
            _active_spinner.update_sub(agent.name, AGENT_TIPS)

        matched_step = None

        if agent.name == "planner":
            if _active_taskboard:
                _active_taskboard.add_or_update("规划中...", "running")
            ctx.set_original_task(task)
            _planner_used = True
        else:
            matched_step_obj = ctx.advance_step(agent_name=agent.name)
            if matched_step_obj:
                matched_step = matched_step_obj.step
                _sync_taskboard()

            context_prompt = ctx.build_context_prompt(agent_name=agent.name)
            if context_prompt:
                task = f"{context_prompt}\n\n[当前任务] {task}"

        try:
            result = await agent.run(task, on_status=_on_status)

            if agent.name == "planner":
                steps = _parse_planner_result(result)
                if steps:
                    ctx.set_plan(steps)
                    _sync_taskboard()
                else:
                    if _active_taskboard:
                        _active_taskboard.add_or_update("规划中...", "done")
            else:
                summary = _summarize_result(result)
                ctx.add_memory(agent.name, task[:200], summary)

                if matched_step:
                    ctx.complete_step(matched_step, summary=summary)
                    _sync_taskboard()

        except Exception as err:
            error_msg = f"[{agent.name}] 执行失败: {str(err)[:150]}"

            if matched_step:
                ctx.fail_step(matched_step, error=str(err)[:100])
                _sync_taskboard()
            elif agent.name == "planner" and _active_taskboard:
                _active_taskboard.add_or_update("规划中...", "error")

            ctx.add_memory(agent.name, task[:200], error_msg)
            result = error_msg
        finally:
            if _active_spinner:
                _active_spinner.remove_sub(agent.name)
        return result

    skills_module.register(
        name=f"agent_{agent.name}",
        description=f"[子智能体] {agent.description}",
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": f"交给 {agent.name} 子智能体的任务描述",
                }
            },
            "required": ["task"],
        },
        func=_run_agent,
    )


def clear_plan():
    """清除规划状态，每轮对话结束后调用"""
    global _planner_used
    _planner_used = False
    reset_context()


def _auto_load():
    package = importlib.import_module("agents")
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        if module_name in ("base", "context", "router"):
            continue
        importlib.import_module(f"agents.{module_name}")


_auto_load()
