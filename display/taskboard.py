"""
任务面板 —— 实时显示任务规划和执行进度
与 spinner 共享终端空间，在 spinner 下方显示任务列表。
"""

import threading

STATUS_ICONS = {
    "pending": "\033[90m○\033[0m",
    "running": "\033[36m◎\033[0m",
    "done": "\033[32m●\033[0m",
    "error": "\033[31m✗\033[0m",
}


class TaskBoard:
    """线程安全的任务面板，由 spinner 线程负责渲染"""

    def __init__(self):
        self._tasks = []
        self._lock = threading.Lock()
        self._visible = False

    def add_or_update(self, name, status):
        """添加或更新任务。name 已存在则更新状态，否则追加。"""
        with self._lock:
            for task in self._tasks:
                if task["name"] == name:
                    task["status"] = status
                    self._visible = True
                    return
            self._tasks.append({"name": name, "status": status})
            self._visible = True

    def update_task(self, name, status):
        """更新已存在任务的状态"""
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
        """将第一个 pending 任务标记为 running，返回其名称；无则返回 None"""
        with self._lock:
            for task in self._tasks:
                if task["status"] == "pending":
                    task["status"] = "running"
                    return task["name"]
        return None

    def get_lines(self):
        """返回要渲染的行列表，由 spinner 调用"""
        with self._lock:
            if not self._visible or not self._tasks:
                return []
            lines = []
            for task in self._tasks:
                icon = STATUS_ICONS.get(task["status"], STATUS_ICONS["pending"])
                name = task["name"]
                if task["status"] == "running":
                    lines.append(f"    {icon} \033[97m{name}\033[0m")
                else:
                    lines.append(f"    {icon} \033[90m{name}\033[0m")
            return lines
