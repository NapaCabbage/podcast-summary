"""
RSS / Atom Feed 解析模块
适用于 Lex Fridman、Latent Space、Dwarkesh 等有 Feed 的来源
用法：直接调用 fetch_episodes(feed_url, max_count)
"""
import feedparser
from datetime import datetime


def fetch_episodes(feed_url, max_count=5):
    """
    解析 RSS/Atom Feed，返回最新 max_count 条集数。
    返回：[(title, url, pub_date_str), ...]
    pub_date_str 格式如 'Feb 12, 2026'；获取失败为空字符串。
    """
    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        raise RuntimeError(
            f"无法解析 Feed：{feed_url}（{feed.get('bozo_exception', '未知错误')}）"
        )

    results = []
    for entry in feed.entries[:max_count]:
        title = entry.get('title', '').strip()

        # 获取文章 URL（RSS 2.0 用 link，Atom 可能在 links 数组里）
        url = entry.get('link', '').strip()
        if not url:
            for link in entry.get('links', []):
                if link.get('rel') == 'alternate':
                    url = link.get('href', '').strip()
                    break

        if not title or not url:
            continue

        # 获取发布日期
        pub_date = ''
        parsed = entry.get('published_parsed') or entry.get('updated_parsed')
        if parsed:
            try:
                pub_date = datetime(*parsed[:6]).strftime('%b %d, %Y')
            except Exception:
                pass

        results.append((title, url, pub_date))

    return results
