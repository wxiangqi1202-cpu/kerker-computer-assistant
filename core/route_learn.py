"""
路由学习模块 —— 记录路由决策和反馈，自适应调整阈值

设计原理：
1. 每次路由决策记录 (input_features, decision, outcome)
2. outcome 判定：
   - 正向：任务顺利完成（无中断、无重新路由）
   - 负向：用户中断(ESC)、命中 replan、DIRECT 后用户追问"帮我做XX"
3. 根据历史数据动态微调 complexity_threshold
4. 数据持久化到 ~/.kerker/route_history.json（保留最近 200 条）
"""

from __future__ import annotations

import os
import json
import time
import threading
from collections import defaultdict
from typing import Optional

from core import config


ROUTE_HISTORY_FILE = os.path.join(config.KERKER_HOME, "route_history.json")
MAX_HISTORY = 200


class RouteRecord:
    """单条路由记录"""
    def __init__(self, text_len, complexity, action, reason, timestamp=None):
        self.text_len = text_len
        self.complexity = complexity
        self.action = action
        self.reason = reason
        self.timestamp = timestamp or time.time()
        self.outcome = None
        self.interrupted = False
        self.replanned = False

    def to_dict(self):
        return {
            "text_len": self.text_len,
            "complexity": self.complexity,
            "action": self.action,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "outcome": self.outcome,
            "interrupted": self.interrupted,
            "replanned": self.replanned,
        }

    @classmethod
    def from_dict(cls, data):
        record = cls(
            text_len=data.get("text_len", 0),
            complexity=data.get("complexity", 0),
            action=data.get("action", ""),
            reason=data.get("reason", ""),
            timestamp=data.get("timestamp", 0),
        )
        record.outcome = data.get("outcome")
        record.interrupted = data.get("interrupted", False)
        record.replanned = data.get("replanned", False)
        return record


class RouteLearner:
    """
    路由学习器。跟踪路由决策的效果，动态调整阈值。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._history: list[RouteRecord] = []
        self._current: Optional[RouteRecord] = None
        self._complexity_bias = 0
        self._load()

    def _load(self):
        if os.path.isfile(ROUTE_HISTORY_FILE):
            try:
                with open(ROUTE_HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._history = [RouteRecord.from_dict(d) for d in data.get("records", [])]
                self._complexity_bias = data.get("complexity_bias", 0)
            except Exception:
                pass

    def _save(self):
        os.makedirs(config.KERKER_HOME, exist_ok=True)
        data = {
            "records": [r.to_dict() for r in self._history[-MAX_HISTORY:]],
            "complexity_bias": self._complexity_bias,
        }
        try:
            with open(ROUTE_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except OSError as err:
            import sys
            print(f"[kerker] 路由历史保存失败: {err}", file=sys.stderr)

    def record_decision(self, text_len, complexity, action, reason):
        """记录一次路由决策"""
        with self._lock:
            self._current = RouteRecord(text_len, complexity, action, reason)

    def record_outcome(self, success=True, interrupted=False, replanned=False):
        """记录本轮结果"""
        with self._lock:
            if not self._current:
                return
            self._current.outcome = "success" if success else "failure"
            self._current.interrupted = interrupted
            self._current.replanned = replanned
            self._history.append(self._current)
            if len(self._history) > MAX_HISTORY:
                self._history = self._history[-MAX_HISTORY:]
            self._update_bias()
            self._current = None
            self._save()

    def _update_bias(self):
        """
        根据最近的路由结果调整 complexity_bias:
        - PLAN 被中断(误触发) → bias +1（提高触发门槛）
        - DIRECT 后用户补充复杂指令(漏触发) → bias -1（降低触发门槛）
        - 范围限制在 [-2, +2]
        """
        recent = self._history[-20:]
        if not recent:
            return

        false_plan = sum(
            1 for r in recent
            if r.action == "plan" and r.interrupted and r.complexity <= 3
        )
        missed_plan = sum(
            1 for r in recent
            if r.action == "direct" and r.replanned
        )

        if false_plan > missed_plan + 1:
            self._complexity_bias = min(self._complexity_bias + 1, 2)
        elif missed_plan > false_plan + 1:
            self._complexity_bias = max(self._complexity_bias - 1, -2)

    @property
    def complexity_threshold_adjustment(self) -> int:
        """返回当前阈值偏移量（加到 complexity score 的判定门槛上）"""
        with self._lock:
            return self._complexity_bias

    def get_stats(self) -> dict:
        """统计信息"""
        with self._lock:
            if not self._history:
                return {"total": 0}
            total = len(self._history)
            by_action = defaultdict(int)
            by_outcome = defaultdict(int)
            for r in self._history:
                by_action[r.action] += 1
                if r.outcome:
                    by_outcome[r.outcome] += 1
            return {
                "total": total,
                "by_action": dict(by_action),
                "by_outcome": dict(by_outcome),
                "complexity_bias": self._complexity_bias,
            }


_learner = RouteLearner()


def get_route_learner() -> RouteLearner:
    return _learner
