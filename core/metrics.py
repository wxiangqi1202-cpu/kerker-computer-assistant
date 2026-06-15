"""
可观测性模块 —— 结构化 metrics 收集

记录每轮对话的关键指标：
- 延迟（首 token、总耗时）
- Token 消耗（prompt/completion）
- 工具调用统计（次数、耗时、成功率）
- Agent 调度统计

数据存储在内存中，可通过 /metrics 命令查看。
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional


@dataclass
class TurnMetrics:
    """单轮对话的指标"""
    turn_id: int = 0
    model: str = ""
    start_time: float = 0.0
    first_token_time: float = 0.0
    end_time: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls: list = field(default_factory=list)
    agent_calls: list = field(default_factory=list)
    rounds: int = 0
    error: str = ""

    @property
    def latency_ms(self) -> float:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0

    @property
    def ttft_ms(self) -> float:
        """Time to first token"""
        if self.first_token_time and self.start_time:
            return (self.first_token_time - self.start_time) * 1000
        return 0.0

    @property
    def tool_count(self) -> int:
        return len(self.tool_calls)

    @property
    def agent_count(self) -> int:
        return len(self.agent_calls)


@dataclass
class ToolCallRecord:
    """工具调用记录"""
    name: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    success: bool = True
    retries: int = 0

    @property
    def duration_ms(self) -> float:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0


class MetricsCollector:
    """
    Metrics 收集器，线程安全。
    保留最近 100 轮对话的指标，供调试和优化参考。
    """

    MAX_HISTORY = 100

    def __init__(self):
        self._lock = threading.Lock()
        self._turns: list[TurnMetrics] = []
        self._current: Optional[TurnMetrics] = None
        self._turn_counter = 0
        self._session_start = time.time()
        self._total_tokens_used = 0
        self._tool_stats: dict = defaultdict(
            lambda: {"calls": 0, "errors": 0, "total_ms": 0.0}
        )

    def start_turn(self, model: str = ""):
        """开始记录新一轮对话"""
        with self._lock:
            self._turn_counter += 1
            self._current = TurnMetrics(
                turn_id=self._turn_counter,
                model=model,
                start_time=time.time(),
            )

    def record_first_token(self):
        """记录首 token 到达时间"""
        with self._lock:
            if self._current and not self._current.first_token_time:
                self._current.first_token_time = time.time()

    def record_usage(self, usage: dict):
        """记录 token 使用量"""
        with self._lock:
            if not self._current:
                return
            self._current.prompt_tokens += usage.get("prompt_tokens", 0)
            self._current.completion_tokens += usage.get("completion_tokens", 0)
            self._current.total_tokens += usage.get("total_tokens", 0)
            self._total_tokens_used += usage.get("total_tokens", 0)

    def record_round(self):
        """记录一个 tool-call 轮次"""
        with self._lock:
            if self._current:
                self._current.rounds += 1

    def record_tool_call(self, name: str, duration_ms: float, success: bool = True, retries: int = 0):
        """记录工具调用"""
        with self._lock:
            if self._current:
                self._current.tool_calls.append(ToolCallRecord(
                    name=name,
                    duration_ms=duration_ms,
                    success=success,
                    retries=retries,
                ))
            stats = self._tool_stats[name]
            stats["calls"] += 1
            if not success:
                stats["errors"] += 1
            stats["total_ms"] += duration_ms

    def record_agent_call(self, name: str, duration_ms: float, success: bool = True):
        """记录 agent 调用"""
        with self._lock:
            if self._current:
                self._current.agent_calls.append(ToolCallRecord(
                    name=name,
                    duration_ms=duration_ms,
                    success=success,
                ))

    def end_turn(self, error: str = ""):
        """结束当前轮次记录"""
        with self._lock:
            if not self._current:
                return
            self._current.end_time = time.time()
            self._current.error = error
            self._turns.append(self._current)
            if len(self._turns) > self.MAX_HISTORY:
                self._turns = self._turns[-self.MAX_HISTORY:]
            self._current = None

    def get_summary(self) -> dict:
        """获取汇总统计"""
        with self._lock:
            if not self._turns:
                return {"turns": 0, "message": "暂无数据"}

            total_turns = len(self._turns)
            avg_latency = sum(t.latency_ms for t in self._turns) / total_turns
            avg_ttft = sum(t.ttft_ms for t in self._turns if t.ttft_ms > 0)
            ttft_count = sum(1 for t in self._turns if t.ttft_ms > 0)
            avg_ttft = avg_ttft / ttft_count if ttft_count else 0

            total_tool_calls = sum(t.tool_count for t in self._turns)
            total_agent_calls = sum(t.agent_count for t in self._turns)

            return {
                "turns": total_turns,
                "avg_latency_ms": round(avg_latency, 1),
                "avg_ttft_ms": round(avg_ttft, 1),
                "total_tokens": self._total_tokens_used,
                "total_tool_calls": total_tool_calls,
                "total_agent_calls": total_agent_calls,
                "session_duration_s": round(time.time() - self._session_start, 1),
                "tool_stats": dict(self._tool_stats),
            }

    def get_last_turn(self) -> Optional[TurnMetrics]:
        """获取最近一轮的指标"""
        with self._lock:
            return self._turns[-1] if self._turns else None

    def format_summary(self) -> str:
        """格式化输出统计摘要"""
        summary = self.get_summary()
        if summary.get("message"):
            return summary["message"]

        lines = [
            f"  会话统计 ({summary['session_duration_s']}s)",
            f"  ├─ 对话轮次: {summary['turns']}",
            f"  ├─ 平均延迟: {summary['avg_latency_ms']}ms",
            f"  ├─ 平均首 Token: {summary['avg_ttft_ms']}ms",
            f"  ├─ Token 总消耗: {summary['total_tokens']}",
            f"  ├─ 工具调用: {summary['total_tool_calls']} 次",
            f"  └─ Agent 调用: {summary['total_agent_calls']} 次",
        ]

        tool_stats = summary.get("tool_stats", {})
        if tool_stats:
            lines.append("")
            lines.append("  工具统计:")
            for name, stats in sorted(tool_stats.items(), key=lambda x: -x[1]["calls"]):
                avg_ms = stats["total_ms"] / stats["calls"] if stats["calls"] else 0
                err_rate = stats["errors"] / stats["calls"] * 100 if stats["calls"] else 0
                lines.append(
                    f"    {name}: {stats['calls']}次 "
                    f"avg={avg_ms:.0f}ms "
                    f"err={err_rate:.0f}%"
                )

        return "\n".join(lines)


_collector = MetricsCollector()


def get_metrics() -> MetricsCollector:
    return _collector
