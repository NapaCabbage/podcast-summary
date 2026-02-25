# 播客纪要项目 — Claude Code 上下文

## 项目概述
自动抓取播客/博客内容，调用豆包大模型生成结构化中文纪要，输出静态 HTML 网站。

## 技术栈
- Python 3.11+，虚拟环境 `.venv/`
- 豆包（Ark）API：`ARK_API_KEY` 环境变量，`openai` SDK 兼容接口
- feedparser：解析 RSS/Atom Feed
- Nginx：对外 serve `output/` 目录

## 核心文件
| 文件 | 作用 |
|------|------|
| `feed_monitor.py` | 主入口：发现新集数 → 抓取 → 纪要 → HTML |
| `auto_summarize.py` | 调用豆包 API 生成 Markdown 纪要 |
| `generator.py` | 将 `summaries/*.md` 编译为 `output/index.html` |
| `sources.yaml` | 订阅来源配置（RSS + YouTube 频道） |
| `scrapers/` | 各类抓取器（youtube / substack / generic / rss） |
| `prompts/summary_template.md` | 纪要生成 prompt 模板 |

## 目录结构
```
raw/          原始抓取文字稿（.txt）
summaries/    生成的 Markdown 纪要（.md）
output/       最终 HTML（Nginx serve）
deploy/       服务器部署配置
logs/         运行日志
```

## 常用命令
```bash
# 检查新集数（不处理）
python feed_monitor.py --dry-run

# 只抓取，不调用 AI
python feed_monitor.py --scrape-only

# 完整流水线（需要 ARK_API_KEY）
python feed_monitor.py

# 只处理指定来源
python feed_monitor.py --source "Lex Fridman Podcast"

# 手动生成单篇纪要
python auto_summarize.py <slug>

# 重建 HTML
python generator.py
```

## 环境变量（.env）
```
ARK_API_KEY=...  # 豆包 API Key（必须）
```

## 纪要 Markdown 格式
每篇纪要 frontmatter：
```
**标题：** ...
**来源：** ...
**发布日期：** ...
**分类：** ...        ← 公司/主题分类，由 COMPANY_PATTERNS 自动检测
**一句话概括：** ...
```

## 注意事项
- `sources.yaml` 修改后立即生效，下次 `feed_monitor.py` 自动读取
- `COMPANY_PATTERNS` 在 `feed_monitor.py` 顶部，关键词区分顺序，首先匹配的获胜
- YouTube 频道 RSS 无需 API Key，通过 `youtube.com/feeds/videos.xml?channel_id=...` 获取
- `generator.py` 中 `CATEGORY_ORDER` 控制首页分组顺序
