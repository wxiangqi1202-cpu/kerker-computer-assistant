"""
执行上下文 —— Agent 间共享的工作记忆

核心职责：
1. 保存 planner 的规划结果，注入后续 agent 的 task context
2. 记录每个 agent 的执行摘要，供后续 agent 参考
3. 管理步骤 → agent 的绑定关系
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field


@dataclass
class PlanStep:
    """规划中的一个步骤"""
    step: str
    agent: str = ""
    status: str = "pending"
    result_summary: str = ""


class AgentContext:
    """
    单轮对话的执行上下文，每轮 clear_plan 时重置。
    线程安全，供 spinner 线程和 asyncio 线程共用。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._plan_steps: list[PlanStep] = []
        self._memory: list[dict] = []
        self._original_task: str = ""

    @property
    def has_plan(self):
        with self._lock:
            return len(self._plan_steps) > 0

    @property
    def plan_steps(self):
        with self._lock:
            return list(self._plan_steps)

    @property
    def original_task(self):
        with self._lock:
            return self._original_task

    def set_original_task(self, task):
        with self._lock:
            self._original_task = task

    def set_plan(self, steps):
        """
        从 planner 返回的结构化数据设置规划。
        steps: [{"step": "...", "agent": "..."}, ...]
        """
        with self._lock:
            self._plan_steps = [
                PlanStep(
                    step=s.get("step", ""),
                    agent=s.get("agent", ""),
                )
                for s in steps if s.get("step")
            ]

    def get_step_names(self):
        with self._lock:
            return [s.step for s in self._plan_steps]

    def advance_step(self, agent_name=""):
        """
        将下一个 pending 步骤标记为 running。
        如果有 agent 绑定，优先匹配对应 agent 的步骤。
        返回匹配到的 PlanStep，或 None。
        """
        with self._lock:
            if agent_name:
                for s in self._plan_steps:
                    if s.status == "pending" and s.agent == agent_name:
                        s.status = "running"
                        return s
            for s in self._plan_steps:
                if s.status == "pending":
                    s.status = "running"
                    return s
            return None

    def complete_step(self, step_name, summary=""):
        with self._lock:
            for s in self._plan_steps:
                if s.step == step_name:
                    s.status = "done"
                    s.result_summary = summary
                    return

    def fail_step(self, step_name, error=""):
        with self._lock:
            for s in self._plan_steps:
                if s.step == step_name:
                    s.status = "error"
                    s.result_summary = error
                    return

    def add_memory(self, agent_name, task, result_summary):
        """记录一条 agent 执行记忆"""
        with self._lock:
            self._memory.append({
                "agent": agent_name,
                "task": task[:200],
                "summary": result_summary[:500],
            })

    def build_context_prompt(self, agent_name=""):
        """
        为即将执行的 agent 构建上下文注入文本。
        包含：原始任务 → 当前规划 → 已完成步骤摘要。
        """
        with self._lock:
            parts = []

            if self._original_task:
                parts.append(f"[原始用户任务] {self._original_task}")

            if self._plan_steps:
                plan_lines = []
                for i, s in enumerate(self._plan_steps, 1):
                    status_icon = {"pending": "○", "running": "◎", "done": "●", "error": "✗"}.get(s.status, "?")
                    agent_hint = f" ({s.agent})" if s.agent else ""
                    summary_hint = f" → {s.result_summary}" if s.result_summary else ""
                    plan_lines.append(f"  {status_icon} {i}. {s.step}{agent_hint}{summary_hint}")
                parts.append("[执行规划]\n" + "\n".join(plan_lines))

            if self._memory:
                mem_lines = []
                for m in self._memory[-5:]:
                    mem_lines.append(f"  [{m['agent']}] {m['summary']}")
                parts.append("[已完成的工作]\n" + "\n".join(mem_lines))

            return "\n\n".join(parts) if parts else ""

    def clear(self):
        with self._lock:
            self._plan_steps.clear()
            self._memory.clear()
            self._original_task = ""

    def to_taskboard_items(self):
        """返回供 taskboard 显示的列表"""
        with self._lock:
            return [(s.step, s.status) for s in self._plan_steps]


_active_context = AgentContext()


def get_context():
    return _active_context


def reset_context():
    _active_context.clear()
