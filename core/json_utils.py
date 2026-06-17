"""
JSON 提取工具 —— 从 LLM 原始输出中提取 JSON 片段

提供两个公开函数：
- extract_json_object: 提取第一个完整的 JSON 对象 ({...})
- extract_json_array:  提取第一个完整的 JSON 数组  ([...])
"""


def _extract_balanced(text: str, open_ch: str, close_ch: str):
    """从文本中提取第一个括号配对完整的片段，正确处理字符串和转义。"""
    start = text.find(open_ch)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
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
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json_object(text: str):
    """从文本中提取第一个完整的 JSON 对象（{...}），正确处理嵌套和字符串转义。"""
    return _extract_balanced(text, "{", "}")


def extract_json_array(text: str):
    """从文本中提取第一个完整的 JSON 数组（[...]），正确处理嵌套和字符串转义。"""
    return _extract_balanced(text, "[", "]")
