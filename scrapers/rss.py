"""
RSS / Atom Feed 解析模块
适用于 Lex Fridman、Latent Space、Dwarkesh 等有 Feed 的来源
用法：直接调用 fetch_episodes(feed_url, max_count)
"""
import re
import requests
import feedparser
from datetime import datetime

_HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; feedfetcher/1.0)'}
# XML 1.0 不允许 \x00-\x08、\x0b、\x0c、\x0e-\x1f 等控制字符
_INVALID_XML_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def fetch_episodes(feed_url, max_count=5):
    """
    解析 RSS/Atom Feed，返回最新 max_count 条集数。
    返回：[(title, url, pub_date_str), ...]
    pub_date_str 格式如 'Feb 12, 2026'；获取失败为空字符串。
    """
    try:
        resp = requests.get(feed_url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        content = _INVALID_XML_RE.sub('', resp.text)
        feed = feedparser.parse(content)
    except requests.HTTPError as e:
        raise RuntimeError(
            f"无法获取 Feed：{feed_url}（HTTP {e.response.status_code}）"
        )
    except requests.RequestException as e:
        raise RuntimeError(f"无法获取 Feed：{feed_url}（{e}）")

    if not feed.entries:
        exc = feed.get('bozo_exception', '无条目')
        raise RuntimeError(f"无法解析 Feed：{feed_url}（{exc}）")

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
