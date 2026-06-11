"""
技能：记忆管理 —— 用户可通过对话控制 agent 的记忆
  "记住我喜欢简洁的代码风格" → remember
  "忘掉关于密码的记忆" → forget
  agent 也可主动调用 recall 获取相关记忆
"""

import json
from skills import register
from core.memory import get_semantic, get_episodic


def remember(content, tags=None, importance=7):
    """记住一条信息（用户偏好、事实、约定等）"""
    mem = get_semantic()
    entry = mem.add(content, source="user", tags=tags or [], importance=importance)
    if entry:
        return f"已记住: {content}"
    return "记忆保存失败"


def forget(keyword):
    """忘掉包含关键词的记忆"""
    mem = get_semantic()
    count = mem.remove(keyword)
    if count > 0:
        return f"已忘掉 {count} 条关于'{keyword}'的记忆"
    return f"没有找到关于'{keyword}'的记忆"


def recall(query):
    """检索与当前问题相关的记忆和历史"""
    sem = get_semantic()
    epi = get_episodic()

    sem_results = sem.search(query, limit=5)
    epi_results = epi.search(query, limit=3)

    parts = []
    if sem_results:
        parts.append("相关记忆:")
        for e in sem_results:
            parts.append(f"  - {e['content']}")

    if epi_results:
        parts.append("相关历史对话:")
        for e in epi_results:
            ts = e.get("timestamp", "")[:10]
            parts.append(f"  - {ts}: {e.get('summary', '')[:60]}")

    if not parts:
        return f"没有找到与'{query}'相关的记忆"

    return "\n".join(parts)


register(
    name="remember",
    description="记住用户告知的信息（偏好、事实、约定）。当用户说'记住xxx'、'我喜欢xxx'、'以后都xxx'时调用。",
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "要记住的内容",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "标签，如 ['偏好', '代码风格']",
            },
            "importance": {
                "type": "integer",
                "description": "重要性 1-10，用户明确要求记住的给 8-10",
            },
        },
        "required": ["content"],
    },
    func=remember,
)

register(
    name="forget",
    description="忘掉包含关键词的记忆。当用户说'忘掉xxx'、'别记了'、'删掉关于xxx的记忆'时调用。",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "要忘掉的关键词",
            },
        },
        "required": ["keyword"],
    },
    func=forget,
)

register(
    name="recall",
    description="检索与问题相关的用户记忆和历史对话。当需要了解用户过去的偏好、约定或历史操作时调用。",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词",
            },
        },
        "required": ["query"],
    },
    func=recall,
)
