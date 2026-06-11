"""
多行动态状态指示器 + ESC 中断 + 任务面板 + stdin 消费
spinner 渲染：主行 → sub-agent 行 → 任务面板行，统一管理行数。
"""

import sys
import os
import tty
import termios
import select
import threading
import time
import random

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
FADE_LEVELS = [255, 252, 249, 246, 243, 240, 237, 245, 248, 251, 254, 255]

THINKING_TIPS = [
    "量子态坍缩中...", "神经网络激活第七层...", "穿越知识维度裂隙...",
    "意识矩阵重构中...", "深层语义解码启动...", "概率云凝聚成形中...",
    "混沌熵值正在收敛...", "跨维度推理链展开...", "认知核心全功率运转...",
    "在无限的解空间中搜寻...",
]
GENERATING_TIPS = [
    "数据流正在具象化...", "信息晶体逐行析出...", "语义粒子加速编织中...",
    "全息投影渲染中...", "比特洪流汇聚成文...", "输出通道带宽全开...",
    "文字序列从虚空浮现...",
]
TOOL_TIPS = [
    "外接模组已挂载...", "技能矩阵同步激活...",
    "子系统协议握手完成...", "能力扩展单元上线...",
]
CONNECTING_TIPS = [
    "信号穿越星际链路...", "量子通道建立中...", "与远端节点握手...",
]
AGENT_TIPS = [
    "分布式认知节点激活...", "多智能体协议同步中...",
    "子任务分配进行中...", "协作网络展开...",
]


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
    def __init__(self):
        self._main_line = None
        self._sub_lines = {}
        self._taskboard = None
        self._running = False
        self._thread = None
        self._key_thread = None
        self._lock = threading.Lock()
        self._render_lock = threading.Lock()
        self._start_time = None
        self._line_count = 0
        self.interrupted = False
        self._old_settings = None

    def set_taskboard(self, taskboard):
        self._taskboard = taskboard

    def update(self, tips=None):
        with self._lock:
            if tips:
                self._main_line = _TipLine(tips)
        if not self._running:
            self._running = True
            self.interrupted = False
            self._start_time = time.time()
            self._line_count = 0
            self._enter_cbreak()
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._key_thread = threading.Thread(target=self._read_keys, daemon=True)
            self._thread.start()
            self._key_thread.start()

    def update_sub(self, name, tips):
        with self._lock:
            self._sub_lines[name] = (_TipLine(tips), time.time())

    def remove_sub(self, name):
        with self._lock:
            self._sub_lines.pop(name, None)

    def _enter_cbreak(self):
        fd = sys.stdin.fileno()
        try:
            self._old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except Exception:
            self._old_settings = None

    def _exit_cbreak(self):
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
                            self.interrupted = True
                            self._running = False
            except Exception:
                break

    def _spin(self):
        spin_idx = 0
        while self._running:
            with self._render_lock:
                self._render_frame(spin_idx)
            spin_idx += 1
            time.sleep(0.08)

    def _render_frame(self, spin_idx):
        now = time.time()
        with self._lock:
            main = self._main_line
            expired = [k for k, (_, born) in self._sub_lines.items() if now - born > 300]
            for k in expired:
                self._sub_lines.pop(k, None)
            subs = [(k, v) for k, (v, _) in self._sub_lines.items()]

        task_lines = self._taskboard.get_lines(tick=spin_idx) if self._taskboard else []
        total_lines = 1 + len(subs) + len(task_lines)

        elapsed = time.time() - self._start_time
        time_str = f"{elapsed * 1000:.0f}ms" if elapsed < 1 else f"{elapsed:.1f}s"
        frame = SPINNER_FRAMES[spin_idx % len(SPINNER_FRAMES)]

        buf = []

        if main:
            tip, color = main.tick()
            tip_str = f"\033[38;5;{color}m{tip}\033[0m" if tip else ""
        else:
            tip_str = ""
        buf.append(f"\r  {frame} {tip_str}  \033[90m{time_str}\033[0m\033[K")

        for sub_name, sub_line in subs:
            tip, color = sub_line.tick()
            sub_frame = SPINNER_FRAMES[(spin_idx + 3) % len(SPINNER_FRAMES)]
            tip_str = f"\033[38;5;{color}m{tip}\033[0m" if tip else ""
            buf.append(f"\r    \033[90m└\033[0m {sub_frame} \033[90m{sub_name}\033[0m {tip_str}\033[K")

        for tl in task_lines:
            buf.append(f"\r{tl}\033[K")

        output = ""
        if self._line_count > 0:
            output += f"\033[{self._line_count}A\r"
        output += "\n".join(buf) + "\n"

        stale = self._line_count - total_lines
        if stale > 0:
            for _ in range(stale):
                output += "\033[2K\n"
            output += f"\033[{stale}A"

        sys.stdout.write(output)
        sys.stdout.flush()
        self._line_count = total_lines

    def stop(self, final_message=None):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._key_thread:
            self._key_thread.join(timeout=0.5)
            self._key_thread = None
        self._exit_cbreak()

        with self._render_lock:
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

        self._start_time = None
        self._main_line = None
        with self._lock:
            self._sub_lines.clear()
        self._line_count = 0
