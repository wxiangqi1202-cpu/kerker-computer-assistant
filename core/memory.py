"""
记忆系统 —— 语义记忆 + 情景记忆 + 会话连续性

存储结构 (~/.kerker/memory/):
  semantic.json   — 语义记忆：用户偏好、事实、项目信息
  episodes.json   — 情景索引：每次会话的摘要和关键词

搜索机制：
  - TF-IDF 加权的文本相似度（无需外部依赖）
  - 字符 bigram 重叠作为 fallback
  - 按相关度 + 重要性 + 访问频率综合排序
"""

import os
import json
import uuid
import math
from datetime import datetime
from collections import Counter
from core import config

MEMORY_DIR = os.path.join(config.KERKER_HOME, "memory")
SEMANTIC_FILE = os.path.join(MEMORY_DIR, "semantic.json")
EPISODES_FILE = os.path.join(MEMORY_DIR, "episodes.json")


def _ensure_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)


def _tokenize(text):
    """
    中英文混合分词：
    - 英文按空格/标点切分为词
    - 中文按字切分 + bigram
    """
    text = text.lower().strip()
    tokens = []
    ascii_buf = []

    for ch in text:
        if ch.isascii() and ch.isalnum():
            ascii_buf.append(ch)
        else:
            if ascii_buf:
                word = "".join(ascii_buf)
                if len(word) >= 2:
                    tokens.append(word)
                ascii_buf = []
            if '\u4e00' <= ch <= '\u9fff':
                tokens.append(ch)

    if ascii_buf:
        word = "".join(ascii_buf)
        if len(word) >= 2:
            tokens.append(word)

    cjk_chars = [ch for ch in text if '\u4e00' <= ch <= '\u9fff']
    for i in range(len(cjk_chars) - 1):
        tokens.append(cjk_chars[i] + cjk_chars[i + 1])

    return tokens


def _compute_tf(tokens):
    """计算词频"""
    counter = Counter(tokens)
    total = len(tokens) if tokens else 1
    return {term: count / total for term, count in counter.items()}


class _TFIDFIndex:
    """轻量 TF-IDF 索引（无外部依赖）"""

    def __init__(self):
        self._docs = []
        self._tf_cache = []
        self._idf_cache = {}
        self._dirty = True

    def update(self, documents):
        """重建索引。documents: list[str]"""
        self._docs = documents
        self._tf_cache = [_compute_tf(_tokenize(doc)) for doc in documents]
        self._dirty = True

    def _build_idf(self):
        """计算 IDF"""
        if not self._dirty:
            return
        num_docs = len(self._docs)
        if num_docs == 0:
            self._idf_cache = {}
            self._dirty = False
            return

        df = Counter()
        for tf in self._tf_cache:
            for term in tf:
                df[term] += 1

        self._idf_cache = {
            term: math.log((num_docs + 1) / (count + 1)) + 1
            for term, count in df.items()
        }
        self._dirty = False

    def query(self, text, top_k=5):
        """
        查询相似文档。返回 [(index, score), ...] 按 score 降序。
        """
        if not self._docs:
            return []

        self._build_idf()
        query_tokens = _tokenize(text)
        query_tf = _compute_tf(query_tokens)

        scores = []
        for doc_idx, doc_tf in enumerate(self._tf_cache):
            score = 0.0
            for term, qtf in query_tf.items():
                if term in doc_tf:
                    idf = self._idf_cache.get(term, 1.0)
                    score += qtf * doc_tf[term] * idf * idf
            scores.append((doc_idx, score))

        scores.sort(key=lambda x: -x[1])
        return [(idx, s) for idx, s in scores[:top_k] if s > 0]


# ── 语义记忆 ─────────────────────────────

