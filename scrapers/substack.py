"""
Substack 文章抓取模块
适用于 dwarkesh.com、latent.space 等 Substack 托管网站
"""
import requests
from bs4 import BeautifulSoup
from scrapers.utils import extract_pub_date

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}


def scrape(url):
    """
    抓取 Substack 文章正文，返回 (text, pub_date) 元组。
    text：包含标题、简介、完整正文（通常含文字稿）。
    pub_date：文章发布日期，如 'Feb 13, 2026'；获取失败则为空字符串。
    """
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')

    # 在移除任何标签之前提取发布日期（JSON-LD 在 <script> 里）
    pub_date = extract_pub_date(soup)

    # 提取标题
    title = ''
    h1 = soup.find('h1')
    if h1:
        title = h1.get_text(strip=True)

    # 提取副标题
    subtitle = ''
    sub = soup.find('h3', class_='subtitle') or soup.find('div', class_='subtitle')
    if sub:
        subtitle = sub.get_text(strip=True)

    # 提取正文：Substack 的内容区域
    content_div = (
        soup.find('div', class_='available-content') or
        soup.find('div', class_='post-content') or
        soup.find('div', {'class': lambda c: c and 'body' in c.lower()}) or
        soup.find('article')
    )

    if not content_div:
        raise RuntimeError(f"找不到正文内容，请检查 URL 是否正确：{url}")

    # 移除不需要的元素（按钮、订阅提示等）
    for tag in content_div.find_all(['button', 'script', 'style']):
        tag.decompose()
    for tag in content_div.find_all(class_=lambda c: c and any(
        kw in c for kw in ['paywall', 'subscribe', 'cta', 'button']
    )):
        tag.decompose()

    # 提取结构化文本（保留段落和标题的换行）
    parts = []
    for elem in content_div.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li']):
        text = elem.get_text(strip=True)
        if text:
            if elem.name in ['h1', 'h2', 'h3', 'h4']:
                parts.append(f'\n## {text}\n')
            else:
                parts.append(text)

    body = '\n\n'.join(parts)

    result = []
    if title:
        result.append(f'# {title}')
    if subtitle:
        result.append(subtitle)
    result.append(body)

    return '\n\n'.join(result), pub_date
