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
html { scroll-behavior: smooth; }

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

/* TOC 目录侧边栏 */
.toc-sidebar {
    position: fixed;
    top: 70px;
    left: calc(50% + 415px);
    width: 200px;
    max-height: calc(100vh - 100px);
    overflow-y: auto;
    font-size: 12px;
    line-height: 1.6;
    padding: 8px 0;
}

.toc-title {
    font-size: 11px;
    font-weight: 600;
    color: #bbb;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-bottom: 8px;
    padding-left: 10px;
}

.toc-sidebar a {
    display: block;
    color: #bbb;
    text-decoration: none;
    padding: 3px 0 3px 10px;
    border-left: 2px solid #e8e8e8;
    transition: color 0.15s, border-color 0.15s;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.toc-sidebar a:hover { color: #333; border-left-color: #999; }

.toc-sidebar .toc-h3 {
    padding-left: 22px;
    font-size: 11px;
}

.toc-sidebar a.active {
    color: #222;
    border-left-color: #333;
    font-weight: 500;
}

@media (max-width: 1240px) {
    .toc-sidebar { display: none; }
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
    """提取原文发布日期（兼容 **发布日期：** 和 **原文发表：** 两种写法）"""
    for pattern in (r'\*\*发布日期：\*\*\s*(.+)', r'\*\*原文发表：\*\*\s*(.+)'):
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip()
    return ''


def parse_summary_date_from_md(content):
    """提取纪要生成日期"""
    match = re.search(r'\*\*纪要生成：\*\*\s*(.+)', content)
    return match.group(1).strip() if match else ''


def parse_category_from_md(content, title=''):
    """
    提取分类标签。
    优先读 **分类：** 字段；若无，按关键词从标题/来源行推断（兼容旧纪要）；
    最终兜底返回 '其他'。
    """
    match = re.search(r'\*\*分类：\*\*\s*(.+)', content)
    if match:
        return match.group(1).strip()

    meta_match = re.search(r'\*\*来源：\*\*(.+)', content)
    haystack = (title + ' ' + (meta_match.group(1) if meta_match else '')).lower()

    LEGACY_PATTERNS = [
        ('Anthropic',       ['anthropic', 'claude', 'dario amodei']),
        ('OpenAI',          ['openai', 'chatgpt', 'gpt-4', 'gpt-5', 'sam altman']),
        ('Google DeepMind', ['google', 'deepmind', 'gemini', 'jeff dean']),
        ('Meta AI',         ['meta ai', 'llama', 'zuckerberg', 'yann lecun']),
        ('xAI',             ['xai', 'grok', 'elon musk']),
        ('Microsoft',       ['microsoft', 'github copilot', 'satya']),
        ('NVIDIA',          ['nvidia', 'jensen huang']),
    ]
    for cat, kws in LEGACY_PATTERNS:
        if any(kw in haystack for kw in kws):
            return cat
    return '其他'


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


TOC_JS = """<script>
(function () {
  var links = document.querySelectorAll('.toc-sidebar a');
  var headings = Array.from(document.querySelectorAll('h2[id], h3[id]'));
  if (!headings.length || !links.length) return;
  function setActive() {
    var active = headings[0];
    for (var i = 0; i < headings.length; i++) {
      if (headings[i].getBoundingClientRect().top <= 90) active = headings[i];
    }
    links.forEach(function (a) {
      a.classList.toggle('active', a.getAttribute('href') === '#' + active.id);
    });
  }
  window.addEventListener('scroll', setActive, { passive: true });
  setActive();
}());
</script>"""


def slugify_id(text):
    """将标题文本转为有效的 HTML id 属性值"""
    text = re.sub(r'[^\w\s-]', '', text, flags=re.UNICODE)
    text = text.strip().lower()
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return text or 'section'


def build_toc_and_add_ids(html):
    """
    在 HTML 的 h2/h3 标签上添加 id 属性，返回 (modified_html, toc_items)。
    toc_items: list of (level, text, id_str)
    """
    toc_items = []
    id_counter = {}

    def replace_heading(match):
        tag = match.group(1)
        attrs = match.group(2)
        inner = match.group(3)
        text = re.sub(r'<[^>]+>', '', inner).strip()
        base_id = slugify_id(text)
        count = id_counter.get(base_id, 0)
        id_counter[base_id] = count + 1
        uid = base_id if count == 0 else f'{base_id}-{count}'
        toc_items.append((int(tag[1]), text, uid))
        extra = (' ' + attrs.strip()) if attrs.strip() else ''
        return f'<{tag} id="{uid}"{extra}>{inner}</{tag}>'

    modified = re.sub(
        r'<(h[23])([^>]*)>(.*?)</\1>',
        replace_heading,
        html,
        flags=re.DOTALL
    )
    return modified, toc_items


def build_toc_html(toc_items):
    """从 toc_items 生成 TOC 侧边栏 HTML"""
    if not toc_items:
        return ''
    lines = [
        '<nav class="toc-sidebar" aria-label="目录">',
        '  <div class="toc-title">目录</div>',
    ]
    for level, text, uid in toc_items:
        cls = f'toc-h{level}'
        lines.append(f'  <a class="{cls}" href="#{uid}" title="{text}">{text}</a>')
    lines.append('</nav>')
    return '\n'.join(lines)


def generate_page(slug, content):
    """生成单篇纪要的 HTML 页面"""
    title = parse_title_from_md(content)
    meta = parse_meta_from_md(content)
    publish_date = parse_publish_date_from_md(content)
    summary_date = parse_summary_date_from_md(content)
    body_html = md_to_html(content)
    body_html, toc_items = build_toc_and_add_ids(body_html)
    toc_html = build_toc_html(toc_items)

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
  {toc_html}
  <div class="container">
    {body_html}
    {date_html}
  </div>
  {TOC_JS if toc_items else ''}
</body>
</html>"""
    return html


def generate_index(entries):
    """生成按分类分组的目录索引页"""

    # 分类显示顺序（未在列表中的分类追加到末尾，按字母排序）
    CATEGORY_ORDER = [
        'Anthropic', 'OpenAI', 'Google DeepMind', 'Meta AI',
        'xAI', 'Microsoft', 'NVIDIA', 'Mistral', 'Cohere',
        'AI 工程', 'AI 资讯', '访谈', '产品', '创投', '投资', '其他',
    ]

    # 按分类分组
    groups = {}
    for entry in entries:
        slug, title, meta, publish_date, summary_date, category = entry
        groups.setdefault(category, []).append(entry)

    # 排序：先按 CATEGORY_ORDER，其余分类按字母排在后面
    ordered_cats = [c for c in CATEGORY_ORDER if c in groups]
    extra_cats = sorted(c for c in groups if c not in CATEGORY_ORDER)
    all_cats = ordered_cats + extra_cats

    def _date_key(entry):
        """将发布日期转为 YYYY-MM-DD 字符串用于排序，无法解析的排到最后。"""
        from datetime import datetime
        pub = (entry[3] or '').strip()
        if not pub:
            return '0000-00-00'
        # YYYY-MM-DD
        m = re.match(r'(\d{4}-\d{2}-\d{2})', pub)
        if m:
            return m.group(1)
        # "Feb 13, 2026" / "Feb 6, 2026"
        for fmt in ('%b %d, %Y', '%B %d, %Y', '%b %d %Y', '%d %b %Y'):
            try:
                return datetime.strptime(pub, fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue
        # 兜底：只取年份
        m = re.search(r'(\d{4})', pub)
        return (m.group(1) + '-00-00') if m else '0000-00-00'

    sections_html = ''
    for cat in all_cats:
        # 按发布日期从新到旧排序
        cat_entries = sorted(groups[cat], key=_date_key, reverse=True)
        cards = ''
        for slug, title, meta, publish_date, summary_date, _ in cat_entries:
            date_parts = []
            if publish_date:
                date_parts.append(f'原文发表：{publish_date}')
            if summary_date:
                date_parts.append(f'纪要生成：{summary_date}')
            date_str = ' &nbsp;·&nbsp; '.join(date_parts)
            cards += f"""
    <a class="card" href="{slug}.html">
      <h3>{title}</h3>
      <div class="card-meta">{meta}</div>
      {f'<div class="card-dates">{date_str}</div>' if date_str else ''}
    </a>"""
        sections_html += f"""
  <div class="category-section">
    <h2 class="category-title">{cat} <span class="category-count">{len(cat_entries)}</span></h2>
    <div class="card-grid">{cards}
    </div>
  </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>播客纪要</title>
  <style>{CSS}
.category-section {{ margin-bottom: 48px; }}
.category-title {{ font-size: 18px; font-weight: 700; margin-bottom: 16px;
                   padding-bottom: 8px; border-bottom: 2px solid #e8e8e8; color: #111; }}
.category-count {{ font-size: 13px; font-weight: 400; color: #999;
                   background: #f0f0f0; border-radius: 10px;
                   padding: 1px 8px; margin-left: 6px; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>播客纪要</h1>
    <p style="color:#888; margin-top:8px;">共 {len(entries)} 篇 · {len(all_cats)} 个分类</p>
    {sections_html}
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
        category = parse_category_from_md(content, title)

        page_html = generate_page(slug, content)
        output_path = os.path.join(OUTPUT_DIR, f'{slug}.html')

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(page_html)

        entries.append((slug, title, meta, publish_date, summary_date, category))
        print(f'  ✅ [{category}] {title}  →  {output_path}')

    # 生成索引页
    index_html = generate_index(entries)
    index_path = os.path.join(OUTPUT_DIR, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_html)

    print(f'\n索引页  →  {index_path}')
    print(f'\n完成！用浏览器打开 output/index.html 查看结果')

    # 自动部署到 Cloudflare Pages（若 wrangler 可用）
    _deploy_to_cloudflare()


def _deploy_to_cloudflare():
    """调用 wrangler 将 output/ 部署到 Cloudflare Pages。"""
    import shutil
    import subprocess
    if not shutil.which('wrangler'):
        return  # wrangler 未安装，跳过
    print('\n正在部署到 Cloudflare Pages...')
    result = subprocess.run(
        ['wrangler', 'pages', 'deploy', OUTPUT_DIR,
         '--project-name', 'podcast-summary', '--commit-dirty=true'],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        # 从输出中提取 URL
        for line in (result.stdout + result.stderr).splitlines():
            if 'pages.dev' in line:
                print(f'✅ 已部署：{line.strip()}')
                break
        else:
            print('✅ Cloudflare Pages 部署完成')
    else:
        print(f'⚠️  Cloudflare 部署失败：{result.stderr[-300:]}')


if __name__ == '__main__':
    main()
