"""
多行动态状态指示器 + ESC 中断 + 任务面板 + stdin 消费

线程安全设计（v2）：
- 状态更新通过 queue.Queue 单向传递给渲染线程
- 渲染线程持有自己的状态副本，无需跨线程锁读取
- 消除 ProgressTracker 的跨线程锁竞争
"""

import sys
import os
import tty
import termios
import select
import threading
import queue
import time
import random

from display import output as _out

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
FADE_LEVELS = [255, 252, 249, 246, 243, 240, 237, 245, 248, 251, 254, 255]

THINKING_TIPS = [
    "思考中...", "推理中...", "分析中...",
]
GENERATING_TIPS = [
    "生成回复中...", "组织语言中...",
]
TOOL_TIPS = [
    "外接模组已挂载...", "技能矩阵同步激活...",
    "子系统协议握手完成...", "能力扩展单元上线...",
]
CONNECTING_TIPS = [
    "连接中...",
]
AGENT_TIPS = [
    "分布式认知节点激活...", "多智能体协议同步中...",
    "子任务分配进行中...", "协作网络展开...",
]

_terminal_locked = False


def is_terminal_locked():
    """终端是否被 spinner 的 cbreak 模式占用（此时 input() 不可用）"""
    return _terminal_locked


class _TipLine:
    def __init__(self, tips):
        self.tips = list(tips)
        random.shuffle(self.tips)
        self.tip_idx = 0
        self.tip_born = time.time()
        self.fade_step = 0
        self.current_tip = ""

    def tick(self):
        now = time.time()
        if self.tips and (now - self.tip_born > 3.0 or not self.current_tip):
            self.current_tip = self.tips[self.tip_idx % len(self.tips)]
            self.tip_idx += 1
            self.tip_born = now
            self.fade_step = 0
        color = FADE_LEVELS[min(self.fade_step, len(FADE_LEVELS) - 1)]
        self.fade_step += 1
        return self.current_tip, color


