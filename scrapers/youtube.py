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


def get_page_metadata(url):
    """抓取 YouTube 页面，返回 (title, description, pub_date)"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        pub_date = extract_pub_date(soup)

        # 提取标题
        title = ''
        og_title = soup.find('meta', property='og:title')
        if og_title:
            title = og_title.get('content', '')
        if not title:
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.text.replace(' - YouTube', '').strip()

        # 从页面 JS 数据中提取完整描述
        description = ''
        m = re.search(r'"shortDescription":"((?:[^"\\]|\\.)*?)"', resp.text)
        if m:
            description = m.group(1).replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
        # 备用：og:description
        if not description:
            og_desc = soup.find('meta', property='og:description')
            if og_desc:
                description = og_desc.get('content', '')

        return title, description, pub_date
    except Exception:
        return '', '', ''


def get_publish_date(url):
    """抓取 YouTube 页面并提取视频发布日期"""
    _, _, pub_date = get_page_metadata(url)
    return pub_date


def scrape(url):
    """
    抓取 YouTube 视频字幕，返回 (text, pub_date) 元组。
    text：带时间戳标记的字幕文本，每段以 [MM:SS] 开头。
    pub_date：视频发布日期，如 'Dec 26, 2025'；获取失败则为空字符串。
    优先英文字幕，其次自动生成字幕。
    若视频无字幕，则回退到视频标题 + 描述作为内容。
    """
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"无法从 URL 提取视频 ID：{url}")

    # 获取发布日期及页面元数据（一次请求）
    title, description, pub_date = get_page_metadata(url)

    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        try:
            transcript = transcript_list.find_manually_created_transcript(['en', 'en-US', 'en-GB'])
        except Exception:
            transcript = transcript_list.find_generated_transcript(['en', 'en-US', 'en-GB'])

        entries = transcript.fetch()

    except Exception as e:
        # 无字幕：回退到音频转写
        print(f"  [警告] 无法获取字幕（{type(e).__name__}），将下载音频并本地转写...")
        text = _transcribe_audio(video_id, url)
        return text, pub_date

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


# ─── 音频转写（无字幕时的 fallback）────────────────────────────────────────────

def _transcribe_audio(video_id, url):
    """
    用 yt-dlp 下载音频，再用 faster-whisper 本地转写。
    返回转写文本字符串。
    """
    import os
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, f'{video_id}.%(ext)s')
        out_path = os.path.join(tmpdir, f'{video_id}.mp3')

        print(f"  [转写] 下载音频：{url}")
        result = subprocess.run(
            [
                'yt-dlp',
                '--extract-audio',
                '--audio-format', 'mp3',
                '--audio-quality', '5',   # 0=最高, 9=最低；5 对转写足够
                '--output', audio_path,
                '--no-playlist',
                url,
            ],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp 下载失败：{result.stderr[-500:]}")

        # yt-dlp 会把扩展名替换成 mp3
        if not os.path.exists(out_path):
            # 有时文件名略有差异，找一下
            files = [f for f in os.listdir(tmpdir) if f.endswith('.mp3')]
            if not files:
                raise RuntimeError("yt-dlp 未生成 mp3 文件")
            out_path = os.path.join(tmpdir, files[0])

        size_mb = os.path.getsize(out_path) / 1024 / 1024
        print(f"  [转写] 音频大小：{size_mb:.1f} MB，开始 Whisper 转写（可能需要数分钟）...")

        from faster_whisper import WhisperModel
        # small 模型：平衡速度与准确率；首次运行会自动下载模型（约 500 MB）
        model = WhisperModel('small', device='cpu', compute_type='int8')
        segments, info = model.transcribe(out_path, beam_size=3, language='en')

        print(f"  [转写] 检测语言：{info.language}，开始拼接文本...")

        # 每 ~30 秒合并为一段，格式与字幕输出保持一致
        paragraphs = []
        current_words = []
        paragraph_start = 0.0
        last_break = 0.0

        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            if seg.start - last_break > 30 and current_words:
                ts = format_timestamp(paragraph_start)
                paragraphs.append(f"[{ts}] " + ' '.join(current_words))
                current_words = []
                paragraph_start = seg.start
                last_break = seg.start
            current_words.append(text)

        if current_words:
            ts = format_timestamp(paragraph_start)
            paragraphs.append(f"[{ts}] " + ' '.join(current_words))

        full_text = '\n\n'.join(paragraphs)
        print(f"  [转写] 完成，共 {len(full_text):,} 字符。")
        return full_text


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
