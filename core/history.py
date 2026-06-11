"""
对话历史持久化 —— 保存/加载/列出对话记录
"""

import json
import os
from datetime import datetime

from core import config

_SAVE_FIELDS = ("role", "content", "tool_calls", "tool_call_id", "reasoning_content")


def ensure_dirs():
    """确保数据目录存在"""
    os.makedirs(config.HISTORY_DIR, exist_ok=True)
    os.makedirs(config.USER_SKILLS_DIR, exist_ok=True)


def save(messages, filename=None):
    """保存对话历史到文件，保留所有 API 所需字段"""
    ensure_dirs()
    if filename is None:
        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    filepath = os.path.join(config.HISTORY_DIR, filename)
    saveable = []
    for msg in messages:
        entry = {}
        for key in _SAVE_FIELDS:
            if key in msg and msg[key] is not None:
                entry[key] = msg[key]
        if "role" in entry:
            saveable.append(entry)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(saveable, f, ensure_ascii=False, indent=2)
    return filepath


def list_all():
    """列出所有保存的对话历史文件名（按时间倒序）"""
    ensure_dirs()
    return sorted(
        [f for f in os.listdir(config.HISTORY_DIR) if f.endswith(".json")],
        reverse=True,
    )


def load(filename):
    """从文件加载对话历史，失败返回 None"""
    filepath = os.path.join(config.HISTORY_DIR, filename)
    if not os.path.isfile(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_for_api(messages):
    """清理消息列表，确保发送给 API 前没有残缺的 tool 链"""
    cleaned = []
    pending_tool_ids = set()

    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            pending_tool_ids = {tc["id"] for tc in msg["tool_calls"]}
            cleaned.append(msg)
        elif role == "tool":
            tid = msg.get("tool_call_id")
            if tid and tid in pending_tool_ids:
                cleaned.append(msg)
                pending_tool_ids.discard(tid)
        else:
            if pending_tool_ids:
                while cleaned and cleaned[-1].get("role") == "tool":
                    cleaned.pop()
                if cleaned and cleaned[-1].get("tool_calls"):
                    cleaned.pop()
                pending_tool_ids.clear()
            cleaned.append(msg)

    if pending_tool_ids:
        while cleaned and cleaned[-1].get("role") == "tool":
            cleaned.pop()
        if cleaned and cleaned[-1].get("tool_calls"):
            cleaned.pop()

    return cleaned
