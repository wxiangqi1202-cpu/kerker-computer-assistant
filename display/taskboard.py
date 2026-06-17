"""
任务面板 v2 —— 纯渲染器，从 ProgressTracker 读取增强快照

特性：
1. 子活动显示（running 步骤下方展示工具调用详情）
2. 步骤摘要（完成步骤显示一行结果摘要）
3. 每步计时（elapsed 显示在右侧）
4. 进度计数器（任务规划 2/5）
5. 收尾态 footer（替代"生成总结"假步骤）
6. 可配置动画速度（fast/normal/off）
7. 结束收束动画
"""

import threading
import time
import unicodedata


def _cjk_truncate(text, max_width):
    """按显示宽度截断文本（CJK字符占2列）"""
    width = 0
    for i, ch in enumerate(text):
        char_width = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if width + char_width > max_width:
            return text[:i]
        width += char_width
    return text

_BREATH_COLORS = [
    238, 240, 242, 244, 247, 250, 252, 255,
    252, 250, 247, 244, 242, 240, 238, 236,
]

_ANIM_PRESETS = {
    "normal": {"hold": 0.4, "converge": 0.6, "flash": 0.2, "fade": 0.3},
    "fast":   {"hold": 0.15, "converge": 0.25, "flash": 0.1, "fade": 0.1},
    "off":    {"hold": 0.0, "converge": 0.0, "flash": 0.0, "fade": 0.0},
}


def _fmt_elapsed(seconds):
    if seconds <= 0:
        return ""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.1f}s"


class TaskBoard:
    """
    任务面板渲染器 v2。
    由 ProgressTracker 驱动，增强显示子活动、摘要和计时。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._tracker = None
        self._finish_anim_start = 0.0
        self._finishing = False
        self._anim_done = False
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
        with self._lock:
            self._finish_anim_start = 0.0
            self._finishing = False
            self._anim_done = False
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

            if self._anim_done:
                return []

            if self._finishing:
                return self._render_finish_anim(tick)

            if self._tracker.is_finished and not self._finishing:
                snapshot = self._tracker.get_rich_snapshot()
                if snapshot:
                    self._finishing = True
                    self._finish_anim_start = time.time()
                    self._final_count = len(snapshot)
                    self._final_snapshot = snapshot
                    return self._render_finish_anim(tick)
                return []

        if not self._tracker.is_visible:
            return []

        snapshot = self._tracker.get_rich_snapshot()
        if not snapshot:
            return []

        return self._render_rich_steps(snapshot, tick)

    def _render_rich_steps(self, snapshot, tick):
        """渲染增强步骤列表：圆形符号家族 + 精细色值"""
        lines = []
        total = len(snapshot)
        done_count = sum(1 for s in snapshot if s["status"] in ("done", "error"))

        header = f"    \033[90m任务规划 ({done_count}/{total})\033[0m"
        lines.append(header)

        for step in snapshot:
            name = step["name"].replace("\n", " ")
            status = step["status"]
            elapsed = step["elapsed"]
            summary = (step["summary"] or "").replace("\n", " ")
            sub_activities = step["sub_activities"]
            elapsed_str = _fmt_elapsed(elapsed)

            if status == "running":
                c = _BREATH_COLORS[tick % len(_BREATH_COLORS)]
                time_part = f"  \033[38;5;242m{elapsed_str}\033[0m" if elapsed_str else ""
                lines.append(f"    \033[38;5;{c}m◉\033[0m \033[1;97m{name}\033[0m{time_part}")
                for act in sub_activities[-2:]:
                    act = act.replace("\n", " ")
                    lines.append(f"      \033[38;5;242m↳ {_cjk_truncate(act, 50)}\033[0m")
            elif status == "done":
                time_part = f"  \033[38;5;242m{elapsed_str}\033[0m" if elapsed_str else ""
                lines.append(f"    \033[38;5;71m✓\033[0m \033[38;5;245m{name}\033[0m{time_part}")
                if summary:
                    lines.append(f"      \033[38;5;240m· {_cjk_truncate(summary, 60)}\033[0m")
            elif status == "error":
                lines.append(f"    \033[38;5;203m✗\033[0m \033[38;5;245m{name}\033[0m")
                if summary:
                    lines.append(f"      \033[38;5;203m· {_cjk_truncate(summary, 60)}\033[0m")
            else:
                lines.append(f"    \033[38;5;242m○\033[0m \033[38;5;245m{name}\033[0m")

        footer = self._tracker.footer
        if footer:
            lines.append(f"    \033[90m─── {footer} ───\033[0m")

        return lines

    def _render_finish_anim(self, tick):
        """结束收束动画：hold → converge → glow → fade"""
        elapsed = time.time() - self._finish_anim_start
        count = self._final_count
        snapshot = self._final_snapshot

        speed = self._tracker.animation_speed if self._tracker else "normal"
        timings = _ANIM_PRESETS.get(speed, _ANIM_PRESETS["normal"])
        t_hold = timings["hold"]
        t_converge = timings["converge"]
        t_flash = timings["flash"]
        t_fade = timings["fade"]
        t_total = t_hold + t_converge + t_flash + t_fade

        if count == 0 or t_total == 0:
            self._finishing = False
            return []

        if elapsed < t_hold:
            return self._render_rich_steps(snapshot, tick)

        summary_text = f"✓ {count} 项已完成"

        t2 = t_hold + t_converge
        if elapsed < t2:
            progress = (elapsed - t_hold) / t_converge if t_converge > 0 else 1.0
            show = max(1, round(count * (1 - progress)))
            if show <= 1:
                g = int(65 + progress * 6)
                return [f"    \033[38;5;{g}m{summary_text}\033[0m"]
            lines = []
            for i in range(show):
                fade = int(240 + (1 - progress) * 15)
                name = snapshot[i]["name"].replace("\n", " ") if i < len(snapshot) else ""
                lines.append(f"    \033[38;5;{fade}m✓ {name}\033[0m")
            return lines

        t3 = t2 + t_flash
        if elapsed < t3:
            fp = (elapsed - t2) / t_flash if t_flash > 0 else 1.0
            color = 71 if fp > 0.4 else 255
            return [f"    \033[38;5;{color}m{summary_text}\033[0m"]

        t4 = t3 + t_fade
        if elapsed < t4:
            fp = (elapsed - t3) / t_fade if t_fade > 0 else 1.0
            c = int(71 + fp * (238 - 71))
            return [f"    \033[38;5;{c}m{summary_text}\033[0m"]

        self._finishing = False
        self._anim_done = True
        self._final_snapshot = []
        return []
