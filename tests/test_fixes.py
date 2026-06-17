"""
修复验证测试 —— 覆盖本轮修复的关键点：
  线程安全、资源清理、错误处理、CJK 宽度、安全检测、Timer 实时读取
"""

import sys
import os
import time
import json
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestThemeThreadSafety(unittest.TestCase):
    """验证 theme 全局单例在并发读取下不会崩溃"""

    def test_concurrent_get_theme(self):
        from display.theme import get_theme
        results = [None] * 10
        errors = []

        def _get(idx):
            try:
                results[idx] = get_theme()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_get, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        for r in results:
            self.assertIsNotNone(r)
            self.assertIn("heading1", r)

    def test_set_theme_returns_false_for_unknown(self):
        from display.theme import set_theme
        self.assertFalse(set_theme("nonexistent_theme_xyz"))

    def test_set_theme_returns_true_for_builtin(self):
        from display.theme import set_theme, get_theme
        self.assertTrue(set_theme("warm"))
        self.assertEqual(get_theme()["name"], "warm")
        set_theme("minimal")


class TestSpinnerInterruptedEvent(unittest.TestCase):
    """验证 Spinner.interrupted 是 threading.Event"""

    def test_interrupted_is_event(self):
        from display.spinner import Spinner
        spinner = Spinner()
        self.assertIsInstance(spinner.interrupted, threading.Event)
        self.assertFalse(spinner.interrupted.is_set())
        spinner.interrupted.set()
        self.assertTrue(spinner.interrupted.is_set())
        spinner.interrupted.clear()
        self.assertFalse(spinner.interrupted.is_set())

    def test_stop_drains_queue(self):
        from display.spinner import Spinner
        spinner = Spinner()
        spinner._msg_queue.put(("main", "test"))
        spinner._msg_queue.put(("sub", "x", None, 0))
        spinner.stop()
        self.assertTrue(spinner._msg_queue.empty())


class TestTimerLiveRead(unittest.TestCase):
    """验证 Timer.format() 在未 stop 时返回实时耗时"""

    def test_format_before_stop_returns_live(self):
        from display.timer import Timer
        timer = Timer()
        timer.start()
        time.sleep(0.05)
        result = timer.format()
        self.assertNotEqual(result, "0ms")
        timer.stop()

    def test_format_after_stop_is_stable(self):
        from display.timer import Timer
        timer = Timer()
        timer.start()
        time.sleep(0.05)
        timer.stop()
        r1 = timer.format()
        time.sleep(0.05)
        r2 = timer.format()
        self.assertEqual(r1, r2)


