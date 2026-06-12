"""
ProgressTracker 单元测试 —— 验证统一进度系统的核心逻辑
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.progress import ProgressTracker, ProgressMode, StepStatus


class TestProgressTrackerModes(unittest.TestCase):
    def setUp(self):
        self.tracker = ProgressTracker()

    def test_initial_state(self):
        self.assertEqual(self.tracker.mode, ProgressMode.IDLE)
        self.assertFalse(self.tracker.is_visible)
        self.assertFalse(self.tracker.is_finished)
        self.assertFalse(self.tracker.has_plan)

    def test_tool_mode_activation(self):
        self.tracker.tool_start("搜索")
        self.assertEqual(self.tracker.mode, ProgressMode.TOOL_MODE)
        self.assertFalse(self.tracker.is_visible)

    def test_tool_mode_visible_after_second_tool(self):
        """TOOL_MODE no longer shows taskboard (spinner handles it)"""
        self.tracker.tool_start("搜索")
        self.tracker.tool_start("读取文件")
        self.assertFalse(self.tracker.is_visible)

    def test_tool_done_marks_complete(self):
        """tool_done is a no-op now"""
        self.tracker.tool_start("搜索")
        self.tracker.tool_done("搜索")
        self.assertEqual(self.tracker.get_snapshot(), [])

    def test_plan_mode_activation(self):
        self.tracker.set_plan([
            {"step": "调研技术方案", "agent": "researcher"},
            {"step": "编写代码", "agent": ""},
        ])
        self.assertEqual(self.tracker.mode, ProgressMode.PLAN_MODE)
        self.assertTrue(self.tracker.has_plan)
        self.assertTrue(self.tracker.is_visible)

    def test_reset_clears_all(self):
        self.tracker.tool_start("搜索")
        self.tracker.reset()
        self.assertEqual(self.tracker.mode, ProgressMode.IDLE)
        self.assertFalse(self.tracker.is_visible)
        self.assertEqual(self.tracker.get_snapshot(), [])


class TestProgressTrackerPlanMode(unittest.TestCase):
    def setUp(self):
        self.tracker = ProgressTracker()
        self.tracker.set_plan([
            {"step": "搜索资料", "agent": "researcher"},
            {"step": "代码审查", "agent": "code_reviewer"},
            {"step": "生成总结", "agent": ""},
        ])

    def test_plan_steps_count(self):
        self.assertEqual(len(self.tracker.plan_steps), 3)

    def test_plan_dedup(self):
        tracker = ProgressTracker()
        tracker.set_plan([
            {"step": "搜索", "agent": ""},
            {"step": "搜索", "agent": ""},
            {"step": "分析", "agent": ""},
        ])
        self.assertEqual(len(tracker.plan_steps), 2)

    def test_agent_start_matches_bound_step(self):
        result = self.tracker.agent_start("researcher")
        self.assertEqual(result, "搜索资料")
        snapshot = self.tracker.get_snapshot()
        self.assertEqual(snapshot[0], ("搜索资料", "running"))
        self.assertEqual(snapshot[1], ("代码审查", "pending"))

    def test_agent_done_completes_step(self):
        self.tracker.agent_start("researcher")
        self.tracker.agent_done("researcher", summary="完成搜索")
        snapshot = self.tracker.get_snapshot()
        self.assertEqual(snapshot[0], ("搜索资料", "done"))

    def test_agent_error_marks_error(self):
        self.tracker.agent_start("researcher")
        self.tracker.agent_error("researcher", error="网络超时")
        snapshot = self.tracker.get_snapshot()
        self.assertEqual(snapshot[0], ("搜索资料", "error"))

    def test_finish_all_completes_remaining(self):
        self.tracker.agent_start("researcher")
        self.tracker.agent_done("researcher")
        self.tracker.finish_all()
        snapshot = self.tracker.get_snapshot()
        for name, status in snapshot:
            self.assertEqual(status, "done")
        self.assertTrue(self.tracker.is_finished)

    def test_tool_calls_in_plan_mode_ignored(self):
        """PLAN_MODE 下普通 tool_start/tool_done 不影响 plan steps"""
        self.tracker.tool_start("搜索")
        self.tracker.tool_done("搜索")
        snapshot = self.tracker.get_snapshot()
        self.assertEqual(len(snapshot), 3)
        self.assertEqual(snapshot[0][1], "pending")


class TestProgressTrackerToolMode(unittest.TestCase):
    """TOOL_MODE 现在不显示面板，仅切换模式"""

    def setUp(self):
        self.tracker = ProgressTracker()

    def test_tool_mode_activated(self):
        self.tracker.tool_start("搜索")
        self.assertEqual(self.tracker.mode, ProgressMode.TOOL_MODE)

    def test_tool_mode_not_visible(self):
        """TOOL_MODE 下面板不可见（由 spinner 负责）"""
        self.tracker.tool_start("搜索")
        self.tracker.tool_start("读取")
        self.assertFalse(self.tracker.is_visible)
        self.assertEqual(self.tracker.get_snapshot(), [])

    def test_finish_all_noop_in_tool_mode(self):
        """TOOL_MODE 无步骤，finish_all 是空操作"""
        self.tracker.tool_start("搜索")
        self.tracker.finish_all()
        self.assertFalse(self.tracker.is_finished)


class TestProgressTrackerContext(unittest.TestCase):
    def setUp(self):
        self.tracker = ProgressTracker()
        self.tracker.set_original_task("写一个完整的 AI 应用")
        self.tracker.set_plan([
            {"step": "调研", "agent": "researcher"},
            {"step": "开发", "agent": ""},
        ])

    def test_build_context_has_task(self):
        ctx = self.tracker.build_context_prompt()
        self.assertIn("写一个完整的 AI 应用", ctx)

    def test_build_context_has_plan(self):
        ctx = self.tracker.build_context_prompt()
        self.assertIn("调研", ctx)
        self.assertIn("开发", ctx)

    def test_build_context_has_memory(self):
        self.tracker.add_memory("researcher", "调研AI框架", "找到3个候选方案")
        ctx = self.tracker.build_context_prompt()
        self.assertIn("找到3个候选方案", ctx)


class TestProgressTrackerEdgeCases(unittest.TestCase):
    """边界情况和稳定性测试"""

    def test_finish_all_no_steps_is_noop(self):
        """无步骤时 finish_all 不应设置 is_finished"""
        tracker = ProgressTracker()
        tracker.finish_all()
        self.assertFalse(tracker.is_finished)
        self.assertEqual(tracker.get_snapshot(), [])

    def test_repeated_tool_names_no_panel(self):
        """重复工具调用不再显示在面板中"""
        tracker = ProgressTracker()
        tracker.tool_start("搜索")
        tracker.tool_start("搜索")
        tracker.tool_start("搜索")
        self.assertEqual(tracker.get_snapshot(), [])

    def test_ensure_step_active_advances_pending(self):
        """ensure_step_active 推进下一个 pending 步骤"""
        tracker = ProgressTracker()
        tracker.set_plan([
            {"step": "步骤1", "agent": ""},
            {"step": "步骤2", "agent": ""},
        ])
        tracker.ensure_step_active()
        snapshot = tracker.get_snapshot()
        self.assertEqual(snapshot[0][1], "running")
        self.assertEqual(snapshot[1][1], "pending")

    def test_ensure_step_active_noop_if_already_running(self):
        """已有 running 步骤时不再推进"""
        tracker = ProgressTracker()
        tracker.set_plan([
            {"step": "步骤1", "agent": ""},
            {"step": "步骤2", "agent": ""},
        ])
        tracker.ensure_step_active()
        tracker.ensure_step_active()
        snapshot = tracker.get_snapshot()
        self.assertEqual(snapshot[0][1], "running")
        self.assertEqual(snapshot[1][1], "pending")

    def test_pause_on_interrupt_preserves_plan(self):
        """中断后 plan 状态保留，running 回退为 pending"""
        tracker = ProgressTracker()
        tracker.set_plan([
            {"step": "A", "agent": "r"},
            {"step": "B", "agent": ""},
        ])
        tracker.agent_start("r")
        tracker.pause_on_interrupt()
        self.assertTrue(tracker.has_plan)
        snapshot = tracker.get_snapshot()
        self.assertEqual(snapshot[0][1], "pending")

    def test_pause_then_resume(self):
        """中断后可以恢复执行"""
        tracker = ProgressTracker()
        tracker.set_plan([
            {"step": "A", "agent": "r"},
            {"step": "B", "agent": ""},
        ])
        tracker.agent_start("r")
        tracker.agent_done("r", summary="ok")
        tracker.pause_on_interrupt()
        tracker.ensure_step_active()
        snapshot = tracker.get_snapshot()
        self.assertEqual(snapshot[0][1], "done")
        self.assertEqual(snapshot[1][1], "running")

    def test_agent_start_without_plan_returns_none(self):
        """非 PLAN_MODE 下 agent_start 返回 None"""
        tracker = ProgressTracker()
        result = tracker.agent_start("researcher")
        self.assertIsNone(result)

    def test_agent_done_without_running_step(self):
        """agent_done 在无 running 步骤时不崩溃"""
        tracker = ProgressTracker()
        tracker.set_plan([{"step": "步骤1", "agent": "researcher"}])
        tracker.agent_done("researcher")
        snapshot = tracker.get_snapshot()
        self.assertEqual(snapshot[0][1], "pending")

    def test_multiple_finish_all_idempotent(self):
        """多次 finish_all 结果一致"""
        tracker = ProgressTracker()
        tracker.set_plan([{"step": "X", "agent": ""}])
        tracker.ensure_step_active()
        tracker.finish_all()
        snapshot1 = tracker.get_snapshot()
        tracker.finish_all()
        snapshot2 = tracker.get_snapshot()
        self.assertEqual(snapshot1, snapshot2)

    def test_plan_mode_to_idle_after_reset(self):
        """reset 后从 PLAN_MODE 回到 IDLE"""
        tracker = ProgressTracker()
        tracker.set_plan([{"step": "X", "agent": ""}])
        self.assertTrue(tracker.has_plan)
        tracker.reset()
        self.assertFalse(tracker.has_plan)
        self.assertEqual(tracker.mode, ProgressMode.IDLE)

    def test_different_tools_no_panel(self):
        """工具调用不再显示在面板"""
        tracker = ProgressTracker()
        tracker.tool_start("搜索")
        tracker.tool_start("读取文件")
        self.assertEqual(tracker.get_snapshot(), [])


class TestTaskBoardRenderer(unittest.TestCase):
    """TaskBoard 渲染器边界测试"""

    def test_no_tracker_returns_empty(self):
        from display.taskboard import TaskBoard
        board = TaskBoard()
        self.assertEqual(board.get_lines(tick=0), [])

    def test_cleared_then_new_content_auto_reset(self):
        """clear 后如果 tracker 被 reset 并有新 plan，应自动恢复"""
        from display.taskboard import TaskBoard
        tracker = ProgressTracker()
        board = TaskBoard()
        board.set_tracker(tracker)

        tracker.set_plan([{"step": "A", "agent": ""}, {"step": "B", "agent": ""}])
        board.clear()
        self.assertEqual(board.get_lines(tick=0), [])

        tracker.reset()
        tracker.set_plan([{"step": "C", "agent": ""}, {"step": "D", "agent": ""}])
        lines = board.get_lines(tick=0)
        self.assertTrue(len(lines) > 0)

    def test_single_tool_not_visible(self):
        """TOOL_MODE 不显示面板"""
        from display.taskboard import TaskBoard
        tracker = ProgressTracker()
        board = TaskBoard()
        board.set_tracker(tracker)
        tracker.tool_start("搜索")
        self.assertEqual(board.get_lines(tick=0), [])


if __name__ == "__main__":
    unittest.main()
