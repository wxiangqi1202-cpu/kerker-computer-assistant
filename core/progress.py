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
        self._tool_name_counts: dict[str, int] = {}
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
        PLAN_MODE: 忽略（由 agent_start 管理步骤）
        TOOL_MODE/IDLE: 自动进入 TOOL_MODE，追加工具条目
        重复工具名自动添加序号（搜索, 搜索②, 搜索③）
        """
        with self._lock:
            if self._mode == ProgressMode.PLAN_MODE:
                return
            if self._mode == ProgressMode.IDLE:
                self._mode = ProgressMode.TOOL_MODE

            display_name = self._dedupe_tool_name(tool_name)
            step = ProgressStep(
                name=display_name,
                status=StepStatus.RUNNING,
                started_at=time.time(),
            )
            self._steps.append(step)
            if len(self._steps) >= 2:
                self._visible = True
            self._finished = False

    def _dedupe_tool_name(self, name: str) -> str:
        """为重复调用的工具生成唯一显示名"""
        count = self._tool_name_counts.get(name, 0) + 1
        self._tool_name_counts[name] = count
        if count == 1:
            return name
        circled = "②③④⑤⑥⑦⑧⑨⑩"
        idx = min(count - 2, len(circled) - 1)
        return f"{name}{circled[idx]}"

    def tool_done(self, tool_name: str):
        """
        工具执行完毕。
        PLAN_MODE: 忽略（由 agent_done 管理）
        TOOL_MODE: 标记最近一个 RUNNING 且名称匹配的工具为 DONE
        """
        with self._lock:
            if self._mode == ProgressMode.PLAN_MODE:
                return
            for step in reversed(self._steps):
                if step.status == StepStatus.RUNNING and (
                    step.name == tool_name or step.name.startswith(tool_name)
                ):
                    step.status = StepStatus.DONE
                    step.finished_at = time.time()
                    break

    def agent_start(self, agent_name: str):
        """子智能体开始执行。在 PLAN_MODE 下推进对应步骤。"""
        with self._lock:
            if self._mode == ProgressMode.PLAN_MODE:
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
        """子智能体失败。"""
        with self._lock:
            if self._mode == ProgressMode.PLAN_MODE:
                for step in self._steps:
                    if step.status == StepStatus.RUNNING and step.agent == agent_name:
                        step.status = StepStatus.ERROR
                        step.summary = error
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
            self._tool_name_counts = {}
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
