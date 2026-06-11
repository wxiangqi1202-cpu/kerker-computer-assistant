"""
任务面板 —— 实时显示任务进度
与 spinner 共享终端空间。
running 呼吸灯，全部完成时收束聚焦动画。
"""

import threading
import time

_BREATH_COLORS = [
    238, 240, 242, 244, 247, 250, 252, 255,
    252, 250, 247, 244, 242, 240, 238, 236,
]

_T_HOLD = 0.5
_T_CONVERGE = 0.7
_T_FLASH = 0.25
_T_FADE = 0.35
_T_TOTAL = _T_HOLD + _T_CONVERGE + _T_FLASH + _T_FADE


class TaskBoard:
    def __init__(self):
        self._tasks = []
        self._lock = threading.Lock()
        self._visible = False
        self._all_done_at = 0
        self._finishing = False

    @property
    def is_finishing(self):
        with self._lock:
            return self._finishing

    def add_or_update(self, name, status):
        with self._lock:
            for task in self._tasks:
                if task["name"] == name:
                    task["status"] = status
                    self._visible = True
                    self._check_done()
                    return
            self._tasks.append({"name": name, "status": status})
            self._visible = True
            self._all_done_at = 0
            self._finishing = False

    def clear(self):
        with self._lock:
            self._tasks.clear()
            self._visible = False
            self._all_done_at = 0
            self._finishing = False

    def replace_all(self, items):
        with self._lock:
            self._tasks = []
            seen = set()
            for name, status in items:
                if name in seen:
                    continue
                seen.add(name)
                self._tasks.append({"name": name, "status": status})
            self._visible = bool(self._tasks)
            self._check_done()

    def advance_first_pending(self):
        with self._lock:
            for task in self._tasks:
                if task["status"] == "pending":
                    task["status"] = "running"
                    return task["name"]
        return None

    def _check_done(self):
        if not self._tasks:
            return
        if all(t["status"] in ("done", "error") for t in self._tasks):
            if self._all_done_at == 0:
                self._all_done_at = time.time()
                self._finishing = True
        else:
            self._all_done_at = 0
            self._finishing = False

    def get_lines(self, tick=0):
        with self._lock:
            if not self._visible or not self._tasks:
                return []
            if self._all_done_at > 0:
                return self._finish_anim(tick)
            return self._render(tick)

    def _render(self, tick):
        lines = []
        for t in self._tasks:
            s, n = t["status"], t["name"]
            if s == "running":
                c = _BREATH_COLORS[tick % len(_BREATH_COLORS)]
                lines.append(f"    \033[38;5;{c}m›\033[0m \033[97m{n}\033[0m")
            elif s == "done":
                lines.append(f"    \033[32m✓\033[0m \033[90m{n}\033[0m")
            elif s == "error":
                lines.append(f"    \033[31m✗\033[0m \033[90m{n}\033[0m")
            else:
                lines.append(f"    \033[90m·\033[0m \033[90m{n}\033[0m")
        return lines

    def _finish_anim(self, tick):
        elapsed = time.time() - self._all_done_at
        count = len(self._tasks)

        if elapsed < _T_HOLD:
            return self._render(tick)

        t2 = _T_HOLD + _T_CONVERGE
        if elapsed < t2:
            p = (elapsed - _T_HOLD) / _T_CONVERGE
            show = max(1, round(count * (1 - p)))
            lines = []
            for i in range(show):
                fade = int(232 + (1 - p) * 23)
                name = self._tasks[i]["name"]
                lines.append(f"    \033[38;5;{fade}m✓ {name}\033[0m")
            if show == 1:
                g = int(34 + p * 6)
                lines = [f"    \033[38;5;{g}m✓ {count} 项已完成\033[0m"]
            return lines

        t3 = t2 + _T_FLASH
        if elapsed < t3:
            fp = (elapsed - t2) / _T_FLASH
            if fp < 0.35:
                return [f"    \033[1;97m✓ {count} 项已完成\033[0m"]
            else:
                return [f"    \033[1;32m✓ {count} 项已完成\033[0m"]

        t4 = t3 + _T_FADE
        if elapsed < t4:
            fp = (elapsed - t3) / _T_FADE
            c = int(232 + (1 - fp) * 23)
            return [f"    \033[38;5;{c}m✓ {count} 项已完成\033[0m"]

        self._tasks.clear()
        self._visible = False
        self._all_done_at = 0
        self._finishing = False
        return []
