"""
主抓取程序
用法：python scraper.py
读取 podcasts.yaml → 识别网站类型 → 抓取内容 → 保存到 raw/
"""
import os
import re
import yaml
from scrapers import youtube, substack, generic


RAW_DIR = 'raw'


def slugify(title):
    """将标题转为适合作文件名的字符串"""
    title = title.lower()
    title = re.sub(r'[^\w\s-]', '', title)
    title = re.sub(r'[\s_]+', '-', title)
    title = re.sub(r'-+', '-', title).strip('-')
    return title[:80]  # 限制文件名长度


def detect_type(url):
    """根据 URL 判断网站类型"""
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    # Substack 特征：已知域名，或 URL 含 /p/ 路径
    substack_domains = ['substack.com', 'dwarkesh.com', 'latent.space']
    if any(d in url for d in substack_domains) or '/p/' in url:
        return 'substack'
    return 'generic'


def scrape_one(podcast):
    """抓取单个播客，保存到 raw/ 文件夹"""
    url = podcast['url']
    title = podcast['title']
    slug = slugify(title)
    output_path = os.path.join(RAW_DIR, f'{slug}.txt')

    # 已存在则跳过
    if os.path.exists(output_path):
        print(f'  [跳过] 已存在：{output_path}')
        return

    site_type = detect_type(url)
    print(f'  [抓取] {title}')
    print(f'         类型：{site_type} | URL：{url}')

    try:
        if site_type == 'youtube':
            text, pub_date = youtube.scrape(url)
        elif site_type == 'substack':
            text, pub_date = substack.scrape(url)
        else:
            text, pub_date = generic.scrape(url)

        # 在文本开头加入元数据（包含发布日期）
        header = (
            f'标题：{title}\n'
            f'URL：{url}\n'
            f'类型：{site_type}\n'
            f'发布日期：{pub_date}\n'
            f'\n{"="*60}\n\n'
        )
        full_text = header + text

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(full_text)

        date_info = f' | 发布日期：{pub_date}' if pub_date else ' | 发布日期：未获取'
        char_count = len(text)
        print(f'         完成，共 {char_count:,} 字符{date_info} → {output_path}')

    except Exception as e:
        print(f'  [错误] 抓取失败：{e}')


def main():
    os.makedirs(RAW_DIR, exist_ok=True)

    with open('podcasts.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    podcasts = config.get('podcasts', [])
    print(f'共 {len(podcasts)} 个播客待处理\n')

    for podcast in podcasts:
        scrape_one(podcast)
        print()

    print('抓取完成！原始文本保存在 raw/ 文件夹')
    print('下一步：告诉 Claude Code "帮我总结 raw/ 里的内容"')


if __name__ == '__main__':
    main()
