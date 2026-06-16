"""
async_client.py —— 向后兼容层

原有逻辑已拆分到：
  core/client.py   — API 客户端（create_client, api_call_with_retry, 响应解析）
  core/prompt.py   — System prompt 组装（sync_system_messages, clean_route_messages）
  core/context.py  — 上下文管理（trim/compress, tool_display_name）
  core/turn.py     — 单轮执行循环（send, _try_auto_route, 工具分发）

本文件保留 re-export 以兼容现有 import。
"""

from core.client import create_client
from core.turn import send
from core.context import tool_display_name as _tool_display_name
