"""
KerKer 记忆系统 v2 —— BM25 + 时间衰减 + 自动分类 + 容量管理

架构：
  SemanticMemory  持久化用户事实/偏好，BM25 语义检索 + 时间衰减打分
  EpisodicMemory  对话会话索引，BM25 + 关键词双重检索

改进点（相比 v1）：
  1. BM25 替换 TF-IDF：TF 有上限，避免高频词过度占优；长度归一化更合理
  2. 时间衰减：记忆随时间权重递减（半衰期 30 天），新记忆天然优先
  3. 访问时效：最近一次访问时间参与打分，不仅仅是次数
  4. 自动分类：写入时标注 技术/项目/偏好/人物/事实 五类，支持按类检索
  5. 容量管理：上限 500 条，超限时按综合得分驱逐最低分条目
  6. 结构化冲突检测：谓词级别识别"同话题不同值"的矛盾记忆

存储（~/.kerker/memory/）：
  semantic.json  语义记忆条目
  episodes.json  情景会话索引
"""

import asyncio
import os
import json
import math
import re
import tempfile
import time
import uuid
from collections import Counter
from datetime import datetime

from core import config

# ── 异步写锁（防止被动提取与主动 remember 并发写入冲突）───
_write_lock = asyncio.Lock()

# ── 目录 ─────────────────────────────────────────
MEMORY_DIR    = os.path.join(config.KERKER_HOME, "memory")
SEMANTIC_FILE = os.path.join(MEMORY_DIR, "semantic.json")
EPISODES_FILE = os.path.join(MEMORY_DIR, "episodes.json")
PENDING_FILE  = os.path.join(MEMORY_DIR, "pending.json")


def _ensure_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)


def _atomic_write_json(filepath: str, data):
    """原子写入 JSON：先写临时文件再 os.replace，防止写入中途崩溃导致数据丢失"""
    _ensure_dir()
    fd, tmp_path = tempfile.mkstemp(dir=MEMORY_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, filepath)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── BM25 参数 ─────────────────────────────────────
_K1 = 1.5
_B  = 0.75

# ── 时间衰减参数 ──────────────────────────────────
_HALF_LIFE_DAYS = 30.0

# ── 容量 & 合并阈值 ───────────────────────────────
_MAX_MEMORIES          = 500
_CONSOLIDATE_THRESHOLD = 8   # 同类别条目超过此数触发自动合并

# ── 记忆合并提示词 ────────────────────────────────
_CONSOLIDATION_PROMPT = """\
以下是用户的 {count} 条「{category}」类记忆，可能有重复或相关内容。\
请提炼为 1-3 条精华摘要，保留全部有价值的细节，去掉冗余。

记忆列表：
{content_list}

要求：每条以"用户"开头；importance 1-10（高价值=7-9，一般=5-6）。
仅输出JSON数组：[{{"content":"...", "importance":8}}]\
"""


# ── 合并任务竞态守卫 ──────────────────────────────
_consolidating: set = set()   # 正在合并的类别集合，防止同类别重复触发


def detect_namespace_from_cwd() -> str:
    """从 CWD 的 git 仓库名自动推断命名空间，失败返回 'global'"""
    import subprocess as _sp
    try:
        r = _sp.run(["git", "rev-parse", "--show-toplevel"],
                    capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            return os.path.basename(r.stdout.strip()) or "global"
    except Exception:
        pass
    return "global"

# ── 自动分类模式 ──────────────────────────────────
_CATEGORY_PATTERNS: dict = {
    "技术": [
        r"python|java|c\+\+|rust|go\b|javascript|typescript|swift|kotlin",
        r"框架|库|sdk|api\b|编程|算法|模型|神经网络|深度学习|机器学习",
        r"docker|git|linux|macos|windows|vscode|vim|终端|shell",
        r"ascend|cann|npu|tiling|算子|pytorch|tensorflow",
    ],
    "项目": [
        r"项目|仓库|repo\b|路径|~/|目录|文件夹|工程|需求|功能|模块|接口|版本",
    ],
    "偏好": [
        r"喜欢|不喜欢|偏好|偏爱|习惯|倾向|风格|方式|擅长|讨厌|觉得|认为",
    ],
    "人物": [
        r"叫|名字|我是|我叫|用户名|账号|联系方式|邮件|手机",
    ],
}

# ── 谓词模式（用于结构化冲突检测） ──────────────────
_PREDICATE_RE = re.compile(
    r"^(.{1,10})(是|叫|用|住在|在|喜欢|不喜欢|擅长|用的是|使用|偏好)(.+)$"
)

# ── Session 作用域检测（临时状态，当天有效）────────────
_SESSION_RE = re.compile(
    r"正在|现在|今天|这次|暂时|临时|当前|此刻|目前|刚才|刚刚|"
    r"currently|right now|today|temporary|for now",
    re.IGNORECASE,
)


# ── 分词 ─────────────────────────────────────────

def _tokenize(text: str) -> list:
    """中英文混合分词：英文按词，中文按字 + bigram"""
    text   = text.lower().strip()
    tokens = []
    ascii_buf: list = []

    for ch in text:
        if ch.isascii() and ch.isalnum():
            ascii_buf.append(ch)
        else:
            if ascii_buf:
                word = "".join(ascii_buf)
                if len(word) >= 2:
                    tokens.append(word)
                ascii_buf = []
            if "\u4e00" <= ch <= "\u9fff":
                tokens.append(ch)

    if ascii_buf:
        word = "".join(ascii_buf)
        if len(word) >= 2:
            tokens.append(word)

    cjk = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])

    return tokens


