"""
子智能体系统 —— 注册表 + 自动加载 + 注册为 skill + 任务面板
planner 返回的结构化任务列表会写入 taskboard 实时显示。
后续 agent 调度会自动匹配步骤并更新状态。
"""

import json
import importlib
import pkgutil

import skills as skills_module
from agents.base import SubAgent

_registry = {}
_active_spinner = None
_active_taskboard = None
_plan_steps = []


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


def _parse_planner_result(text):
    """从 planner 返回文本中解析 JSON 任务列表"""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            tasks = data.get("tasks", [])
            return [t.get("step", "") for t in tasks if t.get("step")]
    except Exception:
        pass
    return []


def match_plan_step(task_text):
    """当 agent 被调度时，匹配 planner 步骤并标记 running。返回步骤名。"""
    if not _plan_steps or not _active_taskboard:
        return None
    return _active_taskboard.advance_first_pending()


def complete_plan_step(step_name):
    """标记步骤为完成"""
    if _active_taskboard and step_name:
        _active_taskboard.add_or_update(step_name, "done")


def _register_as_skill(agent):
    def _on_status(text):
        if _active_spinner:
            _active_spinner.update_sub(agent.name, [text])

    async def _run_agent(task):
        global _plan_steps

        if _active_spinner:
            from display.spinner import AGENT_TIPS
            _active_spinner.update_sub(agent.name, AGENT_TIPS)

        matched_step = None
        if agent.name != "planner":
            matched_step = match_plan_step(task)
        else:
            if _active_taskboard:
                _active_taskboard.add_or_update("planner", "running")

        try:
            result = await agent.run(task, on_status=_on_status)

            if agent.name == "planner" and _active_taskboard:
                steps = _parse_planner_result(result)
                if steps:
                    _plan_steps = steps
                    _active_taskboard.clear()
                    for step in steps:
                        _active_taskboard.add_or_update(step, "pending")
                else:
                    _active_taskboard.add_or_update("planner", "done")

            if matched_step:
                complete_plan_step(matched_step)

        except Exception:
            if matched_step:
                _active_taskboard.add_or_update(matched_step, "error")
            elif agent.name == "planner" and _active_taskboard:
                _active_taskboard.add_or_update("planner", "error")
            raise
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
    global _plan_steps
    _plan_steps = []


def _auto_load():
    package = importlib.import_module("agents")
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        if module_name in ("base",):
            continue
        importlib.import_module(f"agents.{module_name}")


_auto_load()
