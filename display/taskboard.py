"""
任务面板 —— 实时显示任务规划和执行进度
与 spinner 共享终端空间，在 spinner 下方显示任务列表。
running 状态使用呼吸灯效果。
"""

import threading

_BREATH_COLORS = [
    238, 240, 242, 244, 247, 250, 252, 255,
    252, 250, 247, 244, 242, 240, 238, 236,
]

STATUS_ICONS = {
    "pending": "·",
    "done": "✓",
    "error": "✗",
}


class TaskBoard:
    """线程安全的任务面板，由 spinner 线程负责渲染"""

    def __init__(self):
        self._tasks = []
        self._lock = threading.Lock()
        self._visible = False

    def add_or_update(self, name, status):
        with self._lock:
            for task in self._tasks:
                if task["name"] == name:
                    task["status"] = status
                    self._visible = True
                    return
            self._tasks.append({"name": name, "status": status})
            self._visible = True

    def update_task(self, name, status):
        with self._lock:
            for task in self._tasks:
                if task["name"] == name:
                    task["status"] = status
                    break

    def clear(self):
        with self._lock:
            self._tasks.clear()
            self._visible = False

    def advance_first_pending(self):
        with self._lock:
            for task in self._tasks:
                if task["status"] == "pending":
                    task["status"] = "running"
                    return task["name"]
        return None

    def get_lines(self, tick=0):
        """返回要渲染的行列表，由 spinner 调用。tick 用于驱动呼吸动画。"""
        with self._lock:
            if not self._visible or not self._tasks:
                return []
            lines = []
            for task in self._tasks:
                status = task["status"]
                name = task["name"]

                if status == "running":
                    color = _BREATH_COLORS[tick % len(_BREATH_COLORS)]
                    lines.append(
                        f"    \033[38;5;{color}m›\033[0m \033[97m{name}\033[0m"
                    )
                elif status == "done":
                    lines.append(f"    \033[32m✓\033[0m \033[90m{name}\033[0m")
                elif status == "error":
                    lines.append(f"    \033[31m✗\033[0m \033[90m{name}\033[0m")
                else:
                    lines.append(f"    \033[90m·\033[0m \033[90m{name}\033[0m")
            return lines
