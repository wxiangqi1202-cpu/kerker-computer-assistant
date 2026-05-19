"""技能：文件读写"""

import os
from skills import register


def read_file(path):
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return f"文件不存在: {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) > 20000:
            content = content[:20000] + "\n...[内容过长，已截断]"
        return content
    except Exception as e:
        return f"读取失败: {e}"


def write_file(path, content):
    path = os.path.expanduser(path)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已写入 {len(content)} 个字符到 {path}"
    except Exception as e:
        return f"写入失败: {e}"


register(
    name="read_file",
    description="读取指定路径的文件内容，支持 ~ 展开",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要读取的文件路径",
            }
        },
        "required": ["path"],
    },
    func=read_file,
)

register(
    name="write_file",
    description="将内容写入指定路径的文件（会覆盖已有内容），支持自动创建目录",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要写入的文件路径",
            },
            "content": {
                "type": "string",
                "description": "要写入的内容",
            }
        },
        "required": ["path", "content"],
    },
    func=write_file,
)
