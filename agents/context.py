"""
执行上下文 —— 已废弃，统一委托给 ProgressTracker

[DEPRECATED] 此模块保留仅为向后兼容。
所有状态管理已统一到 core.progress.ProgressTracker。
新代码请直接使用 `from core.progress import get_tracker`。
"""

from __future__ import annotations

import warnings
from core.progress import get_tracker


class AgentContext:
    """
    [DEPRECATED] 兼容层 —— 所有方法委托给 ProgressTracker。
    保留此类仅为不破坏可能存在的外部引用。
    """

    def __init__(self):
        pass

    @property
    def _tracker(self):
        return get_tracker()

    @property
    def has_plan(self):
        return self._tracker.has_plan

    @property
    def plan_steps(self):
        return self._tracker.plan_steps

    @property
    def original_task(self):
        return self._tracker.original_task

    def set_original_task(self, task):
        self._tracker.set_original_task(task)

    def set_plan(self, steps):
        self._tracker.set_plan(steps)

    def get_step_names(self):
        return self._tracker.get_step_names()

    def advance_step(self, agent_name=""):
        return self._tracker.agent_start(agent_name)

    def complete_step(self, step_name, summary=""):
        self._tracker.agent_done(step_name, summary=summary)

    def fail_step(self, step_name, error=""):
        self._tracker.agent_error(step_name, error=error)

    def add_memory(self, agent_name, task, result_summary):
        self._tracker.add_memory(agent_name, task, result_summary)

    def build_context_prompt(self, agent_name=""):
        return self._tracker.build_context_prompt(agent_name=agent_name)

    def clear(self):
        self._tracker.reset()

    def to_taskboard_items(self):
        return self._tracker.get_snapshot()


_active_context = AgentContext()


def get_context():
    warnings.warn(
        "get_context() 已废弃，请使用 from core.progress import get_tracker",
        DeprecationWarning,
        stacklevel=2,
    )
    return _active_context


def reset_context():
    warnings.warn(
        "reset_context() 已废弃，请使用 get_tracker().reset()",
        DeprecationWarning,
        stacklevel=2,
    )
    _active_context.clear()
