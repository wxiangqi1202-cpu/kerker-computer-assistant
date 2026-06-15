"""
流式中断恢复 —— 保存 partial response，支持 /resume 断点续接

工作原理：
1. 流式输出过程中，renderer 持续累积 partial_reply
2. 用户按 ESC 中断时，将当前 partial 状态保存到 InterruptState
3. 用户发送 /resume 或新消息时，从 InterruptState 恢复：
   - 将已收到的 partial reply 作为 assistant 消息追加到 messages
   - 注入续接指令让模型从断点继续
4. InterruptState 在成功完成一轮对话后自动清除

状态生命周期：
  stream_start → 持续更新 partial → ESC 中断 → 保存状态
  /resume → 恢复状态注入 messages → 继续执行 → 清除状态
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InterruptState:
    """中断时保存的状态快照"""
    partial_reply: str = ""
    partial_reasoning: str = ""
    tool_calls_in_progress: list = field(default_factory=list)
    interrupted_at: float = 0.0
    model: str = ""
    turn_messages_snapshot: list = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return bool(self.partial_reply or self.partial_reasoning or self.tool_calls_in_progress)

    @property
    def age_seconds(self) -> float:
        if self.interrupted_at:
            return time.time() - self.interrupted_at
        return 0.0

    def build_resume_messages(self) -> list:
        """
        构建恢复续接的消息序列。
        将 partial reply 作为 assistant 消息，然后追加续接指令。
        """
        msgs = []

        if self.partial_reply:
            msgs.append({
                "role": "assistant",
                "content": self.partial_reply,
            })
            msgs.append({
                "role": "user",
                "content": (
                    "[续接指令] 你的回复在以下位置被中断，请从断点处继续完成回答，"
                    "不要重复已经说过的内容：\n"
                    f"...{self.partial_reply[-100:]}"
                ),
            })
        elif self.tool_calls_in_progress:
            tool_names = [tc.get("name", "unknown") for tc in self.tool_calls_in_progress]
            msgs.append({
                "role": "user",
                "content": (
                    f"[续接指令] 之前执行被中断，工具 {', '.join(tool_names)} 的调用未完成。"
                    "请重新评估任务状态并继续执行。"
                ),
            })

        return msgs

    def format_preview(self) -> str:
        """格式化中断状态预览"""
        if not self.has_content:
            return "无中断状态"

        age = self.age_seconds
        if age < 60:
            age_str = f"{age:.0f}s 前"
        else:
            age_str = f"{age / 60:.1f}min 前"

        if self.partial_reply:
            preview = self.partial_reply[-60:].replace("\n", " ").strip()
            return f"中断于 {age_str}，已收到 {len(self.partial_reply)} 字: ...{preview}"
        elif self.tool_calls_in_progress:
            tool_names = [tc.get("name", "?") for tc in self.tool_calls_in_progress]
            return f"中断于 {age_str}，工具调用中: {', '.join(tool_names)}"
        else:
            return f"中断于 {age_str}，有推理内容但无文本输出"


class InterruptRecovery:
    """
    中断恢复管理器。线程安全。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state: Optional[InterruptState] = None
        self._accumulating = False
        self._current_partial = ""
        self._current_reasoning = ""
        self._current_tools = []
        self._current_model = ""

    def start_accumulating(self, model: str = ""):
        """开始累积流式输出（每轮对话开始时调用）"""
        with self._lock:
            self._accumulating = True
            self._current_partial = ""
            self._current_reasoning = ""
            self._current_tools = []
            self._current_model = model

    def accumulate_text(self, text: str):
        """累积文本片段"""
        with self._lock:
            if self._accumulating:
                self._current_partial += text

    def accumulate_reasoning(self, text: str):
        """累积推理内容"""
        with self._lock:
            if self._accumulating:
                self._current_reasoning += text

    def accumulate_tool_call(self, tool_info: dict):
        """记录工具调用"""
        with self._lock:
            if self._accumulating:
                self._current_tools.append(tool_info)

    def save_on_interrupt(self, messages_snapshot: list = None):
        """
        中断时保存当前状态。
        返回保存的 InterruptState。
        """
        with self._lock:
            self._accumulating = False
            if not (self._current_partial or self._current_reasoning or self._current_tools):
                self._state = None
                return None

            self._state = InterruptState(
                partial_reply=self._current_partial,
                partial_reasoning=self._current_reasoning,
                tool_calls_in_progress=list(self._current_tools),
                interrupted_at=time.time(),
                model=self._current_model,
                turn_messages_snapshot=messages_snapshot or [],
            )
            return self._state

    def get_state(self) -> Optional[InterruptState]:
        """获取保存的中断状态"""
        with self._lock:
            return self._state

    def has_state(self) -> bool:
        """是否有可恢复的中断状态"""
        with self._lock:
            if self._state and self._state.has_content:
                if self._state.age_seconds < 600:
                    return True
            return False

    def consume_state(self) -> Optional[InterruptState]:
        """取出并清除中断状态（恢复时调用）"""
        with self._lock:
            state = self._state
            self._state = None
            return state

    def clear(self):
        """清除所有状态（成功完成对话后调用）"""
        with self._lock:
            self._state = None
            self._accumulating = False
            self._current_partial = ""
            self._current_reasoning = ""
            self._current_tools = []

    def stop_accumulating(self):
        """正常结束时停止累积"""
        with self._lock:
            self._accumulating = False
            self._current_partial = ""
            self._current_reasoning = ""
            self._current_tools = []


_recovery = InterruptRecovery()


def get_recovery() -> InterruptRecovery:
    return _recovery
