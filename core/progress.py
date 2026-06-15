"""
统一进度追踪器 —— Plan/Tool/Agent 的唯一状态源

核心设计：
1. 两种模式: PLAN_MODE (planner 产出步骤) / TOOL_MODE (即时工具调用)
2. 所有状态变更通过 ProgressTracker API 发生
3. TaskBoard 只读取 ProgressTracker 的快照来渲染
4. 消除多处直接操作 TaskBoard 导致的状态冲突

状态机:
  IDLE → TOOL_MODE (首次工具调用) → IDLE (done 事件)
  IDLE → PLAN_MODE (planner 返回) → IDLE (done 事件)
"""

import threading
import time
from dataclasses import dataclass
from enum import Enum


class ProgressMode(Enum):
    IDLE = "idle"
    TOOL_MODE = "tool"
    PLAN_MODE = "plan"


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class ProgressStep:
    name: str
    status: StepStatus = StepStatus.PENDING
    agent: str = ""
    summary: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


class ProgressTracker:
    """
    统一进度追踪器。线程安全。
    所有 plan/tool/agent 进度通过此类管理。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._mode = ProgressMode.IDLE
        self._steps: list[ProgressStep] = []
        self._original_task: str = ""
        self._memory: list[dict] = []
        self._finished = False
        self._finish_time: float = 0.0
        self._visible = False
        self._generation: int = 0

    @property
    def mode(self):
        with self._lock:
            return self._mode

    @property
    def is_visible(self):
        with self._lock:
            return self._visible

    @property
    def is_finished(self):
        with self._lock:
            return self._finished

    @property
    def finish_time(self):
        with self._lock:
            return self._finish_time

    @property
    def has_plan(self):
        with self._lock:
            return self._mode == ProgressMode.PLAN_MODE

    @property
    def plan_steps(self):
        with self._lock:
            if self._mode == ProgressMode.PLAN_MODE:
                return list(self._steps)
            return []

    @property
    def original_task(self):
        with self._lock:
            return self._original_task

    def set_original_task(self, task: str):
        with self._lock:
            self._original_task = task

    def peek_next_pending(self) -> tuple:
        """
        预览下一个 pending 步骤（不修改状态）。
        返回 (step_name, agent_name) 或 (None, None)。
        用于预测性 prefetch。
        """
        with self._lock:
            if self._mode != ProgressMode.PLAN_MODE:
                return None, None
            for step in self._steps:
                if step.status == StepStatus.PENDING:
                    return step.name, step.agent
            return None, None

    def set_plan(self, steps: list[dict]):
        """
        从 planner 返回的结构设置计划步骤。
        steps: [{"step": "...", "agent": "..."}, ...]
        切换到 PLAN_MODE。
        """
        with self._lock:
            self._mode = ProgressMode.PLAN_MODE
            self._steps = []
            seen = set()
            for s in steps:
                name = s.get("step", "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                self._steps.append(ProgressStep(
                    name=name,
                    agent=s.get("agent", ""),
                ))
            self._visible = bool(self._steps)
            self._finished = False

    def tool_start(self, tool_name: str):
        """
        工具开始执行。
        PLAN_MODE: 忽略（由 plan step 管理展示）
        TOOL_MODE/IDLE: 仅切换模式，不展示（spinner 负责实时反馈）
        """
        with self._lock:
            if self._mode == ProgressMode.PLAN_MODE:
                return
            if self._mode == ProgressMode.IDLE:
                self._mode = ProgressMode.TOOL_MODE

    def tool_done(self, tool_name: str):
        """工具完成。无面板操作（spinner 负责反馈）。"""
        pass

    def agent_start(self, agent_name: str):
        """
        子智能体开始执行。在 PLAN_MODE 下推进对应步骤。
        如果 ensure_step_active 已经推进了匹配的步骤，直接返回它。
        """
        with self._lock:
            if self._mode == ProgressMode.PLAN_MODE:
                for step in self._steps:
                    if step.status == StepStatus.RUNNING and step.agent == agent_name:
                        return step.name
                for step in self._steps:
                    if step.status == StepStatus.RUNNING and step.agent == "":
                        step.agent = agent_name
                        return step.name
                for step in self._steps:
                    if step.status == StepStatus.PENDING and step.agent == agent_name:
                        step.status = StepStatus.RUNNING
                        step.started_at = time.time()
                        return step.name
                for step in self._steps:
                    if step.status == StepStatus.PENDING:
                        step.status = StepStatus.RUNNING
                        step.started_at = time.time()
                        return step.name
            return None

    def agent_done(self, agent_name: str, summary: str = ""):
        """子智能体完成。标记对应步骤为 DONE。"""
        with self._lock:
            if self._mode == ProgressMode.PLAN_MODE:
                for step in self._steps:
                    if step.status == StepStatus.RUNNING and step.agent == agent_name:
                        step.status = StepStatus.DONE
                        step.summary = summary
                        step.finished_at = time.time()
                        return
                for step in self._steps:
                    if step.status == StepStatus.RUNNING:
                        step.status = StepStatus.DONE
                        step.summary = summary
                        step.finished_at = time.time()
                        return

    def agent_error(self, agent_name: str, error: str = ""):
        """子智能体失败。标记步骤并记录错误次数。"""
        with self._lock:
            if self._mode == ProgressMode.PLAN_MODE:
                for step in self._steps:
                    if step.status == StepStatus.RUNNING and step.agent == agent_name:
                        step.status = StepStatus.ERROR
                        step.summary = error
                        step.finished_at = time.time()
                        return

    @property
    def error_count(self):
        """当前 plan 中失败步骤数"""
        with self._lock:
            return sum(1 for s in self._steps if s.status == StepStatus.ERROR)

    @property
    def needs_replan(self):
        """
        判断是否需要重新规划：
        - 连续 2 个步骤失败
        - 或超过 50% 步骤失败
        """
        with self._lock:
            if self._mode != ProgressMode.PLAN_MODE or not self._steps:
                return False
            errors = sum(1 for s in self._steps if s.status == StepStatus.ERROR)
            if errors >= 2:
                return True
            if len(self._steps) >= 3 and errors / len(self._steps) > 0.5:
                return True
            return False

    def advance_unbound_step(self):
        """
        推进下一个无 agent 绑定的 pending 步骤为 running。
        用于主模型通过普通工具调用执行 plan 步骤时。
        如果没有无绑定步骤，则推进任意 pending 步骤。
        """
        with self._lock:
            if self._mode != ProgressMode.PLAN_MODE:
                return None
            has_running = any(s.status == StepStatus.RUNNING for s in self._steps)
            if has_running:
                return None
            for step in self._steps:
                if step.status == StepStatus.PENDING and step.agent == "":
                    step.status = StepStatus.RUNNING
                    step.started_at = time.time()
                    return step.name
            for step in self._steps:
                if step.status == StepStatus.PENDING:
                    step.status = StepStatus.RUNNING
                    step.started_at = time.time()
                    return step.name
            return None

    def ensure_step_active(self):
        """
        确保面板实时反映进度：
        1. 如果有 pending 步骤且无 running → 推进一个
        2. 如果所有步骤已 done 但未 finished → 追加 "生成总结" 步骤
        每轮 API 调用开始时调用。
        """
        with self._lock:
            if self._mode != ProgressMode.PLAN_MODE:
                return
            has_running = any(s.status == StepStatus.RUNNING for s in self._steps)
            if has_running:
                return
            has_pending = any(s.status == StepStatus.PENDING for s in self._steps)
            if has_pending:
                for step in self._steps:
                    if step.status == StepStatus.PENDING:
                        step.status = StepStatus.RUNNING
                        step.started_at = time.time()
                        return
            if self._steps and not self._finished:
                all_done = all(s.status in (StepStatus.DONE, StepStatus.ERROR) for s in self._steps)
                if all_done:
                    self._steps.append(ProgressStep(
                        name="生成总结",
                        status=StepStatus.RUNNING,
                        started_at=time.time(),
                    ))

    def complete_unbound_step(self):
        """
        完成当前 running 的无绑定步骤。
        用于一轮非 agent 工具调用结束后。
        """
        with self._lock:
            if self._mode != ProgressMode.PLAN_MODE:
                return
            for step in self._steps:
                if step.status == StepStatus.RUNNING and step.agent == "":
                    step.status = StepStatus.DONE
                    step.finished_at = time.time()
                    return
            for step in self._steps:
                if step.status == StepStatus.RUNNING:
                    step.status = StepStatus.DONE
                    step.finished_at = time.time()
                    return

    def finish_all(self):
        """所有工作完成，标记剩余步骤并触发结束。无步骤时为空操作。"""
        with self._lock:
            if not self._steps:
                return
            for step in self._steps:
                if step.status in (StepStatus.PENDING, StepStatus.RUNNING):
                    step.status = StepStatus.DONE
                    step.finished_at = time.time()
            self._finished = True
            self._finish_time = time.time()

    def pause_on_interrupt(self):
        """
        中断时保留 plan 状态。
        将 running 步骤回退为 pending，以便下次消息继续执行。
        递增 generation 以通知 taskboard 重新渲染。
        非 PLAN_MODE 时直接 reset。
        """
        with self._lock:
            if self._mode != ProgressMode.PLAN_MODE:
                self._mode = ProgressMode.IDLE
                self._steps = []
                self._visible = False
                self._finished = False
                self._generation += 1
                return
            for step in self._steps:
                if step.status == StepStatus.RUNNING:
                    step.status = StepStatus.PENDING
                    step.started_at = 0.0
            if self._steps and self._steps[-1].name == "生成总结":
                self._steps.pop()
            self._finished = False
            self._visible = bool(self._steps)
            self._generation += 1

    def reset(self):
        """重置所有状态（新一轮对话时调用）"""
        with self._lock:
            self._mode = ProgressMode.IDLE
            self._steps = []
            self._original_task = ""
            self._memory = []
            self._finished = False
            self._finish_time = 0.0
            self._visible = False
            self._generation += 1

    @property
    def generation(self):
        """递增计数器，每次 reset 加一。用于检测状态已被重置。"""
        with self._lock:
            return self._generation

    def add_memory(self, agent_name: str, task: str, summary: str):
        with self._lock:
            self._memory.append({
                "agent": agent_name,
                "task": task[:200],
                "summary": summary[:500],
            })

    def get_snapshot(self) -> list[tuple[str, str]]:
        """获取当前所有步骤的渲染快照 [(name, status_str), ...]"""
        with self._lock:
            return [(s.name, s.status.value) for s in self._steps]

    def get_step_names(self):
        with self._lock:
            return [s.name for s in self._steps]

    def build_context_prompt(self, agent_name: str = "") -> str:
        """为子智能体构建上下文注入"""
        with self._lock:
            parts = []
            if self._original_task:
                parts.append(f"[原始用户任务] {self._original_task}")
            if self._steps and self._mode == ProgressMode.PLAN_MODE:
                plan_lines = []
                for i, s in enumerate(self._steps, 1):
                    icon = {"pending": "○", "running": "◎", "done": "●", "error": "✗"}.get(s.status.value, "?")
                    agent_hint = f" ({s.agent})" if s.agent else ""
                    summary_hint = f" → {s.summary}" if s.summary else ""
                    plan_lines.append(f"  {icon} {i}. {s.name}{agent_hint}{summary_hint}")
                parts.append("[执行规划]\n" + "\n".join(plan_lines))
            if self._memory:
                mem_lines = [f"  [{m['agent']}] {m['summary']}" for m in self._memory[-5:]]
                parts.append("[已完成的工作]\n" + "\n".join(mem_lines))
            return "\n\n".join(parts) if parts else ""


_tracker = ProgressTracker()


def get_tracker() -> ProgressTracker:
    return _tracker