# ── BM25 索引 ─────────────────────────────────────

class _BM25Index:
    """
    BM25 全文索引（无外部依赖）。
    公式：score(q,d) = Σ IDF(qi) × tf_bm25(qi,d)
      tf_bm25 = f*(k1+1) / (f + k1*(1-b+b*dl/avgdl))   ← TF 有天花板
      IDF     = log((N-df+0.5)/(df+0.5)+1)              ← Robertson-Walker
    """

    def __init__(self):
        self._docs:      list  = []
        self._tf_cache:  list  = []
        self._df:        Counter = Counter()
        self._avgdl:     float = 1.0
        self._idf_cache: dict  = {}
        self._dirty:     bool  = True

    def update(self, documents: list):
        self._docs     = documents
        self._tf_cache = [Counter(_tokenize(d)) for d in documents]
        self._df       = Counter()
        for tf in self._tf_cache:
            for term in tf:
                self._df[term] += 1
        total_len   = sum(sum(tf.values()) for tf in self._tf_cache)
        self._avgdl = total_len / max(len(documents), 1)
        self._dirty = True

    def add_doc(self, doc: str):
        """增量追加单个文档，O(M) 而非 O(N×M)，适合频繁写入场景"""
        tf = Counter(_tokenize(doc))
        n  = len(self._docs) + 1
        new_dl      = sum(tf.values())
        self._avgdl = (self._avgdl * (n - 1) + new_dl) / n
        for term in tf:
            self._df[term] += 1
        self._docs.append(doc)
        self._tf_cache.append(tf)
        self._dirty = True   # IDF cache stale，下次 query 时重建

    def _build_idf(self):
        if not self._dirty:
            return
        n = len(self._docs)
        self._idf_cache = {
            term: math.log((n - df + 0.5) / (df + 0.5) + 1)
            for term, df in self._df.items()
        }
        self._dirty = False

    def query(self, text: str, top_k: int = 5) -> list:
        if not self._docs:
            return []
        self._build_idf()
        q_tokens = _tokenize(text)
        avgdl    = max(self._avgdl, 1.0)   # 防 avgdl=0 导致除零
        scores   = []
        for idx, tf in enumerate(self._tf_cache):
            dl    = sum(tf.values())
            score = 0.0
            for term in q_tokens:
                if term not in tf:
                    continue
                f       = tf[term]
                idf     = self._idf_cache.get(term, 0.0)
                tf_bm25 = f * (_K1 + 1) / (f + _K1 * (1 - _B + _B * dl / avgdl))
                score  += idf * tf_bm25
            scores.append(score)
        ranked = sorted(enumerate(scores), key=lambda x: -x[1])
        return [(i, s) for i, s in ranked[:top_k] if s > 0]


# ── 辅助函数 ──────────────────────────────────────

def _auto_category(content: str) -> str:
    lower = content.lower()
    for cat, patterns in _CATEGORY_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, lower):
                return cat
    return "事实"


def _decay_factor(updated_iso: str) -> float:
    """指数衰减 decay = 2^(-days/HALF_LIFE)，最小 0.1"""
    try:
        ts   = datetime.fromisoformat(updated_iso).timestamp()
        days = (time.time() - ts) / 86400.0
        return max(math.pow(0.5, days / _HALF_LIFE_DAYS), 0.1)
    except Exception:
        return 1.0


