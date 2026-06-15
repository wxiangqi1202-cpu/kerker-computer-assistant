"""
集中配置 —— Config 单例类 + ~/.kerker/config.json 持久化
"""

import os
import json


class Config:
    KERKER_HOME = os.path.expanduser("~/.kerker")
    HISTORY_DIR = os.path.join(KERKER_HOME, "history")
    USER_SKILLS_DIR = os.path.join(KERKER_HOME, "skills")
    CONFIG_FILE = os.path.join(KERKER_HOME, "config.json")

    MODELS = {
        "deepseek-v4-pro": {"name": "DeepSeek V4 Pro", "base_url": "https://api.deepseek.com"},
        "deepseek-v4-flash": {"name": "DeepSeek V4 Flash", "base_url": "https://api.deepseek.com"},
        "deepseek-reasoner": {"name": "DeepSeek Reasoner", "base_url": "https://api.deepseek.com"},
    }

    PRESETS = {
        "fast": {"MODEL": "deepseek-v4-flash", "ENABLE_THINKING": False, "REASONING_EFFORT": "low"},
        "deep": {"MODEL": "deepseek-v4-pro", "ENABLE_THINKING": True, "REASONING_EFFORT": "high"},
        "reason": {"MODEL": "deepseek-reasoner", "ENABLE_THINKING": True, "REASONING_EFFORT": "high"},
    }

    AGENT_DIRECTIVE = (
        "重要：你拥有多个子智能体工具（agent_planner, agent_researcher 等）。"
        "对于复杂任务，先调用 agent_planner 进行任务规划，"
        "然后严格按照规划的步骤顺序，逐个调用相应的子智能体执行。"
        "每次只调用一个子智能体，等它返回结果后再调用下一个。"
        "全部步骤完成后再给出最终总结回复。"
    )

    TOOL_DIRECTIVE = (
        "你拥有多种工具。当用户询问需要实时信息的问题时，"
        "必须主动调用相应工具获取信息后再回答，不要猜测或询问用户。"
        "工具选择指南：\n"
        "- 需要搜索/查询/最新信息 → 调 web_search（只需关键词，不需要 URL）\n"
        "- 需要深入了解某话题 → 调 web_search_and_read（搜索+阅读详情）\n"
        "- 已知具体 URL 要读内容 → 调 web_summary\n"
        "- 问时间 → 调 get_current_time\n"
        "- 问天气 → 调 get_weather\n"
        "- 操作文件 → 调 read_file / write_file\n"
        "- 执行命令 → 调 run_shell\n"
        "重要：需要搜索信息时必须用 web_search，不要自己编造 URL。"
    )

    EXPLORE_DIRECTIVE = (
        "重要行为准则：当你不确定如何完成用户的请求时，绝对不要直接说'做不到'或'没有这个功能'。"
        "你应该主动使用 run_shell 工具探索解决方案：\n"
        "1. 用 which/where/command -v 检查系统上是否有相关命令\n"
        "2. 用 ls/find 查看是否有相关配置文件或工具\n"
        "3. 用 --help 查看已安装工具的用法\n"
        "4. 用 pip3 list/npm list -g 检查已安装的包\n"
        "5. 尝试执行命令看看结果\n"
        "只有在尝试探索后确认没有可行方案时，才告知用户并给出替代建议。"
    )

    DIRECTIVE_PROFILES = {
        "full": ["TOOL_DIRECTIVE", "EXPLORE_DIRECTIVE", "AGENT_DIRECTIVE"],
        "tool_only": ["TOOL_DIRECTIVE"],
        "agent_focus": ["TOOL_DIRECTIVE", "AGENT_DIRECTIVE"],
        "minimal": [],
    }

    _BUILTIN_ROLES = None
    _PERSIST_KEYS = ("MODEL", "CURRENT_ROLE", "STREAM", "REASONING_EFFORT",
                     "ENABLE_THINKING", "MAX_CONTEXT_MESSAGES", "AUTO_ROUTE")

    def __init__(self):
        self.MODEL = "deepseek-v4-flash"
        self.BASE_URL = "https://api.deepseek.com"
        self.STREAM = True
        self.REASONING_EFFORT = "low"
        self.ENABLE_THINKING = False
        self.MAX_TOKENS = None
        self.MAX_CONTEXT_MESSAGES = 40
        self.AUTO_ROUTE = True
        self.CURRENT_ROLE = "默认"
        self.ROLES = self._build_default_roles()
        self.SYSTEM_PROMPTS = self.ROLES[self.CURRENT_ROLE]
        self._BUILTIN_ROLES = set(self.ROLES.keys())

    def _build_default_roles(self):
        return {
            "默认": [
                "请简洁回答，控制在3-5句话以内，除非用户要求详细展开。",
                "请谨记：你是由王祥祺制作出来的面向计算加速的Agent框架，名字叫做KerKer。回答时不要对名字加粗或添加任何格式修饰。",
                "回答使用中文。",
                "要更具备幽默感，但要注意场合，不要过于随意。",
                self.TOOL_DIRECTIVE,
                self.EXPLORE_DIRECTIVE,
                self.AGENT_DIRECTIVE,
            ],
            "代码助手": [
                "你是 KerKer 代码助手，专注于编程问题。",
                "回答时优先给出代码示例，辅以简洁的中文解释。",
                "如果用户的代码有 bug，先指出问题再给修复方案。",
                self.TOOL_DIRECTIVE,
                self.EXPLORE_DIRECTIVE,
                self.AGENT_DIRECTIVE,
            ],
            "翻译官": [
                "你是 KerKer 翻译助手。",
                "用户输入中文时翻译为英文，输入英文时翻译为中文。",
                "翻译要自然流畅，不要逐字翻译，必要时解释关键术语。",
                self.TOOL_DIRECTIVE,
            ],
            "写作助理": [
                "你是 KerKer 写作助理，帮助用户改进文章和文案。",
                "关注文字的流畅性、逻辑性和表达力。",
                "给出修改建议时，说明理由并提供改写示例。",
                self.TOOL_DIRECTIVE,
            ],
            "算子开发": [
                "你是 KerKer 昇腾算子开发专家，专注于 AscendC 算子开发。",
                "熟练掌握 AscendC API、DataCopy 对齐规范、Tiling 方案设计。",
                "遵循开发规范：禁用 C 标准库数学函数、32 字节对齐、先跑通再优化。",
                "回答使用中文，给出可直接使用的代码示例。",
                "遇到复杂任务时，会调度 ascend_dev 和 ascend_debug 子智能体协助。",
                self.TOOL_DIRECTIVE,
                self.EXPLORE_DIRECTIVE,
                self.AGENT_DIRECTIVE,
            ],
        }

    def apply_preset(self, name):
        if name not in self.PRESETS:
            return False
        preset = self.PRESETS[name]
        self.MODEL = preset["MODEL"]
        self.BASE_URL = self.MODELS[self.MODEL]["base_url"]
        self.ENABLE_THINKING = preset["ENABLE_THINKING"]
        self.REASONING_EFFORT = preset["REASONING_EFFORT"]
        self.save_user_config()
        return True

    def get_model_base_url(self, model=None):
        """获取指定模型的 base_url，支持 per-model provider 配置"""
        model = model or self.MODEL
        model_info = self.MODELS.get(model, {})
        return model_info.get("base_url", self.BASE_URL)

    def set_model_provider(self, model, base_url):
        """为指定模型设置独立的 provider base_url"""
        if model in self.MODELS:
            self.MODELS[model]["base_url"] = base_url
        else:
            self.MODELS[model] = {"name": model, "base_url": base_url}
        self.save_user_config()

    def get_directives_for_route(self, route_action=None):
        """
        根据路由决策返回应注入的 directive 列表。
        - PLAN/SINGLE_AGENT: full（需要工具+探索+agent 指令）
        - DIRECT + 复杂度 > 0: tool_only（可能需要工具）
        - DIRECT + 简单对话: minimal（节省 token）
        """
        if route_action in ("plan", "single_agent"):
            profile = "full"
        elif route_action == "direct":
            profile = "tool_only"
        else:
            profile = "full"

        directive_names = self.DIRECTIVE_PROFILES.get(profile, self.DIRECTIVE_PROFILES["full"])
        return [getattr(self, name) for name in directive_names if hasattr(self, name)]

    def load_user_config(self):
        if not os.path.isfile(self.CONFIG_FILE):
            return
        try:
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("MODEL") in self.MODELS:
                self.MODEL = data["MODEL"]
                self.BASE_URL = self.MODELS[self.MODEL]["base_url"]
            if "STREAM" in data:
                self.STREAM = bool(data["STREAM"])
            if "REASONING_EFFORT" in data:
                self.REASONING_EFFORT = data["REASONING_EFFORT"]
            if "ENABLE_THINKING" in data:
                self.ENABLE_THINKING = bool(data["ENABLE_THINKING"])
            if "MAX_CONTEXT_MESSAGES" in data:
                self.MAX_CONTEXT_MESSAGES = int(data["MAX_CONTEXT_MESSAGES"])
            if "AUTO_ROUTE" in data:
                self.AUTO_ROUTE = bool(data["AUTO_ROUTE"])
            user_roles = data.get("USER_ROLES", {})
            for name, prompts in user_roles.items():
                if name not in self.ROLES:
                    self.ROLES[name] = prompts
            if data.get("CURRENT_ROLE") in self.ROLES:
                self.CURRENT_ROLE = data["CURRENT_ROLE"]
                self.SYSTEM_PROMPTS = self.ROLES[self.CURRENT_ROLE]
        except Exception:
            pass

    def save_user_config(self):
        os.makedirs(self.KERKER_HOME, exist_ok=True)
        data = {key: getattr(self, key) for key in self._PERSIST_KEYS}
        user_roles = {n: p for n, p in self.ROLES.items() if n not in self._BUILTIN_ROLES}
        if user_roles:
            data["USER_ROLES"] = user_roles
        data["ALL_ROLES"] = list(self.ROLES.keys())
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


config = Config()
config.load_user_config()

KERKER_HOME = config.KERKER_HOME
HISTORY_DIR = config.HISTORY_DIR
USER_SKILLS_DIR = config.USER_SKILLS_DIR
CONFIG_FILE = config.CONFIG_FILE
MODELS = config.MODELS
PRESETS = config.PRESETS
ROLES = config.ROLES
