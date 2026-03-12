"""
通用音频/视频抓取模块

支持场景：
  1. 本地音频/视频文件路径（.mp3 / .mp4 / .m4a / .wav / .webm 等）
  2. 直接媒体 URL（.m3u8 / .mp4 / .mp3 等）
  3. 需要 yt-dlp 提取的视频页面（Kaltura / Brightcove / NVIDIA on-demand 等）
     - 优先使用项目根目录的 cookies.txt（Netscape 格式）
     - 找不到时尝试 --cookies-from-browser 读取浏览器 Cookie

用法（在 feed_monitor.py / process_url.py 中）：
  from scrapers import audio as audio_scraper
  text, pub_date = audio_scraper.scrape(url_or_path)
"""

import os
import subprocess
import sys
import tempfile

# 项目根目录下的 cookies 文件（Netscape 格式，优先级高于 --cookies-from-browser）
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIES_FILE = os.path.join(_APP_DIR, 'cookies.txt')

# 直接媒体 URL 的常见扩展名
MEDIA_EXTENSIONS = {
    '.mp3', '.mp4', '.m4a', '.wav', '.flac',
    '.webm', '.mkv', '.avi', '.m3u8', '.ts',
}


def is_media_url(url: str) -> bool:
    """URL 路径以媒体扩展名结尾，视为直接媒体链接。"""
    from urllib.parse import urlparse
    path = urlparse(url).path.lower().split('?')[0]
    return any(path.endswith(ext) for ext in MEDIA_EXTENSIONS)


def scrape(url_or_path, cookies_from_browser=None):
    """
    下载/读取媒体 → Whisper 本地转写 → 返回 (text, pub_date) 元组。

    参数
    ----
    url_or_path        : 网页 URL、直接媒体 URL、或本地文件绝对路径
    cookies_from_browser : 读取浏览器 Cookie 以访问需登录的内容
                           可选值：'safari' | 'chrome' | 'firefox' | 'chromium'
                           为 None 时不使用 Cookie
    """
    if os.path.isfile(url_or_path):
        print(f"  [音频] 本地文件：{url_or_path}")
        text = _transcribe(url_or_path)
        return text, ''

    text = _download_and_transcribe(url_or_path, cookies_from_browser)
    return text, ''


# ── 内部函数 ──────────────────────────────────────────────────────────

def _download_and_transcribe(url, cookies_from_browser):
    """用 yt-dlp 下载音频，再用 Whisper 转写。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_template = os.path.join(tmpdir, 'audio.%(ext)s')

        cmd = [
            sys.executable, '-m', 'yt_dlp',
            '--extract-audio',
            '--audio-format', 'mp3',
            '--audio-quality', '5',      # 0=最高品质，5 对转写已足够
            '--output', out_template,
            '--no-playlist',
            '--quiet',
        ]

        # 优先用 cookies.txt 文件（避免 macOS Chrome v10 加密问题）
        if os.path.isfile(COOKIES_FILE):
            cmd += ['--cookies', COOKIES_FILE]
            cookie_hint = f'cookies.txt'
        elif cookies_from_browser:
            cmd += ['--cookies-from-browser', cookies_from_browser]
            cookie_hint = f'{cookies_from_browser} 浏览器'
        else:
            cookie_hint = None

        cmd.append(url)

        print(f"  [音频] yt-dlp 下载：{url}"
              + (f"（使用 {cookie_hint} Cookie）" if cookie_hint else ""))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            err = result.stderr[-600:]
            # 若因 Cookie 限制失败，给出明确提示
            if 'login' in err.lower() or 'sign in' in err.lower() or 'not available' in err.lower():
                raise RuntimeError(
                    f"yt-dlp 下载失败（可能需要登录）。\n"
                    f"请确认已在浏览器中登录该网站，并在设置中正确配置 BROWSER_COOKIES。\n"
                    f"详细错误：{err}"
                )
            raise RuntimeError(f"yt-dlp 下载失败：{err}")

        files = [f for f in os.listdir(tmpdir) if f.endswith('.mp3')]
        if not files:
            raise RuntimeError("yt-dlp 未生成 mp3 文件，该 URL 可能不包含可下载的音频。")

        return _transcribe(os.path.join(tmpdir, files[0]))


def _transcribe(audio_path: str) -> str:
    """faster-whisper 本地转写，返回带时间戳的分段文本。"""
    from faster_whisper import WhisperModel
    from scrapers.youtube import format_timestamp

    size_mb = os.path.getsize(audio_path) / 1024 / 1024
    print(f"  [转写] 文件大小：{size_mb:.1f} MB，开始 Whisper 转写（首次运行会下载模型）...")

    model = WhisperModel('small', device='cpu', compute_type='int8')
    segments, info = model.transcribe(audio_path, beam_size=3)
    print(f"  [转写] 检测语言：{info.language}，拼接文本...")

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
        paragraphs.append(f"[{format_timestamp(paragraph_start)}] " + ' '.join(current_words))

    return '\n\n'.join(paragraphs)