def _access_recency(last_accessed_iso) -> float:
    """访问时效因子，半衰期 7 天，最小 0.2"""
    if not last_accessed_iso:
        return 0.5
    try:
        ts   = datetime.fromisoformat(last_accessed_iso).timestamp()
        days = (time.time() - ts) / 86400.0
        return max(math.pow(0.5, days / 7.0), 0.2)
    except Exception:
        return 0.5


def _extract_predicate(content: str):
    """提取 (主体+谓词, 宾语)，返回 None 表示无法识别"""
    m = _PREDICATE_RE.match(content.strip())
    if m:
        return m.group(1) + m.group(2), m.group(3)
    return None


# ── 语义记忆 ─────────────────────────────────────

class SemanticMemory:
    """
    持久化语义记忆。

    公开 API（向后兼容 v1）：
      add / remove / search / get_all / get_top / clear_all / format_for_prompt
    v2 新增：
      get_by_category / stats
    """

    def __init__(self):
        self._entries:      list  = []
        self._bm25:         _BM25Index = _BM25Index()
        self._access_dirty: bool  = False
        self._load()

    def _load(self):
        if os.path.isfile(SEMANTIC_FILE):
            try:
                with open(SEMANTIC_FILE, "r", encoding="utf-8") as f:
                    self._entries = json.load(f)
                for e in self._entries:                     # 向前兼容
                    e.setdefault("category",      _auto_category(e.get("content", "")))
                    e.setdefault("last_accessed", e.get("updated"))
            except json.JSONDecodeError as err:
                import sys as _sys
                print(f"[kerker] 语义记忆文件损坏，已重置: {err}", file=_sys.stderr)
                self._entries = []
            except Exception as err:
                import sys as _sys
                print(f"[kerker] 加载语义记忆出错，已重置: {err}", file=_sys.stderr)
                self._entries = []
        self._rebuild_index()
        self._purge_expired_sessions()

    def _save(self):
        _atomic_write_json(SEMANTIC_FILE, self._entries)
        self._access_dirty = False

    def _rebuild_index(self):
        self._bm25.update([e.get("content", "") for e in self._entries])

    def _purge_expired_sessions(self):
        """清理非当天的 session 条目，避免无效数据长期积累"""
        today = datetime.now().date()
        before = len(self._entries)
        kept = []
        for entry in self._entries:
            if entry.get("scope") == "session":
                try:
                    created_date = datetime.fromisoformat(entry["created"]).date()
                    if created_date != today:
                        continue
                except Exception:
                    continue
            kept.append(entry)
        if len(kept) != before:
            self._entries = kept
            self._save()
            self._rebuild_index()

    def _entry_score(self, entry: dict) -> float:
        """
        综合得分 = importance × time_decay × access_recency × visit_bonus
        session 作用域条目：仅当天有效，跨天返回 0（不参与注入和排序）。
        """
        if entry.get("scope") == "session":
            try:
                created_date = datetime.fromisoformat(entry["created"]).date()
                if created_date != datetime.now().date():
                    return 0.0   # 跨天的临时记忆自动失效
            except Exception:
                return 0.0
        return (
            entry.get("importance", 5)
            * _decay_factor(entry.get("updated", entry.get("created", "")))
            * _access_recency(entry.get("last_accessed"))
            * (1 + math.log1p(entry.get("access_count", 0)) * 0.3)
        )

    def _evict_if_needed(self):
        if len(self._entries) <= _MAX_MEMORIES:
            return
        scored   = sorted(self._entries, key=self._entry_score)
        to_evict = len(self._entries) - _MAX_MEMORIES
        self._entries = scored[to_evict:]
        self._rebuild_index()

    def _is_conflict(self, new_content: str, old_content: str) -> bool:
        """三层冲突检测：谓词结构 → 词级重叠 → 字符 bigram
        短文本（< 15 字）使用更严格的阈值，避免误判覆盖。
        """
        new_pred = _extract_predicate(new_content)
        old_pred = _extract_predicate(old_content)
        if new_pred and old_pred:
            if new_pred[0] == old_pred[0] and new_pred[1] != old_pred[1]:
                return True

        is_short = max(len(new_content), len(old_content)) < 15
        overlap_threshold = 0.8 if is_short else 0.6

        def words(s):
            return set(s.lower().replace("：", " ").replace(":", " ").split())
        nw, ow = words(new_content), words(old_content)
        if nw and ow and len(nw & ow) / max(len(nw), len(ow)) >= overlap_threshold:
            return True

        def bigrams(s):
            s = s.lower()
            return set(zip(s, s[1:]))
        nb, ob = bigrams(new_content), bigrams(old_content)
        if nb and ob and len(nb & ob) / max(len(nb), len(ob)) >= overlap_threshold:
            return True

        return False

    # ── 公开 API ──────────────────────────────────

    def add(self, content: str, source: str = "auto",
            tags=None, importance: int = 5, namespace: str = None):
        content    = content.strip()
        importance = max(1, min(10, int(importance)))
        if namespace is None:
            namespace = config.CURRENT_NAMESPACE
        if not content:
            return None
        now = datetime.now().isoformat()

        for entry in self._entries:
            if entry["content"] == content:
                entry["access_count"] += 1
                entry["updated"]       = now
                entry["last_accessed"] = now
                self._save()
                return entry

        for entry in self._entries:
            if self._is_conflict(content, entry["content"]):
                entry.update({
                    "content":       content,
                    "updated":       now,
                    "last_accessed": now,
                    "source":        source,
                    "category":      _auto_category(content),
                    "access_count":  entry["access_count"] + 1,
                })
                self._save()
                self._rebuild_index()
                return entry

        entry = {
            "id":            uuid.uuid4().hex,
            "content":       content,
            "source":        source,
            "tags":          tags or [],
            "category":      _auto_category(content),
            "scope":         "session" if _SESSION_RE.search(content) else "persistent",
            "namespace":     namespace,
            "importance":    importance,
            "created":       now,
            "updated":       now,
            "last_accessed": now,
            "access_count":  0,
        }
        self._entries.append(entry)
        needs_evict = len(self._entries) > _MAX_MEMORIES
        self._evict_if_needed()   # 超限则全量 rebuild
        self._save()
        if not needs_evict:       # 未触发驱逐时才用增量，否则 rebuild 已包含新条目
            self._bm25.add_doc(content)
        return entry

    def remove(self, keyword: str) -> int:
        before        = len(self._entries)
        self._entries = [e for e in self._entries
                         if keyword.lower() not in e["content"].lower()]
        removed       = before - len(self._entries)
        if removed:
            self._save()
            self._rebuild_index()
        return removed

    def search(self, query: str, limit: int = 5, category: str = None,
               update_access: bool = True, namespaces: set = None) -> list:
        """BM25 主检索 + 关键词 fallback，综合打分含时间衰减。
        namespaces: 指定命名空间集合，None=自动使用当前+global。
        update_access=False 用于只读查询（如动态注入），避免 access_count 虚高。
        """
        if not self._entries:
            return []
        if namespaces is None:
            ns = config.CURRENT_NAMESPACE
            namespaces = {ns, "global"}

        bm25_hits = {idx: s for idx, s in self._bm25.query(query, top_k=limit * 3)}
        scored    = []
        seen_ids: set = set()

        for idx, entry in enumerate(self._entries):
            if category and entry.get("category") != category:
                continue
            if entry.get("namespace", "global") not in namespaces:
                continue
            bm25_s = bm25_hits.get(idx, 0.0)
            if bm25_s > 0:
                score = (
                    bm25_s * 10
                    * _decay_factor(entry.get("updated", ""))
                    * _access_recency(entry.get("last_accessed"))
                    + entry.get("importance", 5) * 0.5
                )
                scored.append((score, entry))
                seen_ids.add(entry["id"])

        q_lower = query.lower()
        for entry in self._entries:
            if entry["id"] in seen_ids:
                continue
            if category and entry.get("category") != category:
                continue
            if entry.get("namespace", "global") not in namespaces:
                continue
            if q_lower in entry["content"].lower():
                score = (
                    5.0
                    * _decay_factor(entry.get("updated", ""))
                    * _access_recency(entry.get("last_accessed"))
                    + entry.get("importance", 5) * 0.5
                )
                scored.append((score, entry))

        scored.sort(key=lambda x: -x[0])
        now     = datetime.now().isoformat()
        results = []
        for _, entry in scored[:limit]:
            if update_access:
                entry["access_count"] += 1
                entry["last_accessed"] = now
            results.append(entry)

        if results and update_access:
            self._save()
        return results

    def get_all(self) -> list:
        return list(self._entries)

    def get_top(self, limit: int = 10, category: str = None,
                namespaces: set = None) -> list:
        if namespaces is None:
            ns = config.CURRENT_NAMESPACE
            namespaces = {ns, "global"}
        pool = [
            e for e in self._entries
            if (not category or e.get("category") == category)
            and e.get("namespace", "global") in namespaces
        ]
        return sorted(pool, key=self._entry_score, reverse=True)[:limit]

    def get_by_category(self, category: str) -> list:
        return [e for e in self._entries if e.get("category") == category]

    def clear_all(self):
        self._entries      = []
        self._access_dirty = False
        self._save()
        self._rebuild_index()

    async def consolidate_category_async(self, category: str) -> int:
        """
        异步合并某类别的冗余记忆（背景任务，静默失败）。
        用 _consolidating 守卫防止同类别并发重复合并。
        返回减少的条目数，0 表示未触发或失败。
        """
        if category in _consolidating:
            return 0
        _consolidating.add(category)
        try:
            targets = [e for e in self._entries
                       if e.get("category") == category and e.get("scope") != "session"]
            if len(targets) < _CONSOLIDATE_THRESHOLD:
                return 0
            try:
                from openai import AsyncOpenAI
                from core.credentials import load_api_key
                from core.extractor import _extract_json_array

                api_key = load_api_key()
                if not api_key:
                    return 0

                client = AsyncOpenAI(
                    api_key=api_key,
                    base_url=config.get_model_base_url("deepseek-v4-flash"),
                )
                content_list = "\n".join(f"- {e['content']}" for e in targets[:15])
                prompt = _CONSOLIDATION_PROMPT.format(
                    count=len(targets[:15]), category=category, content_list=content_list
                )
                resp = await client.chat.completions.create(
                    model="deepseek-v4-flash",
                    messages=[
                        {"role": "system", "content": "记忆合并助手，只输出JSON数组。"},
                        {"role": "user",   "content": prompt},
                    ],
                    stream=False, max_tokens=500, temperature=0.1,
                )
                raw      = resp.choices[0].message.content or "[]"
                json_str = _extract_json_array(raw)
                if not json_str:
                    return 0
                consolidated = [c for c in json.loads(json_str)
                                if isinstance(c, dict) and c.get("content", "").strip()]
                if not consolidated:
                    return 0

                old_count  = len(targets[:15])
                remove_ids = {e["id"] for e in targets[:15]}          # O(1) hash lookup
                ns_counts = Counter(e.get("namespace", "global") for e in targets[:15])
                dominant_ns = ns_counts.most_common(1)[0][0] if ns_counts else "global"
                self._entries = [e for e in self._entries
                                 if e["id"] not in remove_ids]        # O(N) not O(N^2)
                now = datetime.now().isoformat()
                for item in consolidated:
                    self._entries.append({
                        "id":           uuid.uuid4().hex,
                        "content":      item["content"].strip(),
                        "source":       "consolidated",
                        "tags":         [category],
                        "category":     category,
                        "scope":        "persistent",
                        "namespace":    dominant_ns,
                        "importance":   max(1, min(10, int(item.get("importance", 7)))),
                        "created":      now, "updated": now, "last_accessed": now,
                        "access_count": 0,
                        "source_count": old_count,
                    })
                self._save()
                self._rebuild_index()
                return old_count - len(consolidated)
            except Exception:
                return 0
        finally:
            _consolidating.discard(category)

    def stats(self) -> dict:
        by_cat = Counter(e.get("category", "事实") for e in self._entries)
        return {
            "total":          len(self._entries),
            "max":            _MAX_MEMORIES,
            "by_category":    dict(by_cat),
            "avg_importance": (
                sum(e.get("importance", 5) for e in self._entries) / len(self._entries)
                if self._entries else 0.0
            ),
        }

    def format_for_prompt(self, limit: int = 8, categories=None) -> str:
        """按类别分组注入 system prompt，让 LLM 更清楚记忆的类型。
        categories 过滤在 get_top 阶段完成，确保能取到足够的目标类别条目。
        """
        # 若指定了 categories，先过滤再取 top，确保结果数量符合期望
        if categories:
            pool = [e for e in self._entries if e.get("category") in categories]
            top  = sorted(pool, key=self._entry_score, reverse=True)[:limit]
        else:
            top = self.get_top(limit)
        if not top:
            return ""
        if self._access_dirty:
            self._save()

        grouped: dict = {}
        for e in top:
            grouped.setdefault(e.get("category", "事实"), []).append(e["content"])

        if not grouped:
            return ""

        lines = ["[用户记忆]"]
        for cat, items in grouped.items():
            lines.append(f"  [{cat}]")
            for item in items:
                lines.append(f"  - {item}")
        return "\n".join(lines)


