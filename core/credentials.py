"""
凭证管理 —— API Key 安全存储到 ~/.kerker/credentials
"""

import os
import json
import stat

from core import config

CREDENTIALS_FILE = os.path.join(config.KERKER_HOME, "credentials")


def load_api_key():
    """按优先级获取 API Key: 环境变量 > credentials 文件"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    if os.path.isfile(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("api_key", "")
        except Exception:
            pass
    return ""


def save_api_key(key):
    """保存 API Key 到 ~/.kerker/credentials（权限 600）"""
    os.makedirs(config.KERKER_HOME, exist_ok=True)
    data = {"api_key": key}
    with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    try:
        os.chmod(CREDENTIALS_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def has_api_key():
    """检查是否已配置 API Key"""
    return bool(load_api_key())
