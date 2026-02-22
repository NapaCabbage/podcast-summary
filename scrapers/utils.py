"""
爬虫共享工具函数
"""
import json
from datetime import datetime


def format_pub_date(date_str):
    """将 ISO 日期字符串（或其他格式）转为 'Feb 13, 2026' 格式"""
    if not date_str:
        return ''
    # 只取前 10 位 YYYY-MM-DD
    raw = date_str.strip()[:10]
    try:
        dt = datetime.strptime(raw, '%Y-%m-%d')
        return dt.strftime('%b %d, %Y')
    except ValueError:
        return date_str.strip()


def extract_pub_date(soup):
    """
    从 BeautifulSoup 对象中提取发布日期，按优先级尝试多种来源。
    返回格式化后的日期字符串，如 'Feb 13, 2026'；失败则返回空字符串。

    注意：调用此函数前不要删除 <script> 标签，否则 JSON-LD 会被清除。
    """
    # 1. JSON-LD 结构化数据（最可靠）
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            # 可能是列表或单对象
            if isinstance(data, list):
                data = data[0] if data else {}
            date = data.get('datePublished') or data.get('uploadDate')
            if date:
                return format_pub_date(date)
        except Exception:
            continue

    # 2. <meta> Open Graph / Twitter / itemprop
    for attr, keys in [
        ('property', ['article:published_time', 'og:published_time']),
        ('name',     ['publish_date', 'date', 'DC.date.issued']),
        ('itemprop', ['datePublished', 'uploadDate']),
    ]:
        for key in keys:
            meta = soup.find('meta', {attr: key})
            if meta and meta.get('content'):
                return format_pub_date(meta['content'])

    # 3. <time> 标签的 datetime 属性
    time_tag = soup.find('time', attrs={'datetime': True})
    if time_tag:
        return format_pub_date(time_tag['datetime'])

    return ''
