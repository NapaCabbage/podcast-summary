# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated pipeline that monitors RSS/Atom feeds and YouTube channels, scrapes content, generates structured Chinese-language summaries via the ByteDance Ark API (OpenAI-compatible), and compiles everything into a static HTML website served by Nginx.

## Key Commands

```bash
# Full pipeline (requires ARK_API_KEY)
python feed_monitor.py

# Check for new episodes without processing
python feed_monitor.py --dry-run

# Scrape only, skip AI summarization
python feed_monitor.py --scrape-only

# Process a single source by name
python feed_monitor.py --source "Lex Fridman Podcast"

# Filter by recency
python feed_monitor.py --since 7d
python feed_monitor.py --since 2025-01-01

# Process a single URL end-to-end
python process_url.py https://youtu.be/xxxxx
python process_url.py https://... --title "Custom Title" --scrape-only

# Generate a summary for a specific raw file slug
python auto_summarize.py <slug>

# Rebuild HTML from all summaries
python generator.py

# List raw/ files missing summaries
python summarize.py

# Run the web management UI (http://localhost:8080)
python web_ui.py
```

**Environment variable** (store in `.env` with `chmod 600`):
```
ARK_API_KEY=...
```

## Architecture

### Processing Pipeline

```
sources.yaml (RSS/YouTube configs)
    → feed_monitor.py  (detect new episodes)
    → scrapers/        (extract raw content)
    → raw/*.txt        (raw transcripts)
    → auto_summarize.py (Ark API + prompt template)
    → summaries/*.md   (Markdown with frontmatter)
    → generator.py     (HTML compilation)
    → output/          (static site served by Nginx)
```

### Core Files

| File | Role |
|------|------|
| `feed_monitor.py` | Main orchestrator: discover → scrape → summarize → rebuild HTML |
| `auto_summarize.py` | Calls Ark API with `prompts/summary_template.md` to produce Markdown |
| `generator.py` | Compiles `summaries/*.md` → `output/index.html` + individual pages |
| `web_ui.py` | Flask management UI with REST API and real-time streaming output |
| `process_url.py` | One-shot script: scrape a URL and run the full pipeline |
| `scraper.py` | Legacy scraper reading from `podcasts.yaml` (predecessor to feed_monitor) |
| `sources.yaml` | Primary feed configuration (RSS + YouTube channels) |
| `podcasts.yaml` | Legacy config used by `scraper.py` |
| `prompts/summary_template.md` | Prompt template for Chinese summary generation |

### Scrapers (`scrapers/`)

- `youtube.py` — YouTube transcript/metadata via `youtube-transcript-api` and `yt-dlp`
- `substack.py` — Substack and custom blog content extraction
- `rss.py` — RSS/Atom feed parsing via `feedparser`
- `generic.py` — Generic webpage content scraper via `BeautifulSoup`
- `utils.py` — Shared utilities

### Generated Directories (git-ignored)

- `raw/` — Scraped plain-text transcripts, named by slug (e.g., `lex-fridman-123.txt`)
- `summaries/` — AI-generated Markdown summaries with frontmatter metadata
- `output/` — Final static HTML website
- `logs/` — Cron execution logs

## Configuration

### sources.yaml Fields

```yaml
- name: "Source Name"
  type: rss | youtube_channel
  feed_url: "..."        # RSS: direct feed URL
  channel_handle: "..."  # YouTube: @handle (auto-resolved to channel ID)
  title_filter: "..."    # Only process episodes whose titles contain this string
  max_episodes: 3        # Cap on historical episodes per run
  category: "分类名"     # Default category; overridden by keyword detection
  lock_category: true    # If true, skip keyword detection and always use category
```

### Category Detection

`COMPANY_PATTERNS` at the top of `feed_monitor.py` is an ordered list of `(category_label, [keywords])` tuples. Matching is case-insensitive; first match wins. Modify keyword lists there to change auto-categorization.

`CATEGORY_ORDER` in `generator.py` controls the display order of category groups on the homepage.

### Summary Frontmatter Format

Each `summaries/*.md` file begins with:
```
**标题：** ...
**来源：** ...
**发布日期：** YYYY-MM-DD
**分类：** ...
**一句话概括：** ...
```

## Deployment

- Target: Ubuntu 22.04 LTS, Nginx serving `output/` directory
- One-click server setup: `bash deploy/setup.sh`
- Nginx config: `deploy/nginx.conf`
- Cron schedule: `deploy/crontab.txt` (default: daily at 8 AM)
- YouTube channel RSS requires no API key: `youtube.com/feeds/videos.xml?channel_id=...`
