"""
计时器 —— 记录请求耗时
"""

import time


class Timer:
    """简单计时器，支持 with 语句"""

    def __init__(self):
        self._start = None
        self.elapsed = 0.0

    def start(self):
        self._start = time.time()

    def stop(self):
        if self._start is not None:
            self.elapsed = time.time() - self._start
            self._start = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def format(self):
        """返回格式化的耗时字符串"""
        if self.elapsed < 1:
            return f"{self.elapsed * 1000:.0f}ms"
        return f"{self.elapsed:.1f}s"
