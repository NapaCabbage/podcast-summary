"""
HTML 网页生成器
用法：python generator.py
读取 summaries/ 中的 Markdown 文件 → 生成 output/ 中的 HTML 网页
"""
import os
import re
import markdown

SUMMARY_DIR = 'summaries'
OUTPUT_DIR = 'output'

# 网页通用 CSS 样式
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB",
                 "Microsoft YaHei", sans-serif;
    background: #f5f5f0;
    color: #2c2c2c;
    line-height: 1.8;
}

.container {
    max-width: 780px;
    margin: 0 auto;
    padding: 40px 24px 80px;
}

/* 导航栏 */
.nav {
    background: #fff;
    border-bottom: 1px solid #e8e8e8;
    padding: 16px 24px;
    margin-bottom: 40px;
}
.nav a {
    color: #555;
    text-decoration: none;
    font-size: 14px;
}
.nav a:hover { color: #000; }

/* 标题 */
h1 {
    font-size: 28px;
    font-weight: 700;
    line-height: 1.3;
    margin-bottom: 12px;
    color: #111;
}

h2 {
    font-size: 20px;
    font-weight: 600;
    margin-top: 40px;
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 2px solid #e8e8e8;
    color: #111;
}

h3 {
    font-size: 17px;
    font-weight: 600;
    margin-top: 28px;
    margin-bottom: 10px;
    color: #333;
}

/* 正文 */
p {
    margin-bottom: 14px;
    color: #3a3a3a;
}

ul, ol {
    margin-bottom: 14px;
    padding-left: 24px;
}

li {
    margin-bottom: 6px;
    color: #3a3a3a;
}

/* 引用块 */
blockquote {
    border-left: 3px solid #aaa;
    margin: 20px 0;
    padding: 12px 20px;
    background: #fafafa;
    color: #555;
    font-style: italic;
}

/* 重点高亮 */
strong {
    color: #111;
    font-weight: 600;
}

/* 元数据 */
.meta {
    font-size: 13px;
    color: #888;
    margin-bottom: 32px;
    padding-bottom: 24px;
    border-bottom: 1px solid #eee;
}

/* 全集重点区域 */
.highlights {
    background: #fff;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 24px 28px;
    margin-bottom: 40px;
}
.highlights h2 {
    border: none;
    margin-top: 0;
    font-size: 17px;
    color: #444;
    letter-spacing: 0.02em;
}

/* 索引页卡片 */
.card-grid {
    display: grid;
    gap: 20px;
    margin-top: 32px;
}

.card {
    background: #fff;
    border: 1px solid #e8e8e8;
    border-radius: 8px;
    padding: 24px 28px;
    text-decoration: none;
    color: inherit;
    display: block;
    transition: box-shadow 0.15s;
}
.card:hover {
    box-shadow: 0 4px 16px rgba(0,0,0,0.08);
}
.card h3 {
    margin-top: 0;
    font-size: 17px;
    color: #111;
}
.card .card-meta {
    font-size: 12px;
    color: #999;
    margin-top: 8px;
}
.card .card-dates {
    font-size: 11px;
    color: #bbb;
    margin-top: 6px;
}

/* 分隔线 */
hr {
    border: none;
    border-top: 1px solid #e8e8e8;
    margin: 36px 0;
}
"""


def parse_title_from_md(content):
    """从 Markdown 中提取第一个 H1 标题"""
    match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    return match.group(1).strip() if match else '未命名播客'


def parse_meta_from_md(content):
    """提取来源元数据行"""
    match = re.search(r'\*\*来源：\*\*(.+)', content)
    return match.group(1).strip() if match else ''


def parse_publish_date_from_md(content):
    """提取原文发表日期"""
    match = re.search(r'\*\*原文发表：\*\*\s*(.+)', content)
    return match.group(1).strip() if match else ''


def parse_summary_date_from_md(content):
    """提取纪要生成日期"""
    match = re.search(r'\*\*纪要生成：\*\*\s*(.+)', content)
    return match.group(1).strip() if match else ''


def md_to_html(content):
    """将 Markdown 转为 HTML，并对全集重点区域加特殊样式"""
    html = markdown.markdown(content, extensions=['extra'])

    # 将「全集重点」区块包裹在 highlights div 中
    html = re.sub(
        r'(<h2[^>]*>全集重点</h2>)(.*?)(<h2)',
        r'<div class="highlights">\1\2</div>\3',
        html,
        flags=re.DOTALL
    )
    return html


def generate_page(slug, content):
    """生成单篇纪要的 HTML 页面"""
    title = parse_title_from_md(content)
    meta = parse_meta_from_md(content)
    publish_date = parse_publish_date_from_md(content)
    summary_date = parse_summary_date_from_md(content)
    body_html = md_to_html(content)

    date_parts = []
    if publish_date:
        date_parts.append(f'原文发表：{publish_date}')
    if summary_date:
        date_parts.append(f'纪要生成：{summary_date}')
    date_html = f'<p class="meta">{" &nbsp;·&nbsp; ".join(date_parts)}</p>' if date_parts else ''

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="nav">
    <a href="index.html">← 返回目录</a>
  </div>
  <div class="container">
    {body_html}
    {date_html}
  </div>
</body>
</html>"""
    return html


def generate_index(entries):
    """生成目录索引页"""
    cards_html = ''
    for slug, title, meta, publish_date, summary_date in entries:
        date_parts = []
        if publish_date:
            date_parts.append(f'原文发表：{publish_date}')
        if summary_date:
            date_parts.append(f'纪要生成：{summary_date}')
        date_str = ' &nbsp;·&nbsp; '.join(date_parts)
        cards_html += f"""
    <a class="card" href="{slug}.html">
      <h3>{title}</h3>
      <div class="card-meta">{meta}</div>
      {f'<div class="card-dates">{date_str}</div>' if date_str else ''}
    </a>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>播客纪要</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="container">
    <h1>播客纪要</h1>
    <p style="color:#888; margin-top:8px;">共 {len(entries)} 篇</p>
    <div class="card-grid">
      {cards_html}
    </div>
  </div>
</body>
</html>"""
    return html


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    md_files = sorted([f for f in os.listdir(SUMMARY_DIR) if f.endswith('.md')])
    if not md_files:
        print('summaries/ 文件夹为空，请先让 Claude Code 生成中文纪要')
        return

    print(f'找到 {len(md_files)} 篇纪要，开始生成网页...\n')

    entries = []

    for md_file in md_files:
        slug = md_file.replace('.md', '')
        md_path = os.path.join(SUMMARY_DIR, md_file)

        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        title = parse_title_from_md(content)
        meta = parse_meta_from_md(content)
        publish_date = parse_publish_date_from_md(content)
        summary_date = parse_summary_date_from_md(content)

        page_html = generate_page(slug, content)
        output_path = os.path.join(OUTPUT_DIR, f'{slug}.html')

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(page_html)

        entries.append((slug, title, meta, publish_date, summary_date))
        print(f'  ✅ {title}  →  {output_path}')

    # 生成索引页
    index_html = generate_index(entries)
    index_path = os.path.join(OUTPUT_DIR, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_html)

    print(f'\n索引页  →  {index_path}')
    print(f'\n完成！用浏览器打开 output/index.html 查看结果')


if __name__ == '__main__':
    main()
