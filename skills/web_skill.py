"""技能：网页内容摘要"""

import requests
from bs4 import BeautifulSoup
from skills import register


def web_summary(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)
        if len(text) > 8000:
            text = text[:8000] + "\n...[内容过长，已截断]"
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        return f"标题: {title}\n\n{text}" if title else text
    except Exception as e:
        return f"获取网页失败: {e}"


register(
    name="web_summary",
    description="获取指定 URL 网页的文本内容摘要",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要获取的网页 URL",
            }
        },
        "required": ["url"],
    },
    func=web_summary,
)
