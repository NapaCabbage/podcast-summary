"""
YouTube 字幕抓取模块
使用 youtube-transcript-api，无需 API Key
输出格式带时间戳标记，方便与视频章节对应
"""
import re
import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from scrapers.utils import extract_pub_date

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
