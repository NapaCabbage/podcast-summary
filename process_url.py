"""
处理单条 URL：抓取原文 → 生成纪要 → 重建 HTML

用法：
  python process_url.py https://youtu.be/xxxxx
  python process_url.py https://... --title "自定义标题"
  python process_url.py https://... --scrape-only
"""

import argparse
import os
import re
import subprocess
import sys
from urllib.request import urlopen, Request
import json

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

PYTHON = os.path.join(APP_DIR, '.venv', 'bin', 'python3')
if not os.path.exists(PYTHON):
    PYTHON = sys.executable


def fetch_title(url):
    """自动从 URL 提取标题"""
    try:
        if 'youtube.com' in url or 'youtu.be' in url:
            oembed = f'https://www.youtube.com/oembed?url={url}&format=json'
            req = Request(oembed, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(req, timeout=10) as resp:
                return json.loads(resp.read()).get('title', '')

        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(req, timeout=15) as resp:
            html = resp.read(80000).decode('utf-8', errors='ignore')

        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:title["\']', html, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
        if m:
            return m.group(1).strip()
    except Exception as e:
        print(f'[标题提取] {e}', flush=True)
    return ''


def main():
    parser = argparse.ArgumentParser(description='处理单条 URL')
    parser.add_argument('url', help='要处理的 URL')
    parser.add_argument('--title', default='', help='自定义标题（不填则自动提取）')
    parser.add_argument('--scrape-only', action='store_true', help='只抓取原文，不生成纪要')
    args = parser.parse_args()

    from feed_monitor import scrape_episode, detect_category, slugify

    url = args.url
    title = args.title
    scrape_only = args.scrape_only
    env = {**os.environ, 'PYTHONUNBUFFERED': '1'}

    print(f'URL：{url}', flush=True)

    # ① 获取标题
    if not title:
        print('正在提取标题...', flush=True)
        title = fetch_title(url)
    if not title:
        title = url.rstrip('/').split('/')[-1] or 'untitled'
    print(f'标题：{title}', flush=True)

    # ② 检查是否已存在
    slug = slugify(title)
    raw_path = os.path.join('raw', f'{slug}.txt')
    summary_path = os.path.join('summaries', f'{slug}.md')

    if os.path.exists(raw_path):
        print(f'⚠️  原文已存在：raw/{slug}.txt', flush=True)
        if scrape_only or os.path.exists(summary_path):
            if os.path.exists(summary_path):
                print(f'⚠️  纪要也已存在：summaries/{slug}.md，跳过。', flush=True)
            return
    else:
        # ③ 抓取
        print('正在抓取内容...', flush=True)
        try:
            category = detect_category(title, '其他')
            slug, char_count = scrape_episode(title, url, '', category)
            print(f'✅ 抓取完成：raw/{slug}.txt（{char_count:,} 字符）', flush=True)
        except Exception as e:
            print(f'❌ 抓取失败：{e}', flush=True)
            sys.exit(1)

    if scrape_only:
        print('（只抓取模式，跳过纪要生成）', flush=True)
        return

    # ④ 生成纪要
    if not os.environ.get('ARK_API_KEY'):
        print('❌ 未设置 ARK_API_KEY，无法生成纪要', flush=True)
        sys.exit(1)

    print('正在生成纪要（约 1-2 分钟）...', flush=True)
    result = subprocess.run(
        [PYTHON, 'auto_summarize.py', slug],
        cwd=APP_DIR, env=env,
    )
    if result.returncode == 0:
        print(f'✅ 纪要已生成：summaries/{slug}.md', flush=True)
    else:
        print(f'⚠️  纪要生成异常（返回码 {result.returncode}）', flush=True)

    # ⑤ 重建网页
    print('正在重建网页...', flush=True)
    subprocess.run([PYTHON, 'generator.py'], cwd=APP_DIR, env=env)
    print('✅ 网页已更新', flush=True)


if __name__ == '__main__':
    main()
