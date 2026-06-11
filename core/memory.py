"""
记忆系统 —— 语义记忆 + 情景记忆 + 会话连续性

存储结构 (~/.kerker/memory/):
  semantic.json   — 语义记忆：用户偏好、事实、项目信息
  episodes.json   — 情景索引：每次会话的摘要和关键词
"""

import os
import json
import time
from datetime import datetime
from core import config

MEMORY_DIR = os.path.join(config.KERKER_HOME, "memory")
SEMANTIC_FILE = os.path.join(MEMORY_DIR, "semantic.json")
EPISODES_FILE = os.path.join(MEMORY_DIR, "episodes.json")


def _ensure_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)


# ── 语义记忆 ─────────────────────────────

class SemanticMemory:
    """
    持久化的用户偏好和事实知识。
    每条记忆: {"id", "content", "source", "tags", "importance", "created", "updated", "access_count"}
    """

    def __init__(self):
        self._entries = []
        self._load()

    def _load(self):
        if os.path.isfile(SEMANTIC_FILE):
            try:
                with open(SEMANTIC_FILE, "r", encoding="utf-8") as f:
                    self._entries = json.load(f)
            except Exception:
                self._entries = []

    def _save(self):
        _ensure_dir()
        with open(SEMANTIC_FILE, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, ensure_ascii=False, indent=2)

    def add(self, content, source="auto", tags=None, importance=5):
        """添加一条语义记忆，自动检测冲突"""
        content = content.strip()
        if not content:
            return None

        for entry in self._entries:
            if entry["content"] == content:
                entry["access_count"] += 1
                entry["updated"] = datetime.now().isoformat()
                self._save()
                return entry

            if self._is_conflict(content, entry["content"]):
                entry["content"] = content
                entry["updated"] = datetime.now().isoformat()
                entry["source"] = source
                entry["access_count"] += 1
                self._save()
                return entry

        entry = {
            "id": int(time.time() * 1000),
            "content": content,
            "source": source,
            "tags": tags or [],
            "importance": importance,
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat(),
            "access_count": 0,
        }
        self._entries.append(entry)
        self._save()
        return entry

    def remove(self, keyword):
        """按关键词删除记忆，返回删除数量"""
        before = len(self._entries)
        self._entries = [
            e for e in self._entries
            if keyword.lower() not in e["content"].lower()
        ]
        removed = before - len(self._entries)
        if removed > 0:
            self._save()
        return removed

    def search(self, query, limit=5):
        """关键词搜索，按相关度+重要性排序"""
        query_lower = query.lower()
        scored = []
        for entry in self._entries:
            content_lower = entry["content"].lower()
            score = 0
            for word in query_lower.split():
                if word in content_lower:
                    score += 10
            score += entry.get("importance", 5)
            score += min(entry.get("access_count", 0), 10)
            if score > 0:
                entry["access_count"] = entry.get("access_count", 0) + 1
                scored.append((score, entry))

        scored.sort(key=lambda x: -x[0])
        if scored:
            self._save()
        return [e for _, e in scored[:limit]]

    def get_all(self):
        return list(self._entries)

    def get_top(self, limit=10):
        """获取最重要的记忆条目"""
        sorted_entries = sorted(
            self._entries,
            key=lambda e: (e.get("importance", 5), e.get("access_count", 0)),
            reverse=True,
        )
        return sorted_entries[:limit]

    def clear_all(self):
        self._entries = []
        self._save()

    def _is_conflict(self, new_content, old_content):
        """简单冲突检测：两条记忆讲的是同一件事但值不同"""
        new_words = set(new_content.lower().replace("：", " ").replace(":", " ").split())
        old_words = set(old_content.lower().replace("：", " ").replace(":", " ").split())
        if not new_words or not old_words:
            return False
        overlap = len(new_words & old_words) / max(len(new_words), len(old_words))
        return overlap >= 0.6

    def format_for_prompt(self, limit=8):
        """格式化为 system prompt 注入文本"""
        top = self.get_top(limit)
        if not top:
            return ""
        lines = ["[用户记忆]"]
        for e in top:
            lines.append(f"- {e['content']}")
        return "\n".join(lines)


# ── 情景记忆 ─────────────────────────────

class EpisodicMemory:
    """
    对话会话的摘要索引。
    每条: {"id", "timestamp", "summary", "keywords", "rounds", "file"}
    """

    def __init__(self):
        self._episodes = []
        self._load()

    def _load(self):
        if os.path.isfile(EPISODES_FILE):
            try:
                with open(EPISODES_FILE, "r", encoding="utf-8") as f:
                    self._episodes = json.load(f)
            except Exception:
                self._episodes = []

    def _save(self):
        _ensure_dir()
        with open(EPISODES_FILE, "w", encoding="utf-8") as f:
            json.dump(self._episodes, f, ensure_ascii=False, indent=2)

    def add_episode(self, messages, filename=None):
        """从对话消息中提取摘要并索引"""
        non_system = [m for m in messages if m.get("role") != "system"]
        user_msgs = [m for m in non_system if m.get("role") == "user"]
        assistant_msgs = [m for m in non_system if m.get("role") == "assistant"]

        if not user_msgs:
            return None

        topics = []
        keywords = set()
        for m in user_msgs[:5]:
            content = m.get("content", "")
            if content:
                topics.append(content[:60])
                for word in content.replace("，", " ").replace(",", " ").split():
                    if len(word) >= 2:
                        keywords.add(word[:10])

        summary = " → ".join(topics[:3])
        if len(topics) > 3:
            summary += f" (+{len(topics)-3}轮)"

        last_reply = ""
        if assistant_msgs:
            last = assistant_msgs[-1].get("content", "") or ""
            last_reply = last.split("\n")[0][:80]

        episode = {
            "id": int(time.time() * 1000),
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
            "last_reply": last_reply,
            "keywords": list(keywords)[:20],
            "rounds": len(user_msgs),
            "file": filename,
        }

        self._episodes.append(episode)
        if len(self._episodes) > 200:
            self._episodes = self._episodes[-200:]
        self._save()
        return episode

    def search(self, query, limit=5):
        """搜索历史会话"""
        query_lower = query.lower()
        scored = []
        for ep in self._episodes:
            score = 0
            if query_lower in ep.get("summary", "").lower():
                score += 10
            for kw in ep.get("keywords", []):
                if query_lower in kw.lower() or kw.lower() in query_lower:
                    score += 5
            if score > 0:
                scored.append((score, ep))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:limit]]

    def get_recent(self, limit=5):
        """获取最近的会话摘要"""
        return list(reversed(self._episodes[-limit:]))

    def get_all(self):
        return list(self._episodes)

    def format_recent_for_prompt(self, limit=3):
        """格式化最近会话为 prompt 注入文本"""
        recent = self.get_recent(limit)
        if not recent:
            return ""
        lines = ["[近期对话摘要]"]
        for ep in recent:
            ts = ep.get("timestamp", "")[:10]
            summary = ep.get("summary", "")[:60]
            lines.append(f"- {ts}: {summary}")
        return "\n".join(lines)


# ── 全局实例 ─────────────────────────────

_semantic = None
_episodic = None


def get_semantic():
    global _semantic
    if _semantic is None:
        _semantic = SemanticMemory()
    return _semantic


def get_episodic():
    global _episodic
    if _episodic is None:
        _episodic = EpisodicMemory()
    return _episodic
