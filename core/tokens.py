"""
Token 计算模块 —— 精确 token 计数 + 动态上下文窗口管理

优化点：
1. 优先使用 tiktoken 做精确计数，fallback 到改进的启发式算法
2. 根据模型实际 context window 动态设置上限
3. 缓存 encoding 实例避免重复初始化
"""

import threading

_encoding = None
_tiktoken_available = False
_tiktoken_init_attempted = False
_tiktoken_lock = threading.Lock()


def _init_tiktoken():
    """延迟初始化 tiktoken（仅在首次调用时加载，失败后不再重试）"""
    global _encoding, _tiktoken_available, _tiktoken_init_attempted
    with _tiktoken_lock:
        if _tiktoken_init_attempted:
            return
        _tiktoken_init_attempted = True
        try:
            import tiktoken
            _encoding = tiktoken.get_encoding("cl100k_base")
            _tiktoken_available = True
        except (ImportError, Exception):
            _tiktoken_available = False


def count_tokens(text: str) -> int:
    """
    精确计算文本 token 数。
    优先使用 tiktoken，fallback 到改进的启发式算法。
    """
    if not text:
        return 0

    global _tiktoken_init_attempted
    if not _tiktoken_init_attempted:
        _init_tiktoken()

    if _tiktoken_available and _encoding:
        return len(_encoding.encode(text))

    return _estimate_tokens_heuristic(text)


def _estimate_tokens_heuristic(text: str) -> int:
    """
    改进的启发式 token 估算：
    - 中文字符：平均 1.5 token/字（CJK 统一表意文字）
    - 英文单词：平均 1.3 token/词（比纯 0.4/char 更准确）
    - 标点/特殊符号：约 1 token/符号
    """
    if not text:
        return 0

    cjk_chars = 0
    ascii_chars = 0
    other_chars = 0

    for ch in text:
        if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f':
            cjk_chars += 1
        elif ch.isascii():
            ascii_chars += 1
        else:
            other_chars += 1

    ascii_words = len(text.encode('ascii', errors='ignore').split())
    cjk_tokens = int(cjk_chars * 1.5)
    ascii_tokens = max(int(ascii_words * 1.3), int(ascii_chars * 0.3))
    other_tokens = other_chars

    return cjk_tokens + ascii_tokens + other_tokens


def count_message_tokens(msg: dict) -> int:
    """
    计算单条消息的 token 数（含 message overhead）。
    每条消息额外消耗约 4 token（role + 分隔符）。
    """
    tokens = 4
    content = msg.get("content", "") or ""
    tokens += count_tokens(content)

    if msg.get("tool_calls"):
        for tc in msg["tool_calls"]:
            func = tc.get("function", {})
            tokens += count_tokens(func.get("name", ""))
            tokens += count_tokens(func.get("arguments", ""))

    if msg.get("name"):
        tokens += count_tokens(msg["name"])

    return tokens


MODEL_CONTEXT_WINDOWS = {
    "deepseek-v4-pro": 128000,
    "deepseek-v4-flash": 128000,
    "deepseek-reasoner": 64000,
}

DEFAULT_CONTEXT_WINDOW = 64000
CONTEXT_RESERVE_RATIO = 0.75


def get_max_context_tokens(model: str = None) -> int:
    """
    根据模型返回最大可用 context token 数。
    预留 25% 给输出 + 安全余量。
    """
    from core import config as cfg
    model = model or cfg.MODEL
    window = MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)
    return int(window * CONTEXT_RESERVE_RATIO)


def is_tiktoken_available() -> bool:
    """检查 tiktoken 是否可用（供诊断/日志）"""
    global _tiktoken_init_attempted
    if not _tiktoken_init_attempted:
        _init_tiktoken()
    return _tiktoken_available
