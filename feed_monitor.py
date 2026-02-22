"""
自动监控新集数，触发完整处理流水线：
  发现新集数 → 抓取原文 → 生成纪要 → 重建 HTML

用法：
  python feed_monitor.py              # 检查所有来源，处理新集数
  python feed_monitor.py --dry-run    # 只列出新集数，不执行处理

依赖：
  pip install feedparser
  环境变量：ARK_API_KEY
"""
import os
import re
import sys
import yaml
from scrapers import youtube, substack, generic
from scrapers.rss import fetch_episodes
from scrapers.youtube import list_channel_episodes

RAW_DIR = 'raw'
SUMMARY_DIR = 'summaries'
SOURCES_FILE = 'sources.yaml'


def slugify(title):
    title = title.lower()
    title = re.sub(r'[^\w\s-]', '', title)
    title = re.sub(r'[\s_]+', '-', title)
    title = re.sub(r'-+', '-', title).strip('-')
    return title[:80]


def get_existing_slugs():
    os.makedirs(RAW_DIR, exist_ok=True)
    return {f[:-4] for f in os.listdir(RAW_DIR) if f.endswith('.txt')}


def detect_type(url):
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    substack_domains = ['substack.com', 'dwarkesh.com', 'latent.space']
    if any(d in url for d in substack_domains) or '/p/' in url:
        return 'substack'
    return 'generic'


def scrape_episode(title, url, pub_date):
    """抓取单集内容并保存到 raw/，返回 (slug, char_count)"""
    slug = slugify(title)
    output_path = os.path.join(RAW_DIR, f'{slug}.txt')

    site_type = detect_type(url)

    if site_type == 'youtube':
        text, scraped_date = youtube.scrape(url)
    elif site_type == 'substack':
        text, scraped_date = substack.scrape(url)
    else:
        text, scraped_date = generic.scrape(url)

    # Feed 提供的日期优先；抓取到的日期作备用
    final_date = pub_date or scraped_date

    header = (
        f'标题：{title}\n'
        f'URL：{url}\n'
        f'类型：{site_type}\n'
        f'发布日期：{final_date}\n'
        f'\n{"=" * 60}\n\n'
    )

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(header + text)

    return slug, len(text)


def discover_source(source):
    """
    从 source 配置发现最新集数。
    返回：[(title, url, pub_date_str), ...]
    """
    stype = source['type']
    max_ep = source.get('max_episodes', 5)

    if stype == 'rss':
        return fetch_episodes(source['feed_url'], max_ep)

    if stype == 'youtube_channel':
        handle = source.get('channel_handle') or source.get('channel_id', '')
        return list_channel_episodes(
            handle,
            max_count=max_ep,
            title_filter=source.get('title_filter', ''),
        )

    raise ValueError(f"未知来源类型：{stype}")


def main():
    dry_run = '--dry-run' in sys.argv

    if not os.path.exists(SOURCES_FILE):
        print(f'[错误] 找不到配置文件：{SOURCES_FILE}')
        sys.exit(1)

    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    sources = config.get('sources', [])
    existing_slugs = get_existing_slugs()

    print(f'已有 {len(existing_slugs)} 篇原文，检查 {len(sources)} 个来源...\n')

    all_new = []  # [(title, url, pub_date, source_name)]

    for source in sources:
        name = source.get('name', source.get('feed_url', ''))
        try:
            episodes = discover_source(source)
        except Exception as e:
            print(f'  ❌ {name}：{e}')
            continue

        new_here = [
            (t, u, d) for t, u, d in episodes
            if slugify(t) not in existing_slugs
        ]

        if new_here:
            print(f'  {name}：{len(new_here)} 集新内容')
            for t, u, d in new_here:
                date_str = f'  [{d}]' if d else ''
                print(f'    + {t}{date_str}')
            all_new.extend((t, u, d, name) for t, u, d in new_here)
        else:
            print(f'  {name}：无新内容')

    total = len(all_new)
    if total == 0:
        print('\n没有新集数需要处理。')
        return

    print(f'\n共发现 {total} 集新内容。')

    if dry_run:
        print('（--dry-run 模式，不执行处理）')
        return

    # ── 第一步：抓取原文 ─────────────────────────────────────────
    print('\n' + '─' * 50)
    print('第一步：抓取原文\n')

    os.makedirs(RAW_DIR, exist_ok=True)
    new_slugs = []

    for title, url, pub_date, source_name in all_new:
        print(f'[{source_name}] {title}')
        try:
            slug, char_count = scrape_episode(title, url, pub_date)
            new_slugs.append(slug)
            print(f'  ✅ raw/{slug}.txt  （{char_count:,} 字符）')
        except Exception as e:
            print(f'  ❌ 抓取失败：{e}')
        print()

    if not new_slugs:
        print('没有成功抓取的内容，中止流水线。')
        return

    # ── 第二步：生成纪要 ─────────────────────────────────────────
    print('─' * 50)
    print('第二步：生成纪要\n')

    if not os.environ.get('ARK_API_KEY'):
        print('[错误] 未设置 ARK_API_KEY 环境变量，跳过纪要生成。')
        print('  请先运行：export ARK_API_KEY="..."')
        sys.exit(1)

    import subprocess
    result = subprocess.run(
        [sys.executable, 'auto_summarize.py'] + new_slugs,
    )

    # ── 第三步：重建 HTML ─────────────────────────────────────────
    print('─' * 50)
    print('第三步：重建 HTML\n')

    subprocess.run([sys.executable, 'generator.py'])

    print('\n✅ 流水线完成！')


if __name__ == '__main__':
    main()