class Spinner:
    """
    状态指示器（v2 队列架构）。
    生产者（主线程/asyncio）通过 update/update_sub 发送消息到队列；
    消费者（渲染线程）从队列读取并更新本地状态副本后渲染。
    """

    MSG_UPDATE_MAIN = "main"
    MSG_UPDATE_SUB = "sub"
    MSG_REMOVE_SUB = "rm_sub"

    def __init__(self):
        self._main_line = None
        self._sub_lines = {}
        self._taskboard = None
        self._running = False
        self._start_lock = threading.Lock()
        self._thread = None
        self._key_thread = None
        self._msg_queue = queue.Queue(maxsize=256)
        self._start_time = None
        self._line_count = 0
        self.interrupted = threading.Event()
        self._old_settings = None

    def set_taskboard(self, taskboard):
        self._taskboard = taskboard

    def update(self, tips=None):
        if tips:
            self._msg_queue.put((self.MSG_UPDATE_MAIN, _TipLine(tips)))
        with self._start_lock:
            if not self._running:
                self._running = True
                self.interrupted.clear()
                self._start_time = time.time()
                self._line_count = 0
                self._enter_cbreak()
                self._thread = threading.Thread(target=self._spin, daemon=True)
                self._key_thread = threading.Thread(target=self._read_keys, daemon=True)
                self._thread.start()
                self._key_thread.start()

    def update_sub(self, name, tips):
        self._msg_queue.put((self.MSG_UPDATE_SUB, name, _TipLine(tips), time.time()))

    def remove_sub(self, name):
        self._msg_queue.put((self.MSG_REMOVE_SUB, name))

    def _enter_cbreak(self):
        global _terminal_locked
        fd = sys.stdin.fileno()
        try:
            self._old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            _terminal_locked = True
        except Exception:
            self._old_settings = None

    def _exit_cbreak(self):
        global _terminal_locked
        if self._old_settings:
            fd = sys.stdin.fileno()
            try:
                while select.select([sys.stdin], [], [], 0.05)[0]:
                    os.read(fd, 4096)
            except Exception:
                pass
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, self._old_settings)
            except Exception:
                pass
            self._old_settings = None
        _terminal_locked = False

    def _read_keys(self):
        fd = sys.stdin.fileno()
        while self._running:
            try:
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    ch = os.read(fd, 1)
                    if ch == b"\x1b":
                        if select.select([sys.stdin], [], [], 0.05)[0]:
                            while select.select([sys.stdin], [], [], 0.02)[0]:
                                os.read(fd, 1)
                        else:
                            self.interrupted.set()
                            self._running = False
            except Exception:
                break

    def _spin(self):
        spin_idx = 0
        while self._running:
            self._drain_queue()
            _out.acquire()
            try:
                self._render_frame(spin_idx)
            finally:
                _out.release()
            spin_idx += 1
            time.sleep(0.08)

    def _drain_queue(self):
        """批量消费队列中的状态更新消息"""
        while True:
            try:
                msg = self._msg_queue.get_nowait()
            except queue.Empty:
                break
            if msg[0] == self.MSG_UPDATE_MAIN:
                self._main_line = msg[1]
            elif msg[0] == self.MSG_UPDATE_SUB:
                _, name, tip_line, born = msg
                self._sub_lines[name] = (tip_line, born)
            elif msg[0] == self.MSG_REMOVE_SUB:
                self._sub_lines.pop(msg[1], None)

    def _render_frame(self, spin_idx):
        now = time.time()
        main = self._main_line
        expired = [k for k, (_, born) in self._sub_lines.items() if now - born > 300]
        for k in expired:
            self._sub_lines.pop(k, None)
        subs = [(k, v) for k, (v, _) in self._sub_lines.items()]

        task_lines = self._taskboard.get_lines(tick=spin_idx) if self._taskboard else []

        elapsed = time.time() - self._start_time
        time_str = f"{elapsed * 1000:.0f}ms" if elapsed < 1 else f"{elapsed:.1f}s"
        frame = SPINNER_FRAMES[spin_idx % len(SPINNER_FRAMES)]

        buf = []

        if main:
            tip, color = main.tick()
            tip_str = f"\033[38;5;{color}m{tip}\033[0m" if tip else ""
        else:
            tip_str = ""
        buf.append(f"\r  {frame} {tip_str}  \033[38;5;242m{time_str}\033[0m\033[K")

        for sub_name, sub_line in subs:
            tip, color = sub_line.tick()
            sub_frame = SPINNER_FRAMES[(spin_idx + 3) % len(SPINNER_FRAMES)]
            tip_str = f"\033[38;5;{color}m{tip}\033[0m" if tip else ""
            buf.append(f"\r    \033[38;5;238m└\033[0m {sub_frame} \033[38;5;242m{sub_name}\033[0m {tip_str}\033[K")

        for tl in task_lines:
            tl = tl.replace("\n", " ").replace("\r", "")
            buf.append(f"\r{tl}\033[K")

        total_lines = len(buf)

        output = ""
        if self._line_count > 0:
            output += f"\033[{self._line_count}A\r"
        output += "\n".join(buf) + "\n"

        stale = self._line_count - total_lines
        if stale > 0:
            for _ in range(stale):
                output += "\033[2K\n"
            output += f"\033[{stale}A"

        _out.write_flush(output)
        self._line_count = total_lines

    def stop(self, final_message=None):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._key_thread:
            self._key_thread.join(timeout=0.5)
            self._key_thread = None
        self._exit_cbreak()

        _out.acquire()
        try:
            if self._line_count > 0:
                sys.stdout.write(f"\033[{self._line_count}A\r")
                for _ in range(self._line_count):
                    sys.stdout.write("\033[2K\n")
                sys.stdout.write(f"\033[{self._line_count}A\r")

            if final_message:
                sys.stdout.write(f"  \033[90m{final_message}\033[0m\033[K\n")
            else:
                sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        finally:
            _out.release()

        self._start_time = None
        self._main_line = None
        self._sub_lines.clear()
        self._line_count = 0
        while not self._msg_queue.empty():
            try:
                self._msg_queue.get_nowait()
            except queue.Empty:
                break