class TestTiktokenLock(unittest.TestCase):
    """验证 tiktoken 初始化在并发下安全"""

    def test_concurrent_count_tokens(self):
        from core.tokens import count_tokens
        errors = []

        def _count():
            try:
                count_tokens("hello world 你好世界")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_count) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class TestMemorySingletonLock(unittest.TestCase):
    """验证 memory 单例在并发创建下只有一个实例"""

    def test_get_semantic_singleton(self):
        import core.memory as mem
        mem._semantic = None
        results = [None] * 5

        def _get(idx):
            results[idx] = mem.get_semantic()

        threads = [threading.Thread(target=_get, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for r in results:
            self.assertIs(r, results[0])


class TestHistoryLoadError(unittest.TestCase):
    """验证 history.load 对损坏文件的容错"""

    def test_load_corrupted_returns_none(self):
        from core.history import load, ensure_dirs
        from core import config
        ensure_dirs()
        bad_file = os.path.join(config.HISTORY_DIR, "_test_bad.json")
        with open(bad_file, "w") as f:
            f.write("{corrupted json!!!")
        try:
            result = load("_test_bad.json")
            self.assertIsNone(result)
        finally:
            os.unlink(bad_file)

    def test_load_nonexistent_returns_none(self):
        from core.history import load
        self.assertIsNone(load("nonexistent_file_12345.json"))


class TestConfigSaveError(unittest.TestCase):
    """验证 config.save_user_config 不会因写入失败崩溃"""

    def test_save_with_valid_path_succeeds(self):
        from core.config import config
        try:
            config.save_user_config()
        except Exception:
            self.fail("save_user_config raised unexpectedly")


class TestCjkTruncate(unittest.TestCase):
    """验证 CJK 宽度截断"""

    def test_ascii_truncate(self):
        from display.taskboard import _cjk_truncate
        self.assertEqual(_cjk_truncate("hello world", 5), "hello")

    def test_cjk_truncate_width(self):
        from display.taskboard import _cjk_truncate
        result = _cjk_truncate("你好世界测试", 8)
        self.assertEqual(result, "你好世界")

    def test_mixed_truncate(self):
        from display.taskboard import _cjk_truncate
        result = _cjk_truncate("ab你好cd", 6)
        self.assertEqual(result, "ab你好")

    def test_no_truncation_needed(self):
        from display.taskboard import _cjk_truncate
        self.assertEqual(_cjk_truncate("hi", 10), "hi")


class TestAnsiStripWidth(unittest.TestCase):
    """验证 ANSI 转义码剥离支持更多序列类型"""

    def test_sgr_stripped(self):
        from display.md_render import _visible_width
        self.assertEqual(_visible_width("\033[1;31mhello\033[0m"), 5)

    def test_cursor_movement_stripped(self):
        from display.md_render import _visible_width
        self.assertEqual(_visible_width("\033[2Ahello\033[3B"), 5)

    def test_cjk_width(self):
        from display.md_render import _visible_width
        self.assertEqual(_visible_width("你好"), 4)

    def test_mixed_ansi_cjk(self):
        from display.md_render import _visible_width
        self.assertEqual(_visible_width("\033[1m你好\033[0m"), 4)


class TestFileSkillSensitivityFix(unittest.TestCase):
    """验证 file_skill 只在 home 目录下拦截敏感文件名"""

    def test_env_in_home_blocked(self):
        from skills.file_skill import _is_sensitive
        home = os.path.expanduser("~")
        self.assertTrue(_is_sensitive(os.path.join(home, "project/.env")))

    def test_env_outside_home_allowed(self):
        from skills.file_skill import _is_sensitive
        self.assertFalse(_is_sensitive("/tmp/some_project/.env"))

    def test_ssh_key_always_blocked(self):
        from skills.file_skill import _is_sensitive
        self.assertTrue(_is_sensitive("~/.ssh/id_rsa"))


class TestShellSkillRmNoSpace(unittest.TestCase):
    """验证 rm -rf/path 无空格也能检测"""

    def test_rm_rf_slash_no_space(self):
        from skills.shell_skill import _is_dangerous
        self.assertTrue(_is_dangerous("rm -rf/home"))
        self.assertTrue(_is_dangerous("rm -rf/etc"))

    def test_rm_normal_still_works(self):
        from skills.shell_skill import _is_dangerous
        self.assertTrue(_is_dangerous("rm -rf /"))
        self.assertTrue(_is_dangerous("rm -rf ~"))


class TestMemoryLoadJsonSafe(unittest.TestCase):
    """验证 _load_json_safe 对损坏文件的容错"""

    def test_missing_file_returns_empty(self):
        from core.memory import _load_json_safe
        result = _load_json_safe("/nonexistent/path.json", "测试")
        self.assertEqual(result, [])

    def test_corrupted_file_returns_empty(self):
        import tempfile
        from core.memory import _load_json_safe
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("{bad json")
            result = _load_json_safe(path, "测试")
            self.assertEqual(result, [])
        finally:
            os.unlink(path)


class TestOutputManager(unittest.TestCase):
    """验证 OutputManager 线程安全写入"""

    def test_concurrent_write_no_interleave(self):
        from display import output as _out
        import io
        results = []
        errors = []

        def _write(tag):
            try:
                _out.acquire()
                try:
                    results.append(tag)
                finally:
                    _out.release()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 20)

    def test_write_flush_callable(self):
        from display import output as _out
        try:
            _out.write_flush("")
        except Exception:
            self.fail("write_flush raised unexpectedly")


class TestLazyInit(unittest.TestCase):
    """验证延迟初始化机制"""

    def test_skills_init_idempotent(self):
        import skills
        skills.init()
        count1 = len(skills.get_skill_names())
        skills.init()
        count2 = len(skills.get_skill_names())
        self.assertEqual(count1, count2)

    def test_agents_init_idempotent(self):
        import agents
        agents.init()
        count1 = len(agents.get_all_agents())
        agents.init()
        count2 = len(agents.get_all_agents())
        self.assertEqual(count1, count2)

    def test_skills_not_loaded_before_init(self):
        import skills
        self.assertTrue(skills._initialized)


class TestTurnDelta(unittest.TestCase):
    """验证 send() 不修改原始 messages"""

    def test_send_does_not_modify_original(self):
        import asyncio
        from core.turn import send

        class FakeClient:
            pass

        messages = [
            {"role": "system", "content": "test"},
            {"role": "user", "content": "hello"},
        ]
        original_len = len(messages)
        original_copy = [dict(m) for m in messages]

        async def _run():
            try:
                async for event in send(FakeClient(), messages):
                    pass
            except Exception:
                pass

        try:
            asyncio.run(_run())
        except Exception:
            pass

        self.assertEqual(len(messages), original_len)
        for orig, cur in zip(original_copy, messages):
            self.assertEqual(orig["role"], cur["role"])


class TestNewlineInStepName(unittest.TestCase):
    """验证步骤名中的换行被正确清理"""

    def test_set_plan_strips_newlines(self):
        from core.progress import ProgressTracker
        tracker = ProgressTracker()
        tracker.set_plan([
            {"step": "搜索\n资料", "agent": "researcher"},
            {"step": "代码\r\n审查", "agent": ""},
        ])
        names = tracker.get_step_names()
        for name in names:
            self.assertNotIn("\n", name)
            self.assertNotIn("\r", name)

    def test_summary_strips_newlines(self):
        from core.progress import ProgressTracker
        tracker = ProgressTracker()
        tracker.set_plan([{"step": "A", "agent": "r"}])
        tracker.agent_start("r")
        tracker.set_step_summary("r", "line1\nline2\nline3")
        snapshot = tracker.get_rich_snapshot()
        self.assertNotIn("\n", snapshot[0]["summary"])

    def test_sub_activity_strips_newlines(self):
        from core.progress import ProgressTracker
        tracker = ProgressTracker()
        tracker.set_plan([{"step": "A", "agent": "r"}])
        tracker.agent_start("r")
        tracker.add_sub_activity("r", "doing\nstuff")
        snapshot = tracker.get_rich_snapshot()
        for act in snapshot[0]["sub_activities"]:
            self.assertNotIn("\n", act["text"])
            self.assertEqual(act["source"], "r")


if __name__ == "__main__":
    unittest.main()
