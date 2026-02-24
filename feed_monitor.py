"""
自动监控新集数，触发完整处理流水线：
  发现新集数 → 抓取原文 → 生成纪要 → 重建 HTML

用法：
  python feed_monitor.py                        # 完整流水线
  python feed_monitor.py --dry-run              # 只列出新集数，不执行任何操作
  python feed_monitor.py --scrape-only          # 只抓取原文，不调用 AI 模型
  python feed_monitor.py --source "Latent Space" --scrape-only  # 只处理指定来源

依赖：
  pip install feedparser
  环境变量：ARK_API_KEY（--scrape-only 模式下不需要）
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

# 公司关键词检测：按顺序匹配，第一个命中的即为分类
# 格式：(分类标签, [关键词列表])  — 关键词不区分大小写
COMPANY_PATTERNS = [
    ('Anthropic',       ['anthropic', 'claude', 'dario amodei', 'amanda askell', 'chris olah']),
    ('OpenAI',          ['openai', 'chatgpt', 'gpt-4', 'gpt-5', 'gpt4', 'sam altman',
                         'greg brockman', 'ilya sutskever', 'sora', 'o1', 'o3']),
    ('Google DeepMind', ['google', 'deepmind', 'gemini', 'jeff dean', 'sundar pichai',
                         'demis hassabis', 'noam shazeer']),
    ('Meta AI',         ['meta ai', 'llama', 'mark zuckerberg', 'yann lecun']),
    ('xAI',             ['xai', 'grok', 'elon musk']),
    ('Microsoft',       ['microsoft', 'github copilot', 'satya nadella', 'copilot']),
    ('NVIDIA',          ['nvidia', 'jensen huang', 'cuda']),
    ('Mistral',         ['mistral']),
    ('Cohere',          ['cohere']),
    ('Stability AI',    ['stability ai', 'stable diffusion']),
]


def detect_category(title, default_category):
    """
    根据集数标题关键词检测所属公司/分类。
    若标题命中 COMPANY_PATTERNS，返回对应分类；否则返回 default_category。
    """
    title_lower = title.lower()
    for category, keywords in COMPANY_PATTERNS:
        if any(kw in title_lower for kw in keywords):
            return category
    return default_category


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


def scrape_episode(title, url, pub_date, category=''):
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
        f'分类：{category}\n'
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
    scrape_only = '--scrape-only' in sys.argv

    # --source "Name" 过滤只处理指定来源
    source_filter = ''
    if '--source' in sys.argv:
        idx = sys.argv.index('--source')
        if idx + 1 < len(sys.argv):
            source_filter = sys.argv[idx + 1].lower()

    if not os.path.exists(SOURCES_FILE):
        print(f'[错误] 找不到配置文件：{SOURCES_FILE}')
        sys.exit(1)

    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    sources = config.get('sources', [])
    if source_filter:
        sources = [s for s in sources if source_filter in s.get('name', '').lower()]
        if not sources:
            print(f'[错误] 找不到来源：{source_filter}')
            sys.exit(1)

    existing_slugs = get_existing_slugs()

    print(f'已有 {len(existing_slugs)} 篇原文，检查 {len(sources)} 个来源...\n')

    all_new = []  # [(title, url, pub_date, source_name, category)]

    for source in sources:
        name = source.get('name', source.get('feed_url', ''))
        default_cat = source.get('category', '其他')
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
                cat = detect_category(t, default_cat)
                date_str = f'  [{d}]' if d else ''
                cat_str = f'  →{cat}' if cat != default_cat else f'  [{cat}]'
                print(f'    + {t}{date_str}{cat_str}')
                all_new.append((t, u, d, name, cat))
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

    mode = '（--scrape-only 模式，只抓取原文）' if scrape_only else ''
    if mode:
        print(mode)

    # ── 第一步：抓取原文 ─────────────────────────────────────────
    print('\n' + '─' * 50)
    print('第一步：抓取原文\n')

    os.makedirs(RAW_DIR, exist_ok=True)
    new_slugs = []

    for title, url, pub_date, source_name, category in all_new:
        print(f'[{source_name} / {category}] {title}')
        try:
            slug, char_count = scrape_episode(title, url, pub_date, category)
            new_slugs.append(slug)
            print(f'  ✅ raw/{slug}.txt  （{char_count:,} 字符）')
        except Exception as e:
            print(f'  ❌ 抓取失败：{e}')
        print()

    if not new_slugs:
        print('没有成功抓取的内容，中止流水线。')
        return

    if scrape_only:
        print(f'\n✅ 抓取完成，共 {len(new_slugs)} 篇。原文保存在 raw/ 目录。')
        print('   如需生成纪要，运行：python3 auto_summarize.py ' + ' '.join(new_slugs))
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
