"""
通用网页抓取模块
适用于 Lex Fridman 等自建博客，也作为兜底方案
"""
import requests
from bs4 import BeautifulSoup
from scrapers.utils import extract_pub_date

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}

# 要移除的无关标签
REMOVE_TAGS = ['script', 'style', 'nav', 'footer', 'header', 'aside',
               'form', 'button', 'iframe', 'noscript']

# 要移除的无关 class 关键词
REMOVE_CLASSES = ['nav', 'menu', 'sidebar', 'footer', 'header', 'ad',
                  'banner', 'cookie', 'popup', 'subscribe', 'social']


def scrape(url):
    """
    通用抓取，自动识别主要内容区域，返回 (text, pub_date) 元组。
    text：页面主要内容纯文本。
    pub_date：文章发布日期，如 'Feb 13, 2026'；获取失败则为空字符串。
    """
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')

    # 在移除 <script> 之前提取发布日期（JSON-LD 在 <script> 里）
    pub_date = extract_pub_date(soup)

    # 移除无关标签
    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()

    # 移除含无关 class 的元素
    for tag in soup.find_all(class_=lambda c: c and any(
        kw in ' '.join(c).lower() for kw in REMOVE_CLASSES
    )):
        tag.decompose()

    # 尝试找主要内容区域（按优先级）
    main_content = (
        soup.find('main') or
        soup.find('article') or
        soup.find('div', id='content') or
        soup.find('div', class_='content') or
        soup.find('div', class_='post') or
        soup.find('div', class_='entry-content') or
        soup.body
    )

    if not main_content:
        raise RuntimeError(f"找不到页面内容：{url}")

    # 用 get_text 获取全部正文（比逐标签过滤更完整）
    raw_text = main_content.get_text(separator='\n', strip=True)

    # 清理多余空行
    lines = [line.strip() for line in raw_text.splitlines()]
    lines = [l for l in lines if len(l) > 5]
    cleaned = '\n\n'.join(lines)

    return cleaned, pub_date
