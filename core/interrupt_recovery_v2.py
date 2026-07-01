"""
流式中断恢复 v2 —— 上下文感知升级

增量改进：
1. 上下文指纹快照（ContextFingerprint）
2. 智能过期策略（指纹优先 + 超时兜底）
3. 注入消息去重（防止 token 堆积）
4. 分级用户反馈（ValidationResult）
5. 工具调用中断处理（切换为重新评估策略）

技术约束：Python 3.10+, 零外部依赖
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


# ──────────────────────────────────────────────
# 1. ContextFingerprint
# ──────────────────────────────────────────────

@dataclass
class ContextFingerprint:
    """对话上下文指纹，用于续接前验证上下文是否已变化。"""
    messages_hash: str = ""
    system_prompt_hash: str = ""
    model_id: str = ""

    @classmethod
    def capture(cls, messages: list, system_prompt: str, model_id: str) -> ContextFingerprint:
        """
        从当前对话状态生成指纹。

        >>> fp = ContextFingerprint.capture(
        ...     [{"role": "user", "content": "hello"}],
        ...     "You are helpful.",
        ...     "deepseek-v4"
        ... )
        >>> len(fp.messages_hash)
        16
        >>> len(fp.system_prompt_hash)
        16
        >>> fp.model_id
        'deepseek-v4'
        """
        last_5 = messages[-5:] if messages else []
        msg_text = "".join(
            m.get("content", "") or "" for m in last_5
        )
        messages_hash = hashlib.sha256(msg_text.encode()).hexdigest()[:16]
        system_prompt_hash = hashlib.sha256(
            (system_prompt or "").encode()
        ).hexdigest()[:16]
        return cls(
            messages_hash=messages_hash,
            system_prompt_hash=system_prompt_hash,
            model_id=model_id,
        )

    def match(self, other: ContextFingerprint) -> bool:
        """
        比对两个指纹是否一致。

        >>> fp1 = ContextFingerprint("abc123", "def456", "model-a")
        >>> fp2 = ContextFingerprint("abc123", "def456", "model-a")
        >>> fp1.match(fp2)
        True
        >>> fp3 = ContextFingerprint("abc123", "changed!", "model-a")
        >>> fp1.match(fp3)
        False
        """
        return (
            self.messages_hash == other.messages_hash
            and self.system_prompt_hash == other.system_prompt_hash
            and self.model_id == other.model_id
        )


# ──────────────────────────────────────────────
# 2. ValidationResult
# ──────────────────────────────────────────────

@dataclass
class ValidationResult:
    """验证结果，调用方据此决定阻断还是警告。"""
    valid: bool
    reason: str
    severity: str
    user_message: str
    can_force: bool


# ──────────────────────────────────────────────
# 3. ResumeResult
# ──────────────────────────────────────────────

@dataclass
class ResumeResult:
    """一站式恢复结果。"""
    messages: list = field(default_factory=list)
    validation: Optional[ValidationResult] = None
    injected: list = field(default_factory=list)


# ──────────────────────────────────────────────
# 4. InterruptState
# ──────────────────────────────────────────────

@dataclass
class InterruptState:
    """中断时保存的状态快照"""
    partial_reply: str = ""
    partial_reasoning: str = ""
    tool_calls_in_progress: list = field(default_factory=list)
    interrupted_at: float = 0.0
    model: str = ""
    turn_messages_snapshot: list = field(default_factory=list)
    fingerprint: Optional[ContextFingerprint] = None

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

        若有未完成工具调用 → 注入工具重试提示。
        否则 → 注入 partial_reply 续接指令。
        """
        msgs = []
        resume_id = str(uuid.uuid4())

        if self.tool_calls_in_progress:
            tool_names = [tc.get("name", "unknown") for tc in self.tool_calls_in_progress]
            msgs.append({
                "role": "assistant",
                "content": "（工具调用被中断，未产生有效输出）",
                "metadata": {"_resume_injected": True, "_resume_id": resume_id},
            })
            msgs.append({
                "role": "user",
                "content": (
                    f"工具 [{', '.join(tool_names)}] 的调用在执行过程中被中断，"
                    "未获得结果。请重新评估当前需求，决定是否需要重新调用这些工具。"
                ),
                "metadata": {"_resume_injected": True, "_resume_id": resume_id},
            })
        elif self.partial_reply:
            msgs.append({
                "role": "assistant",
                "content": self.partial_reply,
                "metadata": {"_resume_injected": True, "_resume_id": resume_id},
            })
            msgs.append({
                "role": "user",
                "content": (
                    "[续接指令] 你的回复在以下位置被中断，请从断点处继续完成回答，"
                    "不要重复已经说过的内容：\n"
                    f"...{self.partial_reply[-100:]}"
                ),
                "metadata": {"_resume_injected": True, "_resume_id": resume_id},
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


# ──────────────────────────────────────────────
# 5. InterruptRecovery 类
# ──────────────────────────────────────────────

class InterruptRecovery:
    """
    中断恢复管理器（v2）。

    增强功能：
    - 上下文指纹验证
    - 智能过期策略
    - 注入消息去重
    - 分级用户反馈
    - 工具调用中断处理

    线程安全。
    """

    def __init__(self, ttl_seconds: float = 600.0):
        self._lock = threading.Lock()
        self._state: Optional[InterruptState] = None
        self._accumulating = False
        self._current_partial = ""
        self._current_reasoning = ""
        self._current_tools: list = []
        self._current_model = ""
        self._ttl_seconds = ttl_seconds

    def start_accumulating(self, model: str = ""):
        """开始累积流式输出（每轮对话开始时调用）"""
        with self._lock:
            self._accumulating = True
            self._current_partial = ""
            self._current_reasoning = ""
            self._current_tools = []
            self._current_model = model

    def accumulate_text(self, text: str):
        """累积文本片段（签名不变）"""
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

    def save_on_interrupt(
        self,
        messages_snapshot: list = None,
        pending_tool_calls: list | None = None,
    ) -> Optional[InterruptState]:
        """
        中断时保存当前状态。

        Args:
            messages_snapshot: 中断时的消息列表（用于生成指纹）
            pending_tool_calls: 显式传入的未完成工具调用列表（可选，向后兼容）

        Returns:
            保存的 InterruptState，无内容时返回 None。
        """
        with self._lock:
            self._accumulating = False

            tools = pending_tool_calls if pending_tool_calls is not None else list(self._current_tools)

            if not (self._current_partial or self._current_reasoning or tools):
                self._state = None
                return None

            fingerprint = None
            if messages_snapshot:
                system_msgs = [m for m in messages_snapshot if m.get("role") == "system"]
                system_prompt = "\n".join(m.get("content", "") or "" for m in system_msgs)
                fingerprint = ContextFingerprint.capture(
                    messages_snapshot, system_prompt, self._current_model
                )

            self._state = InterruptState(
                partial_reply=self._current_partial,
                partial_reasoning=self._current_reasoning,
                tool_calls_in_progress=tools,
                interrupted_at=time.time(),
                model=self._current_model,
                turn_messages_snapshot=messages_snapshot or [],
                fingerprint=fingerprint,
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
                if self._state.age_seconds < self._ttl_seconds:
                    return True
            return False

    def consume_state(self) -> Optional[InterruptState]:
        """取出并清除中断状态（恢复时调用）"""
        with self._lock:
            state = self._state
            self._state = None
            return state

    def validate_context(
        self,
        current_messages: list,
        system_prompt: str,
        model_id: str,
    ) -> ValidationResult:
        """
        验证当前上下文与中断时是否一致。

        返回 ValidationResult，调用方据此决定是否续接。

        >>> recovery = InterruptRecovery(ttl_seconds=600.0)
        >>> recovery._state = InterruptState(
        ...     partial_reply="hello world",
        ...     interrupted_at=time.time(),
        ...     model="deepseek-v4",
        ...     fingerprint=ContextFingerprint.capture(
        ...         [{"role": "user", "content": "hi"}],
        ...         "You are helpful.", "deepseek-v4"
        ...     ),
        ... )
        >>> result = recovery.validate_context(
        ...     [{"role": "user", "content": "hi"}],
        ...     "You are helpful.", "deepseek-v4"
        ... )
        >>> result.valid
        True
        >>> result.severity
        'none'
        """
        state = self._state
        if not state or not state.fingerprint:
            return ValidationResult(
                valid=True, reason="ok", severity="none",
                user_message="", can_force=True,
            )

        saved_fp = state.fingerprint
        current_fp = ContextFingerprint.capture(current_messages, system_prompt, model_id)

        if saved_fp.model_id != current_fp.model_id:
            return ValidationResult(
                valid=False,
                reason="model_switched",
                severity="error",
                user_message=(
                    f"模型已切换（{saved_fp.model_id} → {current_fp.model_id}），"
                    "中断内容不适用于当前模型，无法续接。"
                ),
                can_force=False,
            )

        if (saved_fp.messages_hash != current_fp.messages_hash
                or saved_fp.system_prompt_hash != current_fp.system_prompt_hash):
            return ValidationResult(
                valid=False,
                reason="context_changed",
                severity="error",
                user_message=(
                    "对话上下文已发生变化，续接可能产生不连贯内容。"
                    "如需强制续接请使用 /resume --force"
                ),
                can_force=True,
            )

        if state.age_seconds > self._ttl_seconds:
            minutes = state.age_seconds / 60
            return ValidationResult(
                valid=True,
                reason="timeout",
                severity="warn",
                user_message=f"中断已超过 {minutes:.0f} 分钟，内容可能已过时。仍将尝试续接。",
                can_force=True,
            )

        return ValidationResult(
            valid=True, reason="ok", severity="none",
            user_message="", can_force=True,
        )

    def _strip_resume_injected(self, messages: list) -> list:
        """移除 messages 末尾所有带 _resume_injected 标记的消息。"""
        result = list(messages)
        while result:
            metadata = result[-1].get("metadata")
            if isinstance(metadata, dict) and metadata.get("_resume_injected"):
                result.pop()
            else:
                break
        return result

    def resume(
        self,
        messages: list,
        system_prompt: str,
        model_id: str,
        force: bool = False,
    ) -> ResumeResult:
        """
        一站式恢复：验证 + 去重 + 构建注入消息。

        Args:
            messages: 当前消息列表
            system_prompt: 当前系统提示
            model_id: 当前模型 ID
            force: 是否强制续接（跳过指纹检查，超时警告仍保留）

        Returns:
            ResumeResult 包含处理后的 messages、验证结果、注入的消息。

        >>> recovery = InterruptRecovery(ttl_seconds=600.0)
        >>> msgs = [{"role": "user", "content": "tell me a story"}]
        >>> recovery._state = InterruptState(
        ...     partial_reply="Once upon a time",
        ...     interrupted_at=time.time(),
        ...     model="deepseek-v4",
        ...     fingerprint=ContextFingerprint.capture(msgs, "system", "deepseek-v4"),
        ... )
        >>> result = recovery.resume(msgs, "system", "deepseek-v4")
        >>> result.validation.valid
        True
        >>> len(result.injected) == 2
        True
        >>> result.injected[0]["role"]
        'assistant'
        """
        validation = self.validate_context(messages, system_prompt, model_id)

        if not validation.valid and not force:
            return ResumeResult(
                messages=list(messages),
                validation=validation,
                injected=[],
            )

        if not validation.valid and force and not validation.can_force:
            return ResumeResult(
                messages=list(messages),
                validation=validation,
                injected=[],
            )

        state = self.consume_state()
        if not state or not state.has_content:
            return ResumeResult(
                messages=list(messages),
                validation=ValidationResult(
                    valid=True, reason="ok", severity="none",
                    user_message="", can_force=True,
                ),
                injected=[],
            )

        cleaned = self._strip_resume_injected(messages)
        injected = state.build_resume_messages()
        final_messages = cleaned + injected

        if force and not validation.valid:
            validation = ValidationResult(
                valid=True,
                reason=validation.reason,
                severity="warn",
                user_message=validation.user_message + "（已强制续接）",
                can_force=True,
            )

        return ResumeResult(
            messages=final_messages,
            validation=validation,
            injected=injected,
        )

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


# ──────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────

_recovery = InterruptRecovery()


def get_recovery() -> InterruptRecovery:
    return _recovery


# ──────────────────────────────────────────────
# Doctests
# ──────────────────────────────────────────────

def _run_doctests():
    """
    覆盖场景：

    1. 指纹匹配 + 未超时 → 正常续接

    >>> recovery = InterruptRecovery(ttl_seconds=600.0)
    >>> msgs = [{"role": "user", "content": "写一首诗"}]
    >>> recovery.start_accumulating(model="deepseek-v4")
    >>> recovery.accumulate_text("春风又绿江南")
    >>> recovery.save_on_interrupt(messages_snapshot=msgs)  # doctest: +ELLIPSIS
    InterruptState(partial_reply='春风又绿江南', ...)
    >>> result = recovery.resume(msgs, "", "deepseek-v4")
    >>> result.validation.valid
    True
    >>> result.validation.reason
    'ok'
    >>> "春风又绿江南" in result.injected[0]["content"]
    True

    2. 指纹不匹配 → 拒绝 + error 文案

    >>> recovery2 = InterruptRecovery(ttl_seconds=600.0)
    >>> msgs_old = [{"role": "user", "content": "old context"}]
    >>> msgs_new = [{"role": "user", "content": "new context"}]
    >>> recovery2.start_accumulating(model="deepseek-v4")
    >>> recovery2.accumulate_text("partial output")
    >>> recovery2.save_on_interrupt(messages_snapshot=msgs_old)  # doctest: +ELLIPSIS
    InterruptState(...)
    >>> result2 = recovery2.resume(msgs_new, "", "deepseek-v4")
    >>> result2.validation.valid
    False
    >>> result2.validation.reason
    'context_changed'
    >>> result2.validation.severity
    'error'
    >>> "/resume --force" in result2.validation.user_message
    True
    >>> result2.injected
    []

    3. 指纹匹配 + 已超时 → 允许 + warn 文案

    >>> recovery3 = InterruptRecovery(ttl_seconds=60.0)
    >>> msgs3 = [{"role": "user", "content": "hello"}]
    >>> fp3 = ContextFingerprint.capture(msgs3, "sys", "model-x")
    >>> recovery3._state = InterruptState(
    ...     partial_reply="some text",
    ...     interrupted_at=time.time() - 120,
    ...     model="model-x",
    ...     fingerprint=fp3,
    ... )
    >>> result3 = recovery3.resume(msgs3, "sys", "model-x")
    >>> result3.validation.valid
    True
    >>> result3.validation.reason
    'timeout'
    >>> result3.validation.severity
    'warn'
    >>> "过时" in result3.validation.user_message
    True

    4. force=True 强制续接

    >>> recovery4 = InterruptRecovery(ttl_seconds=600.0)
    >>> msgs_a = [{"role": "user", "content": "aaa"}]
    >>> msgs_b = [{"role": "user", "content": "bbb"}]
    >>> recovery4.start_accumulating(model="deepseek-v4")
    >>> recovery4.accumulate_text("forced text")
    >>> recovery4.save_on_interrupt(messages_snapshot=msgs_a)  # doctest: +ELLIPSIS
    InterruptState(...)
    >>> result4_no_force = recovery4.resume(msgs_b, "", "deepseek-v4")
    >>> result4_no_force.validation.valid
    False
    >>> recovery4.start_accumulating(model="deepseek-v4")
    >>> recovery4.accumulate_text("forced text")
    >>> recovery4.save_on_interrupt(messages_snapshot=msgs_a)  # doctest: +ELLIPSIS
    InterruptState(...)
    >>> result4_force = recovery4.resume(msgs_b, "", "deepseek-v4", force=True)
    >>> result4_force.validation.valid
    True
    >>> len(result4_force.injected) == 2
    True

    5. 工具调用中断 → 注入工具提示而非 partial_reply

    >>> recovery5 = InterruptRecovery(ttl_seconds=600.0)
    >>> msgs5 = [{"role": "user", "content": "search for info"}]
    >>> recovery5.start_accumulating(model="deepseek-v4")
    >>> recovery5.accumulate_text("")
    >>> recovery5.save_on_interrupt(
    ...     messages_snapshot=msgs5,
    ...     pending_tool_calls=[{"name": "web_search"}, {"name": "read_file"}],
    ... )  # doctest: +ELLIPSIS
    InterruptState(...)
    >>> result5 = recovery5.resume(msgs5, "", "deepseek-v4")
    >>> result5.validation.valid
    True
    >>> "工具调用被中断" in result5.injected[0]["content"]
    True
    >>> "web_search" in result5.injected[1]["content"]
    True
    >>> "read_file" in result5.injected[1]["content"]
    True

    6. 反复中断→续接 → 验证旧注入消息被清除

    >>> recovery6 = InterruptRecovery(ttl_seconds=600.0)
    >>> msgs6 = [{"role": "user", "content": "tell me"}]
    >>> recovery6.start_accumulating(model="m1")
    >>> recovery6.accumulate_text("first partial")
    >>> recovery6.save_on_interrupt(messages_snapshot=msgs6)  # doctest: +ELLIPSIS
    InterruptState(...)
    >>> result6a = recovery6.resume(msgs6, "", "m1")
    >>> len(result6a.injected)
    2
    >>> injected_msgs = result6a.messages
    >>> has_marker = any(
    ...     m.get("metadata", {}).get("_resume_injected")
    ...     for m in injected_msgs
    ... )
    >>> has_marker
    True
    >>> recovery6.start_accumulating(model="m1")
    >>> recovery6.accumulate_text("second partial")
    >>> recovery6.save_on_interrupt(messages_snapshot=injected_msgs)  # doctest: +ELLIPSIS
    InterruptState(...)
    >>> result6b = recovery6.resume(injected_msgs, "", "m1")
    >>> old_injected = [
    ...     m for m in result6b.messages
    ...     if m.get("metadata", {}).get("_resume_injected")
    ...     and "first partial" in m.get("content", "")
    ... ]
    >>> len(old_injected)
    0
    >>> new_injected = [
    ...     m for m in result6b.messages
    ...     if m.get("metadata", {}).get("_resume_injected")
    ...     and "second partial" in m.get("content", "")
    ... ]
    >>> len(new_injected) > 0
    True
    """
    pass


if __name__ == "__main__":
    import doctest
    doctest.testmod(verbose=True)
