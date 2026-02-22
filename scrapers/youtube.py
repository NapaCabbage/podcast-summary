"""
YouTube 字幕抓取模块 + 频道集数发现
- scrape(url)              抓取单个视频字幕，返回 (text, pub_date)
- list_channel_episodes()  从频道 RSS 获取最新视频列表，无需 API Key
"""
import re
import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from scrapers.utils import extract_pub_date, format_pub_date

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}


def extract_video_id(url):
    """从 YouTube URL 中提取视频 ID"""
    patterns = [
        r'youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
        r'youtu\.be/([a-zA-Z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def format_timestamp(seconds):
    """将秒数转为 HH:MM:SS 或 MM:SS 格式"""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def get_publish_date(url):
    """抓取 YouTube 页面并提取视频发布日期"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        return extract_pub_date(soup)
    except Exception:
        return ''


def scrape(url):
    """
    抓取 YouTube 视频字幕，返回 (text, pub_date) 元组。
    text：带时间戳标记的字幕文本，每段以 [MM:SS] 开头。
    pub_date：视频发布日期，如 'Dec 26, 2025'；获取失败则为空字符串。
    优先英文字幕，其次自动生成字幕。
    """
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"无法从 URL 提取视频 ID：{url}")

    # 获取发布日期
    pub_date = get_publish_date(url)

    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        try:
            transcript = transcript_list.find_manually_created_transcript(['en', 'en-US', 'en-GB'])
        except Exception:
            transcript = transcript_list.find_generated_transcript(['en', 'en-US', 'en-GB'])

        entries = transcript.fetch()

    except Exception as e:
        raise RuntimeError(f"无法获取字幕（视频 ID: {video_id}）：{e}")

    # 每隔约 30 秒合并为一段，段首标记时间戳
    paragraphs = []
    current_words = []
    paragraph_start = 0
    last_break = 0

    for entry in entries:
        text = entry.text.replace('\n', ' ').strip()
        start = entry.start

        if start - last_break > 30 and current_words:
            ts = format_timestamp(paragraph_start)
            paragraphs.append(f"[{ts}] " + ' '.join(current_words))
            current_words = []
            paragraph_start = start
            last_break = start

        current_words.append(text)

    if current_words:
        ts = format_timestamp(paragraph_start)
        paragraphs.append(f"[{ts}] " + ' '.join(current_words))

    return '\n\n'.join(paragraphs), pub_date


# ─── 频道发现 ────────────────────────────────────────────────────────────────

def resolve_channel_id(handle_or_id):
    """
    将 YouTube @handle 或普通 handle 字符串解析为 Channel ID（UCxxxxxxxx）。
    如果传入的已经是 Channel ID，直接返回。
    """
    # 已经是标准 Channel ID（UC 开头，24 位）
    if re.match(r'^UC[a-zA-Z0-9_-]{22}$', handle_or_id):
        return handle_or_id

    handle = handle_or_id.lstrip('@')
    url = f'https://www.youtube.com/@{handle}'

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 优先从 og:url 提取（最稳定）
        og_url = soup.find('meta', property='og:url')
        if og_url:
            m = re.search(r'/channel/(UC[a-zA-Z0-9_-]+)', og_url.get('content', ''))
            if m:
                return m.group(1)

        # 备用：从页面 JS 数据提取
        m = re.search(r'"externalId":"(UC[a-zA-Z0-9_-]+)"', resp.text)
        if m:
            return m.group(1)

        raise RuntimeError('页面中未找到 Channel ID')
    except Exception as e:
        raise RuntimeError(f'解析 @{handle} 的 Channel ID 失败：{e}')


def list_channel_episodes(handle_or_id, max_count=5, title_filter=''):
    """
    从 YouTube 频道 RSS 获取最新视频列表，无需 API Key。
    返回：[(title, url, pub_date_str), ...]
    title_filter：若设置，只返回标题含该字符串的视频（不区分大小写）
    """
    from scrapers.rss import fetch_episodes

    channel_id = resolve_channel_id(handle_or_id)
    feed_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'

    # YouTube 频道 Atom feed 的条目比实际需要的多，先多取再过滤
    fetch_count = max_count if not title_filter else max_count * 10
    episodes = fetch_episodes(feed_url, fetch_count)

    if title_filter:
        episodes = [
            (t, u, d) for t, u, d in episodes
            if title_filter.lower() in t.lower()
        ]

    return episodes[:max_count]
