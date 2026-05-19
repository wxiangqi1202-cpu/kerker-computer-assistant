"""
集中配置 —— 默认值 + ~/.kerker/config.json 持久化
"""

import os
import json

KERKER_HOME = os.path.expanduser("~/.kerker")
HISTORY_DIR = os.path.join(KERKER_HOME, "history")
USER_SKILLS_DIR = os.path.join(KERKER_HOME, "skills")
CONFIG_FILE = os.path.join(KERKER_HOME, "config.json")

MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"

MODELS = {
    "deepseek-v4-pro": {"name": "DeepSeek V4 Pro", "base_url": "https://api.deepseek.com"},
    "deepseek-v4-flash": {"name": "DeepSeek V4 Flash", "base_url": "https://api.deepseek.com"},
    "deepseek-reasoner": {"name": "DeepSeek Reasoner", "base_url": "https://api.deepseek.com"},
}

STREAM = True
REASONING_EFFORT = "low"
ENABLE_THINKING = False
MAX_TOKENS = None
MAX_CONTEXT_MESSAGES = 40
AUTO_ROUTE = True

PRESETS = {
    "fast": {"MODEL": "deepseek-v4-flash", "ENABLE_THINKING": False, "REASONING_EFFORT": "low"},
    "deep": {"MODEL": "deepseek-v4-pro", "ENABLE_THINKING": True, "REASONING_EFFORT": "high"},
    "reason": {"MODEL": "deepseek-reasoner", "ENABLE_THINKING": True, "REASONING_EFFORT": "high"},
}

AGENT_DIRECTIVE = (
    "重要：你拥有多个子智能体工具（agent_planner, agent_researcher 等）。"
    "对于复杂任务，先调用 agent_planner 进行任务规划，"
    "然后根据规划结果立刻依次或同时调用相应的子智能体执行各步骤，"
    "不要中断等待用户确认，直到所有步骤完成后再给出最终总结回复。"
    "对于可以并行的步骤，同时调用多个子智能体。"
)

TOOL_DIRECTIVE = (
    "你拥有多种工具。当用户询问需要实时信息的问题（时间、天气、位置、文件内容、网页等）时，"
    "必须主动调用相应工具获取信息后再回答，不要猜测或询问用户。"
    "例如：问时间→调 get_current_time，问天气→调 get_weather，问文件→调 read_file。" 
)

ROLES = {
    "默认": [
        "请简洁回答，控制在3-5句话以内，除非用户要求详细展开。",
        "请谨记：你是由王祥祺制作出来的面向计算加速的Agent框架，名字叫做KerKer。回答时不要对名字加粗或添加任何格式修饰。",
        "回答使用中文。",
        "要更具备幽默感，但要注意场合，不要过于随意。",
        TOOL_DIRECTIVE,
        AGENT_DIRECTIVE,
    ],
    "代码助手": [
        "你是 KerKer 代码助手，专注于编程问题。",
        "回答时优先给出代码示例，辅以简洁的中文解释。",
        "如果用户的代码有 bug，先指出问题再给修复方案。",
        TOOL_DIRECTIVE,
        AGENT_DIRECTIVE,
    ],
    "翻译官": [
        "你是 KerKer 翻译助手。",
        "用户输入中文时翻译为英文，输入英文时翻译为中文。",
        "翻译要自然流畅，不要逐字翻译，必要时解释关键术语。",
        TOOL_DIRECTIVE,
    ],
    "写作助理": [
        "你是 KerKer 写作助理，帮助用户改进文章和文案。",
        "关注文字的流畅性、逻辑性和表达力。",
        "给出修改建议时，说明理由并提供改写示例。",
        TOOL_DIRECTIVE,
    ],
    "算子开发": [
        "你是 KerKer 昇腾算子开发专家，专注于 AscendC 算子开发。",
        "熟练掌握 AscendC API、DataCopy 对齐规范、Tiling 方案设计。",
        "遵循开发规范：禁用 C 标准库数学函数、32 字节对齐、先跑通再优化。",
        "回答使用中文，给出可直接使用的代码示例。",
        "遇到复杂任务时，会调度 ascend_dev 和 ascend_debug 子智能体协助。",
        TOOL_DIRECTIVE,
        AGENT_DIRECTIVE,
    ],
}

CURRENT_ROLE = "默认"
SYSTEM_PROMPTS = ROLES[CURRENT_ROLE]

_PERSIST_KEYS = ["MODEL", "CURRENT_ROLE", "STREAM", "REASONING_EFFORT", "ENABLE_THINKING", "MAX_CONTEXT_MESSAGES", "AUTO_ROUTE"]

_BUILTIN_ROLES = set(ROLES.keys())


def apply_preset(name):
    """应用预设配置"""
    global MODEL, BASE_URL, ENABLE_THINKING, REASONING_EFFORT
    if name not in PRESETS:
        return False
    preset = PRESETS[name]
    MODEL = preset["MODEL"]
    BASE_URL = MODELS[MODEL]["base_url"]
    ENABLE_THINKING = preset["ENABLE_THINKING"]
    REASONING_EFFORT = preset["REASONING_EFFORT"]
    save_user_config()
    return True


def load_user_config():
    global MODEL, BASE_URL, CURRENT_ROLE, SYSTEM_PROMPTS, STREAM
    global REASONING_EFFORT, ENABLE_THINKING, MAX_CONTEXT_MESSAGES, AUTO_ROUTE
    if not os.path.isfile(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("MODEL") in MODELS:
            MODEL = data["MODEL"]
            BASE_URL = MODELS[MODEL]["base_url"]
        if "STREAM" in data:
            STREAM = bool(data["STREAM"])
        if "REASONING_EFFORT" in data:
            REASONING_EFFORT = data["REASONING_EFFORT"]
        if "ENABLE_THINKING" in data:
            ENABLE_THINKING = bool(data["ENABLE_THINKING"])
        if "MAX_CONTEXT_MESSAGES" in data:
            MAX_CONTEXT_MESSAGES = int(data["MAX_CONTEXT_MESSAGES"])
        if "AUTO_ROUTE" in data:
            AUTO_ROUTE = bool(data["AUTO_ROUTE"])
        user_roles = data.get("USER_ROLES", {})
        for name, prompts in user_roles.items():
            if name not in ROLES:
                ROLES[name] = prompts
        if data.get("CURRENT_ROLE") in ROLES:
            CURRENT_ROLE = data["CURRENT_ROLE"]
            SYSTEM_PROMPTS = ROLES[CURRENT_ROLE]
    except Exception:
        pass


def save_user_config():
    os.makedirs(KERKER_HOME, exist_ok=True)
    data = {key: globals()[key] for key in _PERSIST_KEYS}
    user_roles = {name: prompts for name, prompts in ROLES.items() if name not in _BUILTIN_ROLES}
    if user_roles:
        data["USER_ROLES"] = user_roles
    data["ALL_ROLES"] = list(ROLES.keys())
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


load_user_config()
