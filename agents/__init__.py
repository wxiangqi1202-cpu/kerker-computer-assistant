"""
子智能体系统 v3 —— 注册表 + 自动路由 + ProgressTracker 统一进度

核心改进（v3）：
- 废弃 AgentContext 的直接 taskboard 操作
- 所有进度通过 ProgressTracker 统一管理
- planner 结果注入 ProgressTracker.set_plan()
- agent 执行结果通过 ProgressTracker.agent_done() 上报
- 消除 _sync_taskboard 导致的状态冲突
"""

import json
import importlib
import pkgutil

import skills as skills_module
from agents.base import SubAgent

_registry = {}
_active_spinner = None
_planner_used = False


def set_spinner(spinner):
    global _active_spinner
    _active_spinner = spinner


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
        if ch == '"':
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


def _register_as_skill(agent):
    def _on_status(text):
        if _active_spinner:
            _active_spinner.update_sub(agent.name, [text])

    async def _run_agent(task):
        global _planner_used
        from core.progress import get_tracker
        tracker = get_tracker()

        if agent.name == "planner" and _planner_used:
            return "规划已完成，请根据现有规划继续执行。"

        if _active_spinner:
            _active_spinner.update_sub(agent.name, [f"{agent.name} 工作中..."])

        if agent.name == "planner":
            tracker.set_original_task(task)
            _planner_used = True
        else:
            tracker.agent_start(agent.name)
            context_prompt = tracker.build_context_prompt(agent_name=agent.name)
            if context_prompt:
                task = f"{context_prompt}\n\n[当前任务] {task}"

        try:
            result = await agent.run(task, on_status=_on_status)

            if agent.name == "planner":
                steps = _parse_planner_result(result)
                if steps:
                    tracker.set_plan(steps)
            else:
                summary = _summarize_result(result)
                tracker.agent_done(agent.name, summary=summary)
                tracker.add_memory(agent.name, task[:200], summary)

        except Exception as err:
            error_msg = f"[{agent.name}] 执行失败: {str(err)[:150]}"

            if agent.name != "planner":
                tracker.agent_error(agent.name, error=str(err)[:100])

            tracker.add_memory(agent.name, task[:200], error_msg)
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
    from core.progress import get_tracker
    get_tracker().reset()


def _auto_load():
    package = importlib.import_module("agents")
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        if module_name in ("base", "context", "router"):
            continue
        importlib.import_module(f"agents.{module_name}")


_auto_load()