# ── 情景记忆停用词（模块级，避免每次 add_episode 重建） ───────
_EPISODE_STOPWORDS = frozenset({
    "的", "了", "在", "是", "有", "和", "与", "或", "但", "也",
    "都", "被", "把", "对", "这", "那", "很", "就", "还",
    "不", "我", "你", "他", "她", "它", "们", "这个", "那个",
    "一个", "一些", "可以", "需要", "已经", "因为", "所以",
})


# ── 情景记忆 ─────────────────────────────────────

class EpisodicMemory:
    """对话会话摘要索引，v2 改用 BM25+关键词双重检索"""

    def __init__(self):
        self._episodes: list  = []
        self._bm25:     _BM25Index = _BM25Index()
        self._load()

    def _load(self):
        if os.path.isfile(EPISODES_FILE):
            try:
                with open(EPISODES_FILE, "r", encoding="utf-8") as f:
                    self._episodes = json.load(f)
            except json.JSONDecodeError as err:
                import sys as _sys
                print(f"[kerker] 情景记忆文件损坏，已重置: {err}", file=_sys.stderr)
                self._episodes = []
            except Exception as err:
                import sys as _sys
                print(f"[kerker] 加载情景记忆出错，已重置: {err}", file=_sys.stderr)
                self._episodes = []
        self._rebuild_index()

    def _save(self):
        _atomic_write_json(EPISODES_FILE, self._episodes)

    def _rebuild_index(self):
        docs = [
            e.get("summary", "") + " " + " ".join(e.get("keywords", []))
            for e in self._episodes
        ]
        self._bm25.update(docs)

    def add_episode(self, messages: list, filename=None):
        non_system     = [m for m in messages if m.get("role") != "system"]
        user_msgs      = [m for m in non_system if m.get("role") == "user"]
        assistant_msgs = [m for m in non_system if m.get("role") == "assistant"]
        if not user_msgs:
            return None

        topics: list  = []
        keywords: set = set()
        for m in user_msgs[:5]:
            content = m.get("content", "")
            if content:
                topics.append(content[:60])
                for token in _tokenize(content):
                    if len(token) >= 2 and token not in _EPISODE_STOPWORDS:
                        keywords.add(token[:12])

        summary = " → ".join(topics[:3])
        if len(topics) > 3:
            summary += f" (+{len(topics) - 3}轮)"

        last_reply = ""
        if assistant_msgs:
            last       = assistant_msgs[-1].get("content", "") or ""
            last_reply = last.split("\n")[0][:80]

        episode = {
            "id":         uuid.uuid4().hex,
            "timestamp":  datetime.now().isoformat(),
            "summary":    summary,
            "last_reply": last_reply,
            "keywords":   list(keywords)[:20],
            "rounds":     len(user_msgs),
            "file":       filename,
        }
        self._episodes.append(episode)
        if len(self._episodes) > 200:
            self._episodes = self._episodes[-200:]
        self._save()
        self._rebuild_index()
        return episode

    def search(self, query: str, limit: int = 5) -> list:
        if not self._episodes:
            return []

        bm25_hits = {idx: s for idx, s in self._bm25.query(query, top_k=limit * 2)}
        scored: list = []
        matched: set = set()

        for idx, ep in enumerate(self._episodes):
            if idx in bm25_hits:
                scored.append((bm25_hits[idx] * 10, ep))
                matched.add(idx)

        q_lower = query.lower()
        for idx, ep in enumerate(self._episodes):
            if idx in matched:
                continue
            s = 0
            if q_lower in ep.get("summary", "").lower():
                s += 10
            for kw in ep.get("keywords", []):
                if q_lower in kw.lower() or kw.lower() in q_lower:
                    s += 5
            if s:
                scored.append((float(s), ep))

        scored.sort(key=lambda x: -x[0])
        return [ep for _, ep in scored[:limit]]

    def get_recent(self, limit: int = 5) -> list:
        return list(reversed(self._episodes[-limit:]))

    def get_all(self) -> list:
        return list(self._episodes)

    def format_recent_for_prompt(self, limit: int = 3) -> str:
        recent = self.get_recent(limit)
        if not recent:
            return ""
        lines = ["[近期对话摘要]"]
        for ep in recent:
            ts      = ep.get("timestamp", "")[:10]
            summary = ep.get("summary", "")[:60]
            lines.append(f"- {ts}: {summary}")
        return "\n".join(lines)