class SemanticMemory:
    """
    持久化的用户偏好和事实知识。
    每条记忆: {"id", "content", "source", "tags", "importance", "created", "updated", "access_count"}
    搜索使用 TF-IDF 相似度 + 重要性加权。
    """

    def __init__(self):
        self._entries = []
        self._tfidf = _TFIDFIndex()
        self._access_dirty = False
        self._load()

    def _load(self):
        if os.path.isfile(SEMANTIC_FILE):
            try:
                with open(SEMANTIC_FILE, "r", encoding="utf-8") as f:
                    self._entries = json.load(f)
            except Exception:
                self._entries = []
        self._rebuild_index()

    def _rebuild_index(self):
        """重建 TF-IDF 索引"""
        docs = [e.get("content", "") for e in self._entries]
        self._tfidf.update(docs)

    def _save(self):
        _ensure_dir()
        with open(SEMANTIC_FILE, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, ensure_ascii=False, indent=2)
        self._access_dirty = False

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
                self._rebuild_index()
                return entry

        entry = {
            "id": uuid.uuid4().hex,
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
        self._rebuild_index()
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
            self._rebuild_index()
        return removed

    def search(self, query, limit=5):
        """
        TF-IDF 语义搜索，按相关度+重要性+访问频率综合排序。
        比纯关键词匹配能更好地处理同义词和模糊查询。
        access_count 累加后标记为 dirty，延迟到下次写盘操作时一并持久化，
        避免每次搜索都触发同步 I/O。
        """
        if not self._entries:
            return []

        tfidf_results = self._tfidf.query(query, top_k=limit * 2)

        scored = []
        for idx, tfidf_score in tfidf_results:
            entry = self._entries[idx]
            importance_bonus = entry.get("importance", 5) * 0.5
            access_bonus = min(entry.get("access_count", 0), 10) * 0.3
            final_score = tfidf_score * 10 + importance_bonus + access_bonus
            scored.append((final_score, idx, entry))

        query_lower = query.lower()
        matched_indices = {idx for _, idx, _ in scored}
        for idx, entry in enumerate(self._entries):
            if idx in matched_indices:
                continue
            content_lower = entry["content"].lower()
            keyword_score = 0
            for word in query_lower.split():
                if word in content_lower:
                    keyword_score += 5
            if keyword_score > 0:
                importance_bonus = entry.get("importance", 5) * 0.5
                access_bonus = min(entry.get("access_count", 0), 10) * 0.3
                final_score = keyword_score + importance_bonus + access_bonus
                scored.append((final_score, idx, entry))

        scored.sort(key=lambda x: -x[0])
        results = []
        for _, idx, entry in scored[:limit]:
            entry["access_count"] = entry.get("access_count", 0) + 1
            results.append(entry)

        if results:
            self._access_dirty = True
        return results

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
        self._access_dirty = False
        self._save()
        self._rebuild_index()

    def _is_conflict(self, new_content, old_content):
        """
        冲突检测：判断两条记忆是否描述同一件事。
        使用双重策略：
        1. 词级重叠（适合英文和带空格的中文）
        2. 字符 bigram 重叠（适合无空格的中文）
        任一策略判定为冲突即返回 True。
        """
        new_lower = new_content.lower().replace("：", " ").replace(":", " ")
        old_lower = old_content.lower().replace("：", " ").replace(":", " ")

        new_words = set(new_lower.split())
        old_words = set(old_lower.split())
        if new_words and old_words:
            word_overlap = len(new_words & old_words) / max(len(new_words), len(old_words))
            if word_overlap >= 0.6:
                return True

        new_bigrams = set(zip(new_lower, new_lower[1:]))
        old_bigrams = set(zip(old_lower, old_lower[1:]))
        if new_bigrams and old_bigrams:
            bigram_overlap = len(new_bigrams & old_bigrams) / max(len(new_bigrams), len(old_bigrams))
            if bigram_overlap >= 0.6:
                return True

        return False

    def format_for_prompt(self, limit=8):
        """格式化为 system prompt 注入文本，并顺带持久化累计的 access_count 变更"""
        top = self.get_top(limit)
        if not top:
            return ""
        lines = ["[用户记忆]"]
        for e in top:
            lines.append(f"- {e['content']}")
        if self._access_dirty:
            self._save()
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
            "id": uuid.uuid4().hex,
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
