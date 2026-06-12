"""
技能：角色蒸馏 —— 通过自然语言描述或真实人物名，搜索多源资料并深度蒸馏为角色 prompt

资料搜集策略（三层）：
1. web_search 搜索引擎 — 覆盖面最广，适合任何人物/角色
2. 百科直取 — Wikipedia/百度百科，结构化信息质量高
3. 语录搜索 — 名人名言、经典语录，捕捉说话风格
"""

import json
import requests
from bs4 import BeautifulSoup
from skills import register


def _fetch_page(url, max_chars=4000):
    """抓取网页文本"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code != 200:
            return ""
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line for line in text.splitlines() if line.strip()]
        content = "\n".join(lines[:200])
        return content[:max_chars]
    except Exception:
        return ""


def _search_persona(name):
    """
    三层资料搜集策略：
    1. web_search 搜索引擎（覆盖面广，适用任何人物/虚构角色）
    2. 百科页面直取（Wikipedia/百度百科，结构化高质量）
    3. 语录搜索（捕捉说话风格特征）
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    collected = []

    search_result = _web_search_persona(name)
    if search_result:
        collected.append(search_result)

    encyclopedia_urls = [
        f"https://zh.wikipedia.org/wiki/{name}",
        f"https://en.wikipedia.org/wiki/{name}",
        f"https://baike.baidu.com/item/{name}",
    ]

    quote_queries = [
        f"{name} 经典语录 名言",
        f"{name} quotes famous sayings",
    ]
    quote_urls = [
        f"https://zh.wikiquote.org/wiki/{name}",
    ]

    with ThreadPoolExecutor(max_workers=6) as pool:
        encyclopedia_futures = {
            pool.submit(_fetch_page, url, 3000): f"百科:{url}"
            for url in encyclopedia_urls
        }
        quote_futures = {
            pool.submit(_fetch_page, url, 2000): f"语录:{url}"
            for url in quote_urls
        }
        quote_search_futures = {
            pool.submit(_web_search_quotes, q): f"语录搜索:{q}"
            for q in quote_queries
        }

        all_futures = {**encyclopedia_futures, **quote_futures, **quote_search_futures}

        encyclopedia_results = []
        quote_results = []

        for future in as_completed(all_futures, timeout=12):
            source = all_futures[future]
            try:
                content = future.result()
                if not content or len(content) < 80:
                    continue
                if source.startswith("百科"):
                    encyclopedia_results.append(content)
                else:
                    quote_results.append(content)
            except Exception:
                continue

    if encyclopedia_results:
        collected.append(encyclopedia_results[0])

    if quote_results:
        collected.append(quote_results[0][:2000])

    return "\n\n---\n\n".join(collected) if collected else ""


def _web_search_persona(name):
    """通过 web_search 技能搜索人物资料，并抓取最相关的结果"""
    from skills.web_skill import web_search, web_summary, _is_safe_url

    search_queries = [
        f"{name} 生平 简介 性格 风格",
        f"{name} biography personality style",
    ]

    results_text = []
    for query in search_queries:
        result = web_search(query)
        if result and "未找到" not in result and "出错" not in result:
            results_text.append(result)
            break

    if not results_text:
        return ""

    urls_to_read = []
    for line in results_text[0].split("\n"):
        line = line.strip()
        if line.startswith("http"):
            urls_to_read.append(line)
        elif "http" in line:
            parts = line.split()
            for part in parts:
                if part.startswith("http"):
                    urls_to_read.append(part)
                    break

    detail = ""
    for url in urls_to_read[:2]:
        if _is_safe_url(url):
            page = web_summary(url)
            if page and "安全限制" not in page and "失败" not in page and len(page) > 100:
                detail = page
                break

    output = results_text[0][:2000]
    if detail:
        output += f"\n\n[详细资料]\n{detail[:3000]}"
    return output


def _web_search_quotes(query):
    """通过 web_search 搜索人物语录"""
    from skills.web_skill import web_search
    result = web_search(query)
    if result and "未找到" not in result and "出错" not in result:
        return result[:2000]
    return ""


_DISTILL_PROMPT = """\
你是一个角色蒸馏专家。根据以下关于"{name}"的资料，深度提取核心特征，生成一组 system prompt。

资料：
{material}

用户额外描述：
{description}

请从以下 7 个维度深度提取特征：
1. 身份定位：职业、头衔、时代背景、成就
2. 说话风格：语气、常用句式、口头禅、修辞偏好（比喻/反讽/排比/设问等）
3. 思维方式：分析问题的角度、逻辑风格、是否跳跃性思维
4. 性格标签：3-5个核心性格词（如：犀利、深刻、悲悯、偏执、极简）
5. 知识领域：擅长话题、专业背景、常引用的领域
6. 价值观：核心信念、反对什么、坚持什么
7. 互动习惯：回答方式（直接/迂回/反问）、是否爱举例、是否用隐喻

输出严格 JSON，不要输出其他内容：
{{"role_name": "角色名称", "prompts": ["prompt1", "prompt2", ...], "greeting": "角色开场白(1-2句，完全用角色口吻)"}}

要求：
- prompts 包含 5-8 条具体指令，每条针对一个维度
- 必须具体到语言细节，禁止泛泛而谈（如"说话有个性"这种无用描述）
- 好的例子："你说话时喜欢用短句，常以反问收尾，偶尔夹杂文言词汇"
- greeting 要让人一读就能辨认出是谁，体现最标志性的表达特征
- 使用中文\
"""


def distill_role(name, description=""):
    """
    角色蒸馏：搜索多源资料，提取性格/风格/思维等7维度特征，生成角色prompt。
    name: 角色/人物名称
    description: 额外描述（可选）
    返回 JSON 字符串
    """
    material = _search_persona(name)

    if not material and not description:
        material = (
            f"没有找到关于 {name} 的公开资料（搜索引擎和百科均无结果）。"
            f"请根据名称含义、文化背景和常见认知创造角色。"
        )

    prompt = _DISTILL_PROMPT.format(
        name=name,
        material=material[:6000] if material else "(无搜索结果)",
        description=description or "(无额外描述)",
    )

    try:
        from openai import OpenAI
        from core import config
        from core.credentials import load_api_key

        client = OpenAI(api_key=load_api_key(), base_url=config.BASE_URL)
        response = client.chat.completions.create(
            model=config.MODEL,
            messages=[
                {"role": "system", "content": "你是角色蒸馏专家，只输出 JSON，不要解释。"},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )
        result_text = response.choices[0].message.content or ""

        from agents import _extract_first_json
        json_str = _extract_first_json(result_text)
        if json_str:
            data = json.loads(json_str)
            if "prompts" in data and len(data.get("prompts", [])) >= 3:
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
        "角色蒸馏：根据人物/角色名称搜索多源资料，"
        "深度提取特征并生成角色 system prompt。"
        "适用于创建新角色。调用后必须紧接着调用 save_distilled_role 保存结果。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "角色或人物名称，如'鲁迅'、'乔布斯'、'苏格拉底'",
            },
            "description": {
                "type": "string",
                "description": "用户对角色的额外描述，如'更幽默一些'、'说话犀利'",
            },
        },
        "required": ["name"],
    },
    func=distill_role,
)
