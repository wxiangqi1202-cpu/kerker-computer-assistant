"""
任务面板 —— 纯渲染器，从 ProgressTracker 读取状态快照

设计原则：
1. TaskBoard 不持有业务状态，只负责渲染
2. 从 ProgressTracker 获取快照后渲染为 ANSI 行
3. 结束动画仅在 ProgressTracker.is_finished 时触发
4. 动画期间状态已锁定，不会被新数据打断
"""

import threading
import time

_BREATH_COLORS = [
    238, 240, 242, 244, 247, 250, 252, 255,
    252, 250, 247, 244, 242, 240, 238, 236,
]

_T_HOLD = 0.4
_T_CONVERGE = 0.6
_T_FLASH = 0.2
_T_FADE = 0.3
_T_TOTAL = _T_HOLD + _T_CONVERGE + _T_FLASH + _T_FADE


class TaskBoard:
    """
    任务面板渲染器。
    由 ProgressTracker 驱动，自身不管理业务状态。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._tracker = None
        self._finish_anim_start = 0.0
        self._finishing = False
        self._final_count = 0
        self._final_snapshot = []
        self._cleared = False
        self._cleared_generation = -1

    def set_tracker(self, tracker):
        self._tracker = tracker

    @property
    def is_finishing(self):
        with self._lock:
            return self._finishing

    @property
    def is_visible(self):
        if not self._tracker:
            return False
        with self._lock:
            if self._finishing:
                return True
        return self._tracker.is_visible

    def clear(self):
        """清除动画状态。记录当前 generation 用于检测 tracker reset。"""
        with self._lock:
            self._finish_anim_start = 0.0
            self._finishing = False
            self._final_count = 0
            self._final_snapshot = []
            self._cleared = True
            self._cleared_generation = self._tracker.generation if self._tracker else -1

    def get_lines(self, tick=0):
        if not self._tracker:
            return []

        with self._lock:
            if self._cleared:
                if self._tracker.generation != self._cleared_generation:
                    self._cleared = False
                else:
                    return []

            if self._finishing:
                return self._render_finish_anim(tick)

            if self._tracker.is_finished and not self._finishing:
                snapshot = self._tracker.get_snapshot()
                if snapshot:
                    self._finishing = True
                    self._finish_anim_start = time.time()
                    self._final_count = len(snapshot)
                    self._final_snapshot = snapshot
                    return self._render_finish_anim(tick)
                return []

        if not self._tracker.is_visible:
            return []

        snapshot = self._tracker.get_snapshot()
        if not snapshot:
            return []

        return self._render_steps(snapshot, tick)

    def _render_steps(self, snapshot, tick):
        """渲染步骤列表"""
        lines = []
        for name, status in snapshot:
            if status == "running":
                c = _BREATH_COLORS[tick % len(_BREATH_COLORS)]
                lines.append(f"    \033[38;5;{c}m›\033[0m \033[97m{name}\033[0m")
            elif status == "done":
                lines.append(f"    \033[32m✓\033[0m \033[90m{name}\033[0m")
            elif status == "error":
                lines.append(f"    \033[31m✗\033[0m \033[90m{name}\033[0m")
            else:
                lines.append(f"    \033[90m○\033[0m \033[90m{name}\033[0m")
        return lines

    def _render_finish_anim(self, tick):
        """结束收束动画：hold → converge → flash → fade"""
        elapsed = time.time() - self._finish_anim_start
        count = self._final_count
        snapshot = self._final_snapshot

        if count == 0:
            self._finishing = False
            return []

        if elapsed < _T_HOLD:
            return self._render_steps(snapshot, tick)

        t2 = _T_HOLD + _T_CONVERGE
        if elapsed < t2:
            progress = (elapsed - _T_HOLD) / _T_CONVERGE
            show = max(1, round(count * (1 - progress)))
            if show <= 1:
                g = int(34 + progress * 6)
                return [f"    \033[38;5;{g}m✓ {count} 项已完成\033[0m"]
            lines = []
            for i in range(show):
                fade = int(232 + (1 - progress) * 23)
                name = snapshot[i][0] if i < len(snapshot) else ""
                lines.append(f"    \033[38;5;{fade}m✓ {name}\033[0m")
            return lines

        t3 = t2 + _T_FLASH
        if elapsed < t3:
            fp = (elapsed - t2) / _T_FLASH
            color = "1;97m" if fp < 0.4 else "1;32m"
            return [f"    \033[{color}✓ {count} 项已完成\033[0m"]

        t4 = t3 + _T_FADE
        if elapsed < t4:
            fp = (elapsed - t3) / _T_FADE
            c = int(232 + (1 - fp) * 23)
            return [f"    \033[38;5;{c}m✓ {count} 项已完成\033[0m"]

        self._finishing = False
        self._final_snapshot = []
        return []
