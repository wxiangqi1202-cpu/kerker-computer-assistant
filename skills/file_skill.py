"""技能：文件读写"""

import os
from skills import register

_SENSITIVE_PATHS = [
    os.path.expanduser("~/.ssh"),
    os.path.expanduser("~/.gnupg"),
    os.path.expanduser("~/.aws"),
    os.path.expanduser("~/.config/gh"),         # GitHub CLI token
    os.path.expanduser("~/.docker/config.json"), # Docker registry token
    os.path.expanduser("~/.netrc"),              # FTP/HTTP credentials
    os.path.expanduser("~/.npmrc"),              # NPM token
    os.path.expanduser("~/.pypirc"),             # PyPI token
    os.path.expanduser("~/.kerker/credentials"),
    "/etc/shadow",
    "/etc/passwd",
    "/etc/sudoers",
    "/private/etc/shadow",
    "/private/etc/passwd",
]

_SENSITIVE_NAMES = {
    ".zshrc", ".bashrc", ".bash_profile", ".profile",
    ".zprofile", ".env", ".envrc",
    "id_rsa", "id_ed25519", "id_ecdsa",    # 私钥文件名
}

_MAX_WRITE_BYTES = 5 * 1024 * 1024  # 5 MB 写入上限


def _is_sensitive(path):
    path = os.path.abspath(os.path.expanduser(path))
    for sp in _SENSITIVE_PATHS:
        if path == sp or path.startswith(sp + os.sep):
            return True
    home = os.path.expanduser("~")
    if os.path.basename(path) in _SENSITIVE_NAMES and path.startswith(home + os.sep):
        return True
    return False


def read_file(path):
    path = os.path.expanduser(path)
    if _is_sensitive(path):
        return f"安全限制: 不允许读取敏感路径 {path}"
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
    if _is_sensitive(path):
        return f"安全限制: 不允许写入敏感路径 {path}"
    size = len(content.encode("utf-8"))
    if size > _MAX_WRITE_BYTES:
        return f"写入拒绝: 内容超出 5MB 限制（当前 {size // 1024} KB）"
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
