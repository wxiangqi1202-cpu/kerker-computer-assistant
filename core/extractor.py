"""
被动记忆提取器 —— 静默从用户消息中提取习惯/偏好/情感/事实

工作流：
  1. 预过滤：正则快速判断消息是否可能含有可提取的个人信息
     → 过滤掉纯任务指令（"帮我写X"）和问题（"X是什么"）
  2. LLM 提取：向 deepseek-v4-flash 发送轻量提取请求（~150 tokens）
  3. 入库：解析返回的 JSON 写入 SemanticMemory，source="passive"

设计原则：
  - 完全异步：asyncio.create_task，不阻塞主对话流
  - 静默失败：任何异常直接 pass，绝不影响主流程
  - 可开关：config.PASSIVE_MEMORY = False 时跳过所有操作
  - 去重/冲突：由 SemanticMemory.add() 的三层冲突检测负责
"""

import json
import re

from core.memory import _CONSOLIDATE_THRESHOLD


def _extract_json_array(text: str):
    """从文本中提取第一个完整的 JSON 数组（括号配对），正确处理嵌套"""
    start = text.find("[")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape    = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None

# ── 预过滤模式（正则，零成本）────────────────────────────────

_PRE_FILTER = re.compile(
    r"我(叫|是|在|住|用|有|学|做|写|看|想|喜欢|讨厌|不喜欢|觉得|感觉|认为|每天|经常|总是|习惯)"
    r"|喜欢|偏好|偏爱|擅长|讨厌|享受|厌烦"
    r"|感觉|心情|最近|情绪|压力|很累|很烦|很爽|开心|高兴|难受|沮丧|焦虑"
    r"|目标|计划|打算|希望|想要|准备.{0,4}(做|学|完成|实现)"
    r"|I\s+(like|love|hate|prefer|always|usually|often|feel|think|want|plan|use|am)\b"
    r"|my\s+(project|goal|habit|preference|favorite|workflow|daily)\b"
    r"|feeling\s+(tired|happy|stressed|overwhelmed|excited|frustrated)\b",
    re.IGNORECASE,
)

# 一定不含个人信息的命令性开头（直接跳过）
_TASK_PREFIX = re.compile(
    r"^(帮(我|忙)|请|写一个|解释|翻译|搜索|查一下|生成|总结|分析|优化|修复|fix|write|explain|search|generate|translate)\b",
    re.IGNORECASE,
)


def _should_extract(text: str) -> bool:
    """预判是否值得调用 LLM 提取（零成本快速判断）"""
    if len(text.strip()) < 8:
        return False
    if _TASK_PREFIX.search(text.strip()):
        return False
    return bool(_PRE_FILTER.search(text))


# ── 提取 Prompt ──────────────────────────────────────────────

_EXTRACT_PROMPT = """\
从用户消息中提取隐含的个人信息。

对话上下文（辅助理解指代）：
{context}

提取范围：
  ✅ 个人偏好（喜欢/讨厌/擅长）
  ✅ 使用习惯（工具/框架/工作方式）
  ✅ 情感状态（压力/心情/感受）
  ✅ 个人事实（职业/居住地/身份）
  ✅ 长期目标（计划/希望/打算）
  ❌ 不提取：一次性任务指令、技术问题、纯问题

要求：
  - 用第三人称，以"用户"开头
  - importance 评分：强烈偏好/个人事实=7-9，日常习惯/情绪=5-6，模糊信息=3-4
  - importance < 4 的直接丢弃，不要输出

示例输入："今天写完了，Python asyncio 真好用，就是加班加到12点，累死了"
示例输出：[
  {{"content": "用户喜欢Python，认为asyncio使用体验好", "category": "偏好", "importance": 7}},
  {{"content": "用户有加班习惯，有时工作到深夜", "category": "习惯", "importance": 5}}
]

示例输入："帮我写一个快速排序"
示例输出：[]

用户消息：{message}

仅输出JSON数组，无其他内容："""


# ── 主提取函数 ────────────────────────────────────────────────

async def extract_and_save(user_message: str, context_messages: list = None) -> list:
    """
    被动提取入口。完全静默，任何异常直接返回 []。
    context_messages: 最近 1-2 轮的对话消息列表，帮助理解指代和省略。
    返回值仅供调试，正常使用无需关心。
    """
    from core import config
    if not config.PASSIVE_MEMORY:
        return []
    if not _should_extract(user_message):
        return []

    try:
        from openai import AsyncOpenAI
        from core.credentials import load_api_key
        from core.memory import get_semantic

        api_key = load_api_key()
        if not api_key:
            return []

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=config.get_model_base_url("deepseek-v4-flash"),
        )

        context_str = "无"
        if context_messages:
            ctx_lines = []
            for msg in context_messages[-4:]:
                role = msg.get("role", "")
                content = (msg.get("content") or "")[:200]
                if role in ("user", "assistant") and content:
                    label = "用户" if role == "user" else "助手"
                    ctx_lines.append(f"{label}: {content}")
            if ctx_lines:
                context_str = "\n".join(ctx_lines)

        resp = await client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "信息提取助手，只输出JSON数组。"},
                {"role": "user", "content": _EXTRACT_PROMPT.format(
                    message=user_message[:600],
                    context=context_str,
                )},
            ],
            stream=False,
            max_tokens=400,
            temperature=0.1,
        )

        raw = resp.choices[0].message.content or "[]"
        json_str = _extract_json_array(raw)
        if not json_str:
            return []
        items = json.loads(json_str)
        if not isinstance(items, list):
            return []

        from core.memory import get_semantic, _write_lock

        sem   = get_semantic()
        pend  = None
        from core import config as _cfg
        if _cfg.MEMORY_CONFIRM:
            from core.memory import get_pending
            pend = get_pending()

        saved = []
        cats_updated: set = set()
        async with _write_lock:
            for item in items:
                if not isinstance(item, dict):
                    continue
                content    = item.get("content", "").strip()
                importance = int(item.get("importance", 5))
                category   = item.get("category", "事实")
                if not content or importance < 4:
                    continue
                if pend is not None:
                    pend.add(content=content, source="passive",
                             tags=[category], importance=importance, category=category)
                else:
                    entry = sem.add(content=content, source="passive",
                                    tags=[category], importance=importance)
                    if entry:
                        saved.append(entry)
                        cats_updated.add(entry.get("category", "事实"))

        # 后台触发记忆合并（只统计非 session 条目，过期 session 不计入阈值）
        import asyncio as _aio
        for cat in cats_updated:
            non_session = sum(
                1 for e in sem.get_by_category(cat)
                if e.get("scope") != "session"
            )
            if non_session >= _CONSOLIDATE_THRESHOLD:
                _aio.create_task(_consolidate_background(sem, cat))

        return saved

    except Exception:
        return []


async def _consolidate_background(sem, category: str):
    """后台记忆合并任务，静默失败。"""
    try:
        await sem.consolidate_category_async(category)
    except Exception:
        pass