# ── 全局单例 ─────────────────────────────────────

_semantic = None
_episodic = None
_pending  = None


def get_semantic() -> SemanticMemory:
    global _semantic
    if _semantic is None:
        _semantic = SemanticMemory()
    return _semantic


def get_episodic() -> EpisodicMemory:
    global _episodic
    if _episodic is None:
        _episodic = EpisodicMemory()
    return _episodic


# ── 待确认记忆队列 ─────────────────────────────────

class PendingMemory:
    """
    被动提取的待确认记忆队列（当 config.MEMORY_CONFIRM=True 时启用）。
    passive → pending.json → 用户 /memory approve → semantic.json
    超过 7 天未处理自zai c动清除。
    """

    _EXPIRE_DAYS = 7

    def __init__(self):
        self._pending: list = []
        self._load()

    def _load(self):
        if os.path.isfile(PENDING_FILE):
            try:
                with open(PENDING_FILE, "r", encoding="utf-8") as f:
                    self._pending = json.load(f)
                self._expire_old()
            except Exception:
                self._pending = []

    def _save(self):
        _atomic_write_json(PENDING_FILE, self._pending)

    def _expire_old(self):
        cutoff = time.time() - self._EXPIRE_DAYS * 86400
        before = len(self._pending)
        kept   = []
        for p in self._pending:
            try:
                ts = datetime.fromisoformat(p.get("pending_since", "")).timestamp()
                if ts > cutoff:
                    kept.append(p)
            except Exception:
                pass
        if len(kept) != before:
            self._pending = kept
            self._save()

    def add(self, content: str, source: str = "passive",
            tags=None, importance: int = 5, category: str = "事实") -> dict:
        entry = {
            "pending_id":    uuid.uuid4().hex[:8],
            "content":       content.strip(),
            "source":        source,
            "tags":          tags or [],
            "category":      category,
            "importance":    importance,
            "pending_since": datetime.now().isoformat(),
        }
        self._pending.append(entry)
        self._save()
        return entry

    def get_all(self) -> list:
        return list(self._pending)

    def count(self) -> int:
        return len(self._pending)

    def approve(self, pending_id: str = None) -> int:
        """批准并移入语义记忆。pending_id=None 全部批准。"""
        sem     = get_semantic()
        targets = self._pending if pending_id is None else [
            p for p in self._pending if p.get("pending_id") == pending_id
        ]
        approved, approved_ids = 0, set()
        for p in targets:
            sem.add(
                content=p["content"], source="approved",
                tags=p["tags"],       importance=p["importance"],
            )
            approved_ids.add(p["pending_id"])
            approved += 1
        self._pending = [p for p in self._pending if p["pending_id"] not in approved_ids]
        if approved:
            self._save()
        return approved

    def reject(self, pending_id: str = None) -> int:
        before        = len(self._pending)
        self._pending = [] if pending_id is None else [
            p for p in self._pending if p.get("pending_id") != pending_id
        ]
        removed = before - len(self._pending)
        if removed:
            self._save()
        return removed

    def format_preview(self, limit: int = 10) -> str:
        if not self._pending:
            return "暂无待确认记忆"
        lines = [f"待确认记忆（{len(self._pending)} 条，/memory approve 全部接受）"]
        for p in self._pending[:limit]:
            pid  = p.get("pending_id", "?")
            cat  = p.get("category", "事实")
            imp  = p.get("importance", 5)
            text = p["content"][:50]
            lines.append(f"  [{pid}] [{cat}] {text}  重要度:{imp}")
        if len(self._pending) > limit:
            lines.append(f"  … 还有 {len(self._pending) - limit} 条")
        return "\n".join(lines)


def get_pending() -> PendingMemory:
    global _pending
    if _pending is None:
        _pending = PendingMemory()
    return _pending
