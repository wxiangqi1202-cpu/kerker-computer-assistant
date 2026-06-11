"""
技能：角色蒸馏 —— 通过自然语言描述或真实人物名，自动搜索资料并蒸馏为角色 prompt
用户在对话中说"帮我创建一个xxx角色"时，主模型调用此技能。
"""

import json
import requests
from bs4 import BeautifulSoup
from skills import register


def _search_persona(name):
    """搜索人物/角色的公开资料，提取性格特征描述"""
    urls = [
        f"https://zh.wikipedia.org/wiki/{name}",
        f"https://en.wikipedia.org/wiki/{name}",
        f"https://baike.baidu.com/item/{name}",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    collected = []

    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                continue
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            lines = [line for line in text.splitlines() if line.strip()]
            content = "\n".join(lines[:150])
            if len(content) > 3000:
                content = content[:3000]
            collected.append(content)
            if len(collected) >= 2:
                break
        except Exception:
            continue

    return "\n\n---\n\n".join(collected) if collected else ""


_DISTILL_PROMPT = """\
你是一个角色蒸馏专家。根据以下关于"{name}"的资料，提取这个人/角色的核心特征，生成一组 system prompt 用于让 AI 扮演这个角色。

资料：
{material}

用户的额外描述：
{description}

请输出严格的 JSON 格式，不要输出其他内容：
{{"role_name": "角色名称", "prompts": ["prompt1", "prompt2", ...], "greeting": "角色的开场自我介绍(1-2句话)"}}

要求：
- prompts 包含 3-6 条指令，涵盖：身份定位、说话风格、知识领域、行为习惯
- 如果是真实人物，捕捉其标志性的语言风格和思维方式
- 如果是虚构角色或自定义描述，根据描述创造合理的人设
- greeting 是角色切换后的第一句话，要符合角色性格
- 使用中文\
"""


def distill_role(name, description=""):
    """
    角色蒸馏：根据名称搜索资料，提取特征，生成角色 prompt。
    name: 角色/人物名称
    description: 用户对角色的额外描述（可选）
    返回 JSON 字符串：{"role_name": "...", "prompts": [...], "greeting": "..."}
    """
    material = _search_persona(name)

    if not material and not description:
        material = f"没有找到关于 {name} 的公开资料。请根据名称本身的含义来创造角色。"

    prompt = _DISTILL_PROMPT.format(
        name=name,
        material=material[:4000] if material else "(无搜索结果)",
        description=description or "(无额外描述)",
    )

    try:
        from openai import OpenAI
        from core import config
        from core.credentials import load_api_key

        client = OpenAI(api_key=load_api_key(), base_url=config.BASE_URL)
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "你是角色蒸馏专家，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )
        result_text = response.choices[0].message.content or ""

        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(result_text[start:end])
            return json.dumps(data, ensure_ascii=False, indent=2)

        return json.dumps({
            "role_name": name,
            "prompts": [f"你是{name}。{description}" if description else f"你是{name}。"],
            "greeting": f"你好，我是{name}。",
        }, ensure_ascii=False, indent=2)

    except Exception as err:
        return json.dumps({
            "error": str(err),
            "role_name": name,
            "prompts": [f"你是{name}。{description}" if description else f"你是{name}。"],
            "greeting": f"你好，我是{name}。",
        }, ensure_ascii=False, indent=2)


register(
    name="distill_role",
    description=(
        "角色蒸馏：根据人物/角色名称搜索公开资料，提取性格特征和说话风格，"
        "自动生成角色 system prompt。用于用户说'帮我创建一个xxx角色'或'我想和xxx对话'时调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "角色或人物名称，如'鲁迅'、'乔布斯'、'柯南'",
            },
            "description": {
                "type": "string",
                "description": "用户对角色的额外描述，如'更幽默一些'、'专注于技术话题'",
            },
        },
        "required": ["name"],
    },
    func=distill_role,
)
