"""
技能：网页搜索与内容获取
  web_search     — 搜索引擎查询，返回结果标题+摘要+链接
  web_summary    — 获取指定 URL 的文本内容
"""

import subprocess
import ipaddress
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from skills import register


_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]", "metadata.google.internal"}


def _is_safe_url(url):
    """检查 URL 是否安全，阻止 SSRF 攻击"""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host:
            return False
        if host in _BLOCKED_HOSTS:
            return False
        if parsed.scheme not in ("http", "https"):
            return False
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return False
        except ValueError:
            pass
        return True
    except Exception:
        return False


def _bing_search(query, max_results=6):
    """Bing 搜索"""
    url = f"https://www.bing.com/search?q={requests.utils.quote(query)}&setlang=zh-Hans"
    result = subprocess.run(
        ["curl", "-s", "-L", "--max-time", "8", "-H",
         "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36", url],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return None

    soup = BeautifulSoup(result.stdout, "html.parser")
    results = []
    seen_domains = set()

    for item in soup.select("li.b_algo"):
        title_el = item.select_one("h2")
        snippet_el = item.select_one(".b_caption p, .b_lineclamp2")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
        link_el = title_el.select_one("a")
        link = link_el.get("href", "") if link_el else ""

        domain = link.split("/")[2] if link.count("/") >= 2 else ""
        if domain in seen_domains:
            continue
        seen_domains.add(domain)

        results.append({"title": title, "snippet": snippet, "url": link})
        if len(results) >= max_results:
            break

    return results if results else None


def _sogou_search(query, max_results=6):
    """搜狗搜索（Bing 失败时的 fallback）"""
    url = f"https://www.sogou.com/web?query={requests.utils.quote(query)}"
    try:
        result = subprocess.run(
            ["curl", "-s", "-L", "--max-time", "8", "-H",
             "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", url],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None

        soup = BeautifulSoup(result.stdout, "html.parser")
        results = []
        for item in soup.select(".vrwrap, .rb"):
            title_el = item.select_one("h3 a, .vr_title a")
            snippet_el = item.select_one(".str_info, .space-txt, p")
            if title_el:
                title = title_el.get_text(strip=True)
                snippet = snippet_el.get_text(strip=True)[:150] if snippet_el else ""
                link = title_el.get("href", "")
                results.append({"title": title, "snippet": snippet, "url": link})
            if len(results) >= max_results:
                break
        return results if results else None
    except Exception:
        return None


def web_search(query):
    """搜索引擎查询，返回结果标题和摘要（Bing 优先，搜狗 fallback）"""
    try:
        results = _bing_search(query)
        if not results:
            results = _sogou_search(query)
        if not results:
            return f"未找到关于 '{query}' 的搜索结果"

        lines = []
        for r in results:
            lines.append(f"- {r['title']}\n  {r['snippet']}\n  {r['url']}")
        return "\n\n".join(lines)
    except subprocess.TimeoutExpired:
        return "搜索超时"
    except Exception as e:
        return f"搜索出错: {e}"


def web_summary(url):
    """获取指定 URL 网页的文本内容"""
    if not _is_safe_url(url):
        return f"安全限制: 不允许访问该 URL（内网/受限地址）: {url}"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)

        if len(text) < 50:
            return f"该页面内容极少（可能是 JS 动态渲染），建议用 web_search 搜索相关信息。URL: {url}"

        if len(text) > 4000:
            text = text[:4000] + "\n...[已截断]"
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        return f"标题: {title}\n\n{text}" if title else text
    except requests.Timeout:
        return f"获取超时: {url}"
    except Exception as e:
        return f"获取网页失败: {e}"


def web_search_and_read(query):
    """搜索并自动读取第一条结果的详细内容（一步到位）"""
    try:
        results = _bing_search(query, max_results=3)
        if not results:
            results = _sogou_search(query, max_results=3)
        if not results:
            return f"未找到关于 '{query}' 的搜索结果"

        summary_lines = ["搜索结果:"]
        for r in results:
            summary_lines.append(f"- {r['title']}: {r['snippet'][:80]}")

        first_url = results[0].get("url", "")
        detail = ""
        if first_url and not first_url.startswith("javascript"):
            detail = web_summary(first_url)

        output = "\n".join(summary_lines)
        if detail and "内容极少" not in detail and "失败" not in detail:
            output += f"\n\n--- 详细内容（{results[0]['title']}）---\n{detail}"

        return output
    except Exception as e:
        return f"搜索并读取失败: {e}"


register(
    name="web_search",
    description=(
        "联网搜索：通过搜索引擎查找信息，返回搜索结果的标题、摘要和链接。"
        "需要获取实时信息、最新动态、查询事实时使用。"
        "不需要知道具体 URL，只需提供关键词。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
        },
        "required": ["query"],
    },
    func=web_search,
)

register(
    name="web_search_and_read",
    description=(
        "搜索并阅读：搜索关键词，返回搜索结果摘要 + 自动读取第一条结果的详细内容。"
        "当用户需要深入了解某个话题时使用（比 web_search 更详细，但也更慢）。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
        },
        "required": ["query"],
    },
    func=web_search_and_read,
)

register(
    name="web_summary",
    description=(
        "获取指定 URL 网页的文本内容摘要。"
        "当已经知道具体 URL 需要读取详情时使用。"
        "如果不知道 URL，应先用 web_search 搜索。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要获取的网页 URL"},
        },
        "required": ["url"],
    },
    func=web_summary,
)
