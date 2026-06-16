# KerKer

> 面向计算加速的多智能体 CLI 框架

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)
![Version](https://img.shields.io/badge/version-0.2.0-orange)

KerKer 是一个运行在终端里的 AI 编程助手与多智能体协作框架，专为计算加速（昇腾 AscendC 算子开发）和日常编程工作流设计。它不是一个网页应用，而是一个深度集成进你的终端的 AI 工作伙伴。

```
  ██╗  ██╗███████╗██████╗ ██╗  ██╗███████╗██████╗
  ██║ ██╔╝██╔════╝██╔══██╗██║ ██╔╝██╔════╝██╔══██╗
  █████╔╝ █████╗  ██████╔╝█████╔╝ █████╗  ██████╔╝
  ██╔═██╗ ██╔══╝  ██╔══██╗██╔═██╗ ██╔══╝  ██╔══██╗
  ██║  ██╗███████╗██║  ██║██║  ██╗███████╗██║  ██║
  ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
  Computational Agent Framework  v0.2.0
```



## ✨ 功能亮点

| 亮点 | 说明 |
|---|---|
| 🤖 **多智能体协作** | Planner 自动拆解任务，Research / CodeReview / AscendDev 并行或串行执行 |
| 🎭 **角色蒸馏** | 说出人名，AI 自动搜索多源资料并提炼 7 维度人格 Prompt，一键变身任意角色 |
| 🧠 **持久化记忆** | TF-IDF 语义记忆 + 情景记忆，跨会话记住你的偏好和项目背景 |
| 🖥️ **沉浸式终端 UI** | 流畅 Markdown 渲染、代码高亮、任务进度面板、可视化 token 用量状态栏 |
| ⚡ **昇腾专项支持** | 内置 AscendC 算子开发 / 调试 Agent，覆盖编译、运行、精度诊断全流程 |
| 🔌 **技能可扩展** | 在 `~/.kerker/skills/` 放一个 `.py` 文件即可注册新工具，无需改动框架代码 |
| 🔒 **分层安全防护** | Shell 执行门控、敏感路径白名单、Web 内容 Prompt 注入防御、技能文件权限校验 |
| 💾 **对话连续性** | ESC 随时中断，`/resume` 断点续接；自动保存历史，会话可恢复 |



## 🚀 快速开始

### 环境要求

- Python 3.9+
- macOS / Linux（Windows 支持基础功能，Shell 技能需要 WSL）

### 安装

```bash
# 克隆项目
git clone https://github.com/wxiangqi1202-cpu/kerker-computer-assistant
cd kerker-computer-assistant

# 安装依赖（推荐使用虚拟环境）
pip install -e .

# 安装精确 token 计数支持（可选）
pip install -e ".[precise]"
```

### 首次启动

```bash
kerker          # pip install 后
# 或
python main.py
```

首次运行会自动弹出配置向导，引导你填写 API Key 并选择默认模式。也可以提前设置环境变量跳过：

```bash
export DEEPSEEK_API_KEY=sk-xxxxxxxx
kerker
```



## 💬 对话与命令

直接输入自然语言即可与 KerKer 对话。以 `/` 开头的输入是命令：

```
/help          查看所有命令
/fast          切换极速模式（flash + 关思考）
/deep          切换深度模式（pro + 开思考）
/model         交互式切换模型
/role          切换 / 新建角色
/statusbar     切换状态栏 token 用量样式（8 种）
/theme         切换 Markdown 渲染主题
/welcome       切换启动页风格
/memory        查看 / 管理持久记忆
/resume        恢复上次对话 / 断点续接 / 搜索历史
/config        查看 / 修改运行配置
/metrics       查看本次会话性能统计
/agents        查看已加载子智能体
/skills        查看已加载技能
/clear         清空当前对话上下文
/exit          退出程序
```

**多行输入**：以 `"""` 开头，再次输入 `"""` 结束，适合粘贴大段代码或文本。

**中断**：任意时刻按 `ESC` 停止响应，输入 `/resume` 可从断点续接。



## 🤖 多智能体系统

KerKer 内置一套 **Planner-Executor** 多智能体框架。对于复杂任务，主模型会自动调用 Planner 拆解步骤，再依次调度专项 Agent 执行。

```
用户输入
  └─ 主模型（路由判断）
       ├─ 简单任务 → 直接回答
       └─ 复杂任务 → agent_planner 拆解
            ├─ agent_researcher     联网搜索 + 资料整理
            ├─ agent_code_reviewer  代码审查 + Bug 分析
            ├─ agent_ascend_dev     AscendC 算子开发
            └─ agent_ascend_debug   算子编译/运行时诊断
```

**任务进度面板**实时显示每个步骤的执行状态（`○ pending` → `◎ running` → `✓ done`），执行完成后有汇聚动画。

**示例**：

```
你 › 帮我写一个 AscendC 的 ReLU 算子，包含 Tiling 方案和测试代码

  › 任务规划 (3 步)
    ✓ 设计 Tiling 方案
    ◎ 生成算子代码
    ○ 编写测试用例
```



## 🧰 内置技能

| 技能 | 触发示例 | 说明 |
|---|---|---|
| `web_search` | "搜索最新的 PyTorch 版本" | Bing 优先，搜狗 fallback |
| `web_search_and_read` | "深入了解 AscendC DataCopy" | 搜索 + 自动阅读首条详情 |
| `web_summary` | 给出 URL | 获取指定网页正文 |
| `run_shell` | "运行 `ls -la`" | 执行 Shell 命令（可通过 `/config shell` 开关） |
| `read_file` | "读取 main.py" | 读取本地文件 |
| `write_file` | "把这段代码写入 test.py" | 写入本地文件（5MB 上限） |
| `calculate` | "1234 * 5678 + 9" | AST 安全沙箱计算 |
| `get_current_time` | "现在几点" | 获取系统时间 |
| `get_weather` | "北京今天天气" | 查询天气 |
| `remember` | "记住我用 Python 3.12" | 写入持久记忆 |
| `forget` | "忘掉关于密码的记忆" | 删除记忆条目 |
| `recall` | 自动触发 | 检索相关历史记忆 |
| `switch_role` | "切换到代码助手" | 切换当前角色 |
| `distill_role` | "用鲁迅的风格" | 多源资料蒸馏角色 Prompt |
| `npu_info` | "查看 NPU 状态" | 调用 npu-smi 查询昇腾设备 |
| `ascend_build` | "编译算子项目" | cmake + make 自动构建 |
| `ascend_run` | "运行 ./build/relu_test" | 自动配置环境变量并运行 |

### 自定义技能

在 `~/.kerker/skills/` 新建一个 `.py` 文件：

```python
# ~/.kerker/skills/my_tool.py
from skills import register

def hello(name):
    return f"Hello, {name}!"

register(
    name="hello",
    description="打招呼工具",
    parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    func=hello,
)
```

重启 KerKer 后自动加载，LLM 可直接调用。文件权限需为当前用户所有且不可被他人写入。



## 🎭 角色系统

KerKer 内置五种角色，通过 `/role` 命令切换：

| 角色 | 定位 |
|---|---|
| **默认** | 通用助手，均衡能力 |
| **代码助手** | 优先给出代码示例，快速定位 Bug |
| **翻译官** | 中英互译，自然流畅 |
| **写作助理** | 文章润色，逻辑与表达并重 |
| **算子开发** | AscendC 专家，内置开发规范约束 |

### 角色蒸馏（核心亮点）

无需手写 Prompt，只需告诉 KerKer 你想要哪种风格：

```
你 › 帮我创建一个鲁迅风格的角色
```

KerKer 会自动：
1. 通过搜索引擎、Wikipedia、语录网站收集多源资料（并发抓取）
2. 从 7 个维度（说话风格、思维方式、价值观、知识领域……）深度提炼
3. 生成专属 Prompt 并立即切换

也支持自定义增强：`"帮我创建一个更犀利一些的乔布斯角色"`



## 🧠 记忆系统

KerKer 有两层记忆，存储在 `~/.kerker/memory/`：

**语义记忆**（长期）
- 记住用户偏好、项目背景、个人习惯
- 基于 TF-IDF 的语义搜索，中英文混合分词
- 每次对话启动时自动注入最相关的 8 条到上下文

**情景记忆**（历史索引）
- 自动为每次对话生成摘要并建立关键词索引
- 支持 `/resume search <关键词>` 快速翻找历史对话

```
你 › 记住我的项目用 Python 3.12，框架是 PyTorch 2.3
KerKer › 已记住：项目使用 Python 3.12，PyTorch 2.3

# 下次对话，KerKer 会自动知道这些背景
```



## 🎨 个性化

**渲染主题**（`/theme`）：`minimal`（默认）/ `warm` / `plain`

**启动页风格**（`/welcome`）：
- `cyber` — ASCII Art 赛博风格（默认）
- `hologram` — 全息投影动画
- `typewriter` — 打字机动画

**状态栏样式**（`/statusbar`）：8 种 token 用量展示风格，从纯文字到进度条到 Badge，颜色随用量渐变（绿→黄→橙→红）：

```
A  ─── deepseek-v4-flash · 默认 · 14 tools · 3.2k/48k ctx ───
B  ─── deepseek-v4-flash · 默认 · 14 tools · [███░░░░░░░] 30% ───
E  ─── deepseek-v4-flash · 默认 · 14 tools · ◔ 3.2k/48k ───
H  ─── deepseek-v4-flash · 默认 · 14 tools ───  （安静模式，超限才显示）
```



## ⚙️ 配置参考

所有配置存储在 `~/.kerker/config.json`，可通过 `/config` 命令修改：

| 键 | 默认值 | 说明 |
|---|---|---|
| `MODEL` | `deepseek-v4-flash` | 使用的模型 |
| `STREAM` | `true` | 流式输出 |
| `ENABLE_THINKING` | `false` | 深度思考模式 |
| `REASONING_EFFORT` | `low` | 推理强度 `low/medium/high` |
| `MAX_CONTEXT_MESSAGES` | `40` | 上下文消息数上限 |
| `AUTO_ROUTE` | `true` | 自动路由（智能判断是否调 Planner） |
| `ALLOW_SHELL` | `true` | 允许 LLM 执行 Shell 命令 |
| `STATUSBAR_STYLE` | `a` | 状态栏样式 `a`~`h` |
| `CURRENT_ROLE` | `默认` | 当前角色 |

**快捷预设**：

```bash
/fast    # deepseek-v4-flash + 关闭思考（速度优先）
/deep    # deepseek-v4-pro + 开启深度思考（质量优先）
```

**添加自定义模型**（在 config.json 中）：

```json
{
  "USER_ROLES": {
    "我的角色": ["你是一个专注于 XX 领域的助手。", "简洁回答。"]
  }
}
```



## 🔒 安全说明

KerKer 在多个层面内置了安全防护：

- **Shell 门控**：`/config shell false` 可完全禁用 Shell 执行能力；危险命令（`rm -rf`、`sudo`、`curl | bash` 等）在非交互模式下自动拦截，交互模式下需二次确认
- **文件访问保护**：`~/.ssh`、`~/.aws`、`~/.config/gh`、`~/.docker` 等凭证路径受保护；写入操作有 5MB 上限
- **Prompt 注入防御**：Web 抓取内容自动标注 `[外部内容]`，System Prompt 层面明确指示 LLM 忽略外部注入指令
- **用户技能校验**：加载 `~/.kerker/skills/` 中的自定义技能前，校验文件所有权和写权限（Unix）
- **API Key 安全**：优先读取环境变量 `DEEPSEEK_API_KEY`，文件存储时自动设置 `chmod 600`

> 建议在不需要 Shell 功能时通过 `/config shell false` 关闭，以降低误操作风险。



## 📋 命令速查

```
对话操作
  ESC               中断当前响应
  """               开始多行输入（再次 """ 结束）
  /resume           恢复上次对话 / 断点续接 / 搜索历史
  /clear            清空当前上下文
  /exit             退出

模型 & 模式
  /fast             极速模式
  /deep             深度思考模式
  /model            切换模型
  /config           查看/修改配置

角色 & 记忆
  /role             切换/新建角色
  /memory           查看/清空记忆
  /memory clear     清空所有记忆

外观
  /statusbar        切换状态栏样式（a~h）
  /theme            切换渲染主题
  /welcome          切换启动页风格

信息
  /help             帮助
  /agents           查看子智能体
  /skills           查看已加载技能
  /metrics          性能统计
```



## License

MIT © 王祥祺
