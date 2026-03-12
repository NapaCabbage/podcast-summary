"""
播客纪要 — 本地 Web 管理界面

用法：
  python web_ui.py
  然后在浏览器打开 http://localhost:8080
"""

import json
import os
import re
import subprocess
import sys

import yaml
from flask import Flask, Response, jsonify, request, stream_with_context

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)

PYTHON = os.path.join(APP_DIR, '.venv', 'bin', 'python3')
if not os.path.exists(PYTHON):
    PYTHON = sys.executable

app = Flask(__name__)


# ── .env 读写 ────────────────────────────────────────────────────────

ENV_FILE = os.path.join(APP_DIR, '.env')
# 允许通过界面配置的 Key（白名单，防止意外覆盖其他变量）
CONFIGURABLE_KEYS = ('ARK_API_KEY', 'CLOUDFLARE_API_TOKEN', 'BROWSER_COOKIES')


def _load_env_on_startup():
    """启动时将 .env 中的变量加载到当前进程（不覆盖已有的系统环境变量）。"""
    try:
        with open(ENV_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v
    except FileNotFoundError:
        pass


_load_env_on_startup()


def _read_env() -> dict:
    """读取 .env 文件，返回 {key: value} 字典。"""
    result = {}
    try:
        with open(ENV_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    result[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return result


def _write_env(updates: dict):
    """将 updates 中的键写入 .env，保留其余行不变。"""
    lines = []
    updated = set()
    try:
        with open(ENV_FILE, encoding='utf-8') as f:
            for line in f:
                raw = line.strip()
                if raw and not raw.startswith('#') and '=' in raw:
                    k = raw.split('=', 1)[0].strip()
                    if k in updates:
                        lines.append(f'{k}={updates[k]}\n')
                        updated.add(k)
                        continue
                lines.append(line if line.endswith('\n') else line + '\n')
    except FileNotFoundError:
        pass
    for k, v in updates.items():
        if k not in updated:
            lines.append(f'{k}={v}\n')
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    # 同步更新当前进程环境变量，无需重启即生效
    for k, v in updates.items():
        os.environ[k] = v


# ── 纪要元数据解析 ────────────────────────────────────────────────────

def _read_summary_meta(slug):
    """从 summaries/<slug>.md 中读取 frontmatter 字段。"""
    path = os.path.join('summaries', f'{slug}.md')
    meta = {'slug': slug, 'title': slug, 'source': '', 'date': '', 'category': '其他', 'abstract': ''}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                m = re.match(r'\*\*(.+?)：\*\*\s*(.*)', line)
                if m:
                    key_map = {
                        '标题': 'title', '来源': 'source',
                        '发布日期': 'date', '分类': 'category', '一句话概括': 'abstract',
                    }
                    k = m.group(1)
                    if k in key_map:
                        meta[key_map[k]] = m.group(2).strip()
    except Exception:
        pass
    return meta


# ── Flask 路由 ────────────────────────────────────────────────────────

@app.route('/')
def index():
    return HTML


@app.route('/api/status')
def status():
    sources_count = 0
    try:
        with open('sources.yaml', encoding='utf-8') as f:
            sources_count = len(yaml.safe_load(f).get('sources', []))
    except Exception:
        pass
    summaries_count = 0
    try:
        summaries_count = len([f for f in os.listdir('summaries') if f.endswith('.md')])
    except Exception:
        pass
    return jsonify({'sources': sources_count, 'summaries': summaries_count})


@app.route('/api/sources', methods=['GET'])
def api_sources_get():
    try:
        with open('sources.yaml', encoding='utf-8') as f:
            sources = yaml.safe_load(f).get('sources', [])
        return jsonify({'ok': True, 'sources': sources})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/sources', methods=['POST'])
def api_sources_add():
    """添加新来源到 sources.yaml"""
    data = request.get_json(force=True, silent=True) or {}
    name = data.get('name', '').strip()
    stype = data.get('type', '').strip()

    if not name or stype not in ('rss', 'youtube_channel'):
        return jsonify({'ok': False, 'error': '缺少 name 或 type 字段'}), 400

    try:
        with open('sources.yaml', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        sources = config.get('sources', [])

        if any(s.get('name') == name for s in sources):
            return jsonify({'ok': False, 'error': f'来源 "{name}" 已存在'}), 400

        entry = {'name': name, 'type': stype}
        if stype == 'rss':
            entry['feed_url'] = data.get('feed_url', '').strip()
        else:
            entry['channel_handle'] = data.get('channel_handle', '').strip()
            if data.get('title_filter', '').strip():
                entry['title_filter'] = data['title_filter'].strip()

        entry['max_episodes'] = int(data.get('max_episodes', 3))
        entry['category'] = data.get('category', '其他').strip()
        if data.get('lock_category'):
            entry['lock_category'] = True

        sources.append(entry)
        config['sources'] = sources

        with open('sources.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/sources/<path:name>', methods=['PUT'])
def api_sources_update(name):
    """更新指定来源的配置"""
    data = request.get_json(force=True, silent=True) or {}
    new_name = data.get('name', '').strip()
    stype = data.get('type', '').strip()

    if not new_name or stype not in ('rss', 'youtube_channel'):
        return jsonify({'ok': False, 'error': '缺少 name 或 type 字段'}), 400

    try:
        with open('sources.yaml', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        sources = config.get('sources', [])

        idx = next((i for i, s in enumerate(sources) if s.get('name') == name), None)
        if idx is None:
            return jsonify({'ok': False, 'error': f'找不到来源：{name}'}), 404

        if new_name != name and any(s.get('name') == new_name for s in sources):
            return jsonify({'ok': False, 'error': f'来源名称 "{new_name}" 已存在'}), 400

        entry = {'name': new_name, 'type': stype}
        if stype == 'rss':
            entry['feed_url'] = data.get('feed_url', '').strip()
        else:
            entry['channel_handle'] = data.get('channel_handle', '').strip()
            if data.get('title_filter', '').strip():
                entry['title_filter'] = data['title_filter'].strip()

        entry['max_episodes'] = int(data.get('max_episodes', 3))
        entry['category'] = data.get('category', '其他').strip()
        if data.get('lock_category'):
            entry['lock_category'] = True

        sources[idx] = entry
        config['sources'] = sources

        with open('sources.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/sources/<path:name>', methods=['DELETE'])
def api_sources_delete(name):
    """从 sources.yaml 删除指定来源"""
    try:
        with open('sources.yaml', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        sources = config.get('sources', [])
        original_len = len(sources)
        config['sources'] = [s for s in sources if s.get('name') != name]

        if len(config['sources']) == original_len:
            return jsonify({'ok': False, 'error': f'找不到来源：{name}'}), 404

        with open('sources.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/summaries/<path:slug>', methods=['DELETE'])
def api_summary_delete(slug):
    """删除指定纪要的 .md 和 .html 文件（不含重建，重建由前端单独触发）。"""
    import re
    if not re.match(r'^[\w\-]+$', slug):
        return jsonify({'ok': False, 'error': '非法 slug'}), 400
    md_path = os.path.join('summaries', f'{slug}.md')
    html_path = os.path.join('output', f'{slug}.html')
    if not os.path.exists(md_path):
        return jsonify({'ok': False, 'error': '纪要不存在'}), 404
    try:
        os.remove(md_path)
        if os.path.exists(html_path):
            os.remove(html_path)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/summaries')
def api_summaries():
    try:
        slugs = sorted(
            [f[:-3] for f in os.listdir('summaries') if f.endswith('.md')],
            reverse=True,
        )
        summaries = [_read_summary_meta(s) for s in slugs]
        categories = sorted({s['category'] for s in summaries if s['category']})
        return jsonify({'ok': True, 'summaries': summaries, 'categories': categories})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# ── 设置端点 ──────────────────────────────────────────────────────────

@app.route('/api/settings', methods=['GET'])
def api_settings_get():
    """返回各 Key 的设置状态（不返回完整值，只返回末 4 位作为提示）。"""
    env = _read_env()
    result = {}
    for k in CONFIGURABLE_KEYS:
        v = env.get(k) or os.environ.get(k, '')
        result[k] = {'set': bool(v), 'hint': ('…' + v[-4:]) if len(v) >= 4 else ('已设置' if v else '')}
    return jsonify({'ok': True, 'settings': result})


@app.route('/api/settings', methods=['POST'])
def api_settings_save():
    """保存 API Key 到 .env 文件，并立即更新当前进程环境变量。"""
    data = request.get_json(force=True, silent=True) or {}
    updates = {k: str(data[k]).strip() for k in CONFIGURABLE_KEYS if k in data and str(data[k]).strip()}
    if not updates:
        return jsonify({'ok': False, 'error': '没有可更新的字段'}), 400
    try:
        _write_env(updates)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── SSE 工具 ──────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_subprocess(args):
    env = {**os.environ, 'PYTHONUNBUFFERED': '1'}

    def generate():
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=APP_DIR,
                env=env,
            )
            for line in proc.stdout:
                yield _sse({'line': line.rstrip()})
            proc.wait()
            yield _sse({'done': True, 'ok': proc.returncode == 0})
        except Exception as e:
            yield _sse({'line': f'❌ {e}', 'done': True, 'ok': False})

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# ── 流水线端点 ────────────────────────────────────────────────────────

def _pipeline_args(base_args):
    """附加 --source 和 --since 参数"""
    source = request.args.get('source', '').strip()
    since = request.args.get('since', '').strip()
    args = list(base_args)
    if source:
        args += ['--source', source]
    if since:
        args += ['--since', since]
    return args


@app.get('/api/run/check')
def run_check():
    return _stream_subprocess(_pipeline_args([PYTHON, 'feed_monitor.py', '--dry-run']))


@app.get('/api/run/scrape')
def run_scrape():
    return _stream_subprocess(_pipeline_args([PYTHON, 'feed_monitor.py', '--scrape-only']))


@app.get('/api/run/process')
def run_process():
    return _stream_subprocess(_pipeline_args([PYTHON, 'feed_monitor.py']))


@app.get('/api/run/rebuild')
def run_rebuild():
    """仅重建 HTML 并部署（不抓取新内容）。"""
    return _stream_subprocess([PYTHON, 'generator.py'])


@app.post('/api/run/url')
def run_url():
    data = request.get_json(force=True, silent=True) or {}
    url = data.get('url', '').strip()
    title = data.get('title', '').strip()
    scrape_only = data.get('scrape_only', False)

    if not url:
        return jsonify({'ok': False, 'error': '缺少 url'}), 400

    args = [PYTHON, 'process_url.py', url]
    if title:
        args += ['--title', title]
    if scrape_only:
        args += ['--scrape-only']
    return _stream_subprocess(args)


# ── HTML ──────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>播客纪要</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f2f5;color:#222;font-size:14px}

header{background:#1a1a2e;color:#fff;padding:13px 24px;display:flex;align-items:center;gap:12px}
header h1{font-size:17px;font-weight:600}
.chip{background:rgba(255,255,255,.16);border-radius:20px;padding:3px 12px;font-size:12px}

nav{background:#fff;border-bottom:1px solid #e0e0e0;padding:0 20px;display:flex;gap:2px}
nav button{background:none;border:none;border-bottom:2px solid transparent;padding:11px 15px;
  cursor:pointer;font-size:14px;color:#666;transition:.15s}
nav button.active{color:#1a73e8;border-bottom-color:#1a73e8;font-weight:500}
nav button:hover:not(.active){color:#333}

main{padding:20px 24px;max-width:920px;margin:0 auto}

.card{background:#fff;border-radius:10px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:16px}
.card-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.7px;color:#999;margin-bottom:14px}

.row{display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;align-items:center}
input[type=text],input[type=url],input[type=date],select{
  border:1px solid #ddd;border-radius:6px;padding:7px 11px;font-size:14px;outline:none;background:#fff}
input[type=text]:focus,input[type=url]:focus,input[type=date]:focus,select:focus{
  border-color:#1a73e8;box-shadow:0 0 0 3px rgba(26,115,232,.1)}
input.grow{flex:1;min-width:160px}
.check-label{display:flex;align-items:center;gap:6px;font-size:13px;color:#555;
  cursor:pointer;white-space:nowrap;padding:7px 0}

.btn{border:none;border-radius:6px;padding:7px 16px;cursor:pointer;font-size:13px;
  font-weight:500;transition:.15s;white-space:nowrap}
.btn:disabled{opacity:.45;cursor:not-allowed}
.btn-primary{background:#1a73e8;color:#fff}.btn-primary:not(:disabled):hover{background:#1557b0}
.btn-ghost{background:#f1f3f4;color:#333}.btn-ghost:not(:disabled):hover{background:#e0e0e0}
.btn-green{background:#34a853;color:#fff}.btn-green:not(:disabled):hover{background:#2a8944}
.btn-red{background:none;border:1px solid #e0e0e0;color:#c62828;padding:5px 10px;font-size:12px}
.btn-red:not(:disabled):hover{background:#fce8e6;border-color:#c62828}
.btn-link{background:none;border:none;color:#1a73e8;cursor:pointer;font-size:13px;padding:0}
.btn-link:hover{text-decoration:underline}
.btn-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}

/* Log */
.log{background:#1e1e1e;color:#ccc;border-radius:8px;padding:14px 16px;
  font-family:'Menlo','Consolas',monospace;font-size:12.5px;line-height:1.65;
  max-height:400px;overflow-y:auto;min-height:60px;white-space:pre-wrap;word-break:break-all}
.log .ok{color:#89d185}.log .err{color:#f48771}.log .dim{color:#777}
.log .done-ok{color:#89d185;font-weight:600}.log .done-err{color:#f48771;font-weight:600}

/* Table */
table{width:100%;border-collapse:collapse}
th{text-align:left;padding:8px 10px;font-size:11px;text-transform:uppercase;
  color:#999;border-bottom:2px solid #f0f0f0;white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid #f5f5f5;vertical-align:top}
tr:last-child td{border-bottom:none}
.badge{display:inline-block;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:500}
.badge-blue{background:#e8f0fe;color:#1a73e8}
.badge-gray{background:#f1f3f4;color:#666}
.empty{color:#aaa;text-align:center;padding:24px;font-size:13px}

/* Sources add form */
.add-form{background:#f8f9fa;border:1px dashed #ccc;border-radius:8px;
  padding:16px;margin-top:12px;display:none}
.add-form.visible{display:block}
.form-row{display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;align-items:center}
.form-row label{font-size:13px;color:#555;white-space:nowrap;min-width:64px}
.hint{font-size:12px;color:#aaa;margin-top:2px}

/* Summaries category filter */
.cat-bar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.cat-btn{border:1px solid #ddd;background:#fff;border-radius:20px;padding:5px 14px;
  font-size:12px;cursor:pointer;transition:.12s;color:#555}
.cat-btn.active{background:#1a73e8;border-color:#1a73e8;color:#fff}
.cat-btn:hover:not(.active){background:#f0f2f5}
.sum-title{font-weight:500;font-size:13px}
.sum-abstract{font-size:12px;color:#777;margin-top:3px;line-height:1.5}
.sum-meta{font-size:11px;color:#aaa;margin-top:3px}

/* Time range */
.time-range{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.time-range label{font-size:13px;color:#555}

.tab-content{display:none}.tab-content.active{display:block}
#cond-rss,#cond-yt{display:none}
</style>
</head>
<body>

<header>
  <h1>🎙 播客纪要</h1>
  <span class="chip" id="chip-sources">— 来源</span>
  <span class="chip" id="chip-summaries">— 纪要</span>
</header>

<nav>
  <button class="active" data-tab="url"       onclick="switchTab(this)">处理 URL</button>
  <button              data-tab="pipeline"   onclick="switchTab(this)">订阅流水线</button>
  <button              data-tab="sources"    onclick="switchTab(this)">来源管理</button>
  <button              data-tab="summaries"  onclick="switchTab(this)">纪要列表</button>
  <button              data-tab="settings"   onclick="switchTab(this)">⚙ 设置</button>
</nav>

<main>

<!-- ── 处理 URL ── -->
<div id="tab-url" class="tab-content active">
  <div class="card">
    <div class="card-title">处理单条链接</div>
    <div class="row">
      <input type="url" id="url-input" class="grow" placeholder="https://youtu.be/xxxxx  或  Substack / 博客链接" />
    </div>
    <div class="row">
      <input type="text" id="url-title" class="grow" placeholder="自定义标题（选填，留空自动提取）" />
      <label class="check-label">
        <input type="checkbox" id="url-scrape-only"> 只抓取，不生成纪要
      </label>
    </div>
    <div class="btn-row">
      <button class="btn btn-primary" id="btn-url" onclick="processUrl()">开始处理</button>
    </div>
  </div>
  <div class="card">
    <div class="card-title">输出</div>
    <div class="log" id="log-url">准备就绪，输入链接后点击处理。</div>
  </div>
</div>

<!-- ── 订阅流水线 ── -->
<div id="tab-pipeline" class="tab-content">
  <div class="card">
    <div class="card-title">运行流水线</div>
    <div class="row">
      <input type="text" id="pipeline-source" class="grow" placeholder="来源名称（选填，留空处理全部）" />
    </div>
    <div class="row time-range">
      <label>时间范围：</label>
      <select id="since-preset" onchange="onSinceChange()">
        <option value="">全部（不限时间）</option>
        <option value="3d">最近 3 天</option>
        <option value="7d">最近 7 天</option>
        <option value="14d">最近 14 天</option>
        <option value="30d">最近 30 天</option>
        <option value="custom">自定义日期…</option>
      </select>
      <input type="date" id="since-date" style="display:none" />
    </div>
    <div class="hint" style="margin-bottom:10px;margin-top:-4px">
      「时间范围」按 Feed 中的发布时间过滤，仅处理范围内的新集数
    </div>
    <div class="btn-row">
      <button class="btn btn-ghost" onclick="runPipeline('check')">🔍 检查新集数</button>
      <button class="btn btn-ghost" onclick="runPipeline('scrape')">⬇️ 只抓取原文</button>
      <button class="btn btn-green" onclick="runPipeline('process')">⚡ 完整处理</button>
    </div>
  </div>
  <div class="card">
    <div class="card-title">输出</div>
    <div class="log" id="log-pipeline">选择操作后将在此显示实时日志。</div>
  </div>
</div>

<!-- ── 来源管理 ── -->
<div id="tab-sources" class="tab-content">
  <div class="card">
    <div class="card-title" style="display:flex;justify-content:space-between;align-items:center">
      <span>订阅来源</span>
      <button class="btn btn-primary" style="font-size:12px;padding:5px 12px" onclick="toggleAddForm()">+ 添加来源</button>
    </div>

    <!-- 已有来源列表 -->
    <table id="sources-table">
      <thead>
        <tr>
          <th>名称</th><th>类型</th><th>分类</th>
          <th title="每次运行最多检查该来源最新的 N 集，防止首次添加时处理大量历史内容">最多集数 ℹ</th>
          <th>Feed / 频道</th><th></th>
        </tr>
      </thead>
      <tbody id="sources-body">
        <tr><td colspan="6" class="empty">加载中...</td></tr>
      </tbody>
    </table>

    <!-- 添加/编辑来源表单 -->
    <div class="add-form" id="add-form">
      <div id="add-form-title" style="font-size:13px;font-weight:600;margin-bottom:12px;color:#333">添加新来源</div>

      <div class="form-row">
        <label>名称</label>
        <input type="text" id="add-name" class="grow" placeholder="Latent Space" />
      </div>

      <div class="form-row">
        <label>类型</label>
        <label class="check-label"><input type="radio" name="add-type" value="rss" onchange="onTypeChange()"> RSS / Substack / 播客 Feed</label>
        <label class="check-label"><input type="radio" name="add-type" value="youtube_channel" onchange="onTypeChange()"> YouTube 频道</label>
      </div>

      <div id="cond-rss" style="display:none">
        <div class="form-row">
          <label>Feed URL</label>
          <input type="text" id="add-feed-url" class="grow" placeholder="https://example.substack.com/feed" />
        </div>
      </div>

      <div id="cond-yt" style="display:none">
        <div class="form-row">
          <label>频道 Handle</label>
          <input type="text" id="add-handle" class="grow" placeholder="lexfridman（不含 @）" />
        </div>
        <div class="form-row">
          <label>标题过滤</label>
          <input type="text" id="add-filter" class="grow" placeholder="关键词（选填，如 Podcast 只抓播客集）" />
        </div>
      </div>

      <div class="form-row">
        <label>分类</label>
        <input type="text" id="add-category" class="grow" placeholder="AI/ML、通用、其他…" />
        <label style="white-space:nowrap;font-size:13px;color:#555">最多集数</label>
        <input type="text" id="add-max" style="width:60px" value="3" />
        <span style="font-size:12px;color:#aaa">/次</span>
      </div>

      <div class="form-row">
        <label></label>
        <label class="check-label" style="font-size:13px;color:#555">
          <input type="checkbox" id="add-lock-category"> 锁定分类（不按标题关键词自动覆盖，适合投资/产品等固定主题播客）
        </label>
      </div>

      <div class="btn-row" style="justify-content:flex-end">
        <button class="btn btn-ghost" onclick="toggleAddForm()">取消</button>
        <button class="btn btn-primary" id="add-form-submit" onclick="submitAddSource()">保存</button>
      </div>
      <div id="add-error" style="color:#c62828;font-size:12px;margin-top:8px"></div>
    </div>
  </div>
</div>

<!-- ── 纪要列表 ── -->
<div id="tab-summaries" class="tab-content">
  <div class="card">
    <div class="card-title">已生成纪要</div>
    <div class="cat-bar" id="cat-bar"></div>
    <table>
      <thead><tr><th>#</th><th>标题</th><th>分类</th><th>发布日期</th><th></th></tr></thead>
      <tbody id="summaries-body">
        <tr><td colspan="5" class="empty">加载中...</td></tr>
      </tbody>
    </table>
  </div>
  <div class="card" id="delete-log-card" style="display:none">
    <div class="card-title">删除 &amp; 部署进度</div>
    <div class="log" id="log-delete">准备中...</div>
  </div>
</div>

<!-- ── 设置 ── -->
<div id="tab-settings" class="tab-content">
  <div class="card">
    <div class="card-title">API Key 配置</div>
    <p style="font-size:13px;color:#666;margin-bottom:16px">
      保存后写入项目根目录的 <code>.env</code> 文件，并立即对当前服务生效，无需重启。
    </p>

    <div class="form-row" style="align-items:flex-start;gap:12px">
      <div style="flex:1;min-width:220px">
        <div style="font-size:13px;font-weight:600;margin-bottom:6px">ARK_API_KEY
          <span id="ark-status" style="font-size:11px;font-weight:400;margin-left:8px;color:#aaa">检测中…</span>
        </div>
        <div style="font-size:12px;color:#aaa;margin-bottom:8px">
          豆包（Ark）大模型 API Key，生成纪要时必须填写。<br>
          获取地址：<a href="https://console.volcengine.com/ark" target="_blank">火山引擎控制台</a>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <input type="password" id="ark-key-input" class="grow"
            placeholder="填写新 Key（留空则不修改）" autocomplete="off" />
          <button class="btn btn-ghost" style="white-space:nowrap"
            onclick="toggleArkVisible()">显示</button>
        </div>
      </div>
    </div>

    <div style="border-top:1px solid #f0f0f0;margin:20px 0"></div>

    <div class="form-row" style="align-items:flex-start;gap:12px">
      <div style="flex:1;min-width:220px">
        <div style="font-size:13px;font-weight:600;margin-bottom:6px">BROWSER_COOKIES
          <span id="bc-status" style="font-size:11px;font-weight:400;margin-left:8px;color:#aaa">检测中…</span>
        </div>
        <div style="font-size:12px;color:#aaa;margin-bottom:8px">
          处理需要登录的视频页面（NVIDIA on-demand、Kaltura 等）时，yt-dlp 会读取该浏览器的 Cookie 自动鉴权。<br>
          填写浏览器名称：<code>safari</code>（推荐，macOS 默认）、<code>chrome</code>、<code>firefox</code><br>
          留空则不使用 Cookie（公开内容无需设置）。
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <input type="text" id="bc-input" class="grow"
            placeholder="safari（留空则不修改）" autocomplete="off" />
        </div>
      </div>
    </div>

    <div style="border-top:1px solid #f0f0f0;margin:20px 0"></div>

    <div class="form-row" style="align-items:flex-start;gap:12px">
      <div style="flex:1;min-width:220px">
        <div style="font-size:13px;font-weight:600;margin-bottom:6px">CLOUDFLARE_API_TOKEN
          <span id="cf-status" style="font-size:11px;font-weight:400;margin-left:8px;color:#aaa">检测中…</span>
        </div>
        <div style="font-size:12px;color:#aaa;margin-bottom:8px">
          Cloudflare API Token，处理完成后自动部署到 Pages 时必须填写。<br>
          获取地址：<a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank">Cloudflare → My Profile → API Tokens</a><br>
          创建 Token 时选择模板「Edit Cloudflare Pages」或手动添加权限：<code>Cloudflare Pages:Edit</code>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <input type="password" id="cf-key-input" class="grow"
            placeholder="填写新 Token（留空则不修改）" autocomplete="off" />
          <button class="btn btn-ghost" style="white-space:nowrap"
            onclick="toggleCfVisible()">显示</button>
        </div>
      </div>
    </div>

    <div class="btn-row" style="margin-top:16px">
      <button class="btn btn-primary" onclick="saveSettings()">保存</button>
    </div>
    <div id="settings-msg" style="margin-top:10px;font-size:13px"></div>
  </div>
</div>

</main>

<script>
// ── Tab 切换
function switchTab(btn) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  const name = btn.dataset.tab;
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
  if (name === 'sources') loadSources();
  if (name === 'summaries') loadSummaries();
  if (name === 'settings') loadSettings();
}

// ── 日志
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function appendLog(el, line) {
  const cls = /✅/.test(line) ? 'ok' : /❌|错误|失败/.test(line) ? 'err'
             : /^[─\[（⏰⚠]/.test(line) ? 'dim' : '';
  el.innerHTML += `<span class="${cls}">${esc(line)}</span>\n`;
  el.scrollTop = el.scrollHeight;
}
function finishLog(el, ok) {
  const cls = ok ? 'done-ok' : 'done-err';
  el.innerHTML += `<span class="${cls}">── ${ok ? '完成' : '结束（有错误）'} ──</span>\n`;
  el.scrollTop = el.scrollHeight;
}

// ── SSE GET
function streamGet(url, logEl, onDone) {
  logEl.innerHTML = '';
  const src = new EventSource(url);
  src.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.line !== undefined) appendLog(logEl, d.line);
    if (d.done) { finishLog(logEl, d.ok); src.close(); refreshStats(); if(onDone) onDone(); }
  };
  src.onerror = () => { appendLog(logEl, '❌ 连接中断'); src.close(); if(onDone) onDone(); };
}

// ── SSE POST (fetch + ReadableStream)
function streamPost(url, body, logEl, onDone) {
  logEl.innerHTML = '';
  fetch(url, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(r => {
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = '';
      function pump() {
        reader.read().then(({done, value}) => {
          if (done) { if(onDone) onDone(); return; }
          buf += dec.decode(value, {stream:true});
          const parts = buf.split('\n\n'); buf = parts.pop();
          parts.forEach(p => {
            if (p.startsWith('data: ')) {
              const d = JSON.parse(p.slice(6));
              if (d.line !== undefined) appendLog(logEl, d.line);
              if (d.done) { finishLog(logEl, d.ok); refreshStats(); }
            }
          });
          pump();
        });
      }
      pump();
    })
    .catch(e => { appendLog(logEl, '❌ ' + e); if(onDone) onDone(); });
}

// ── 处理 URL
function processUrl() {
  const url = document.getElementById('url-input').value.trim();
  if (!url) { alert('请先输入链接'); return; }
  const title = document.getElementById('url-title').value.trim();
  const scrapeOnly = document.getElementById('url-scrape-only').checked;
  const btn = document.getElementById('btn-url');
  btn.disabled = true;
  streamPost('/api/run/url', {url, title, scrape_only: scrapeOnly},
    document.getElementById('log-url'), () => btn.disabled = false);
}

// ── 时间范围下拉
function onSinceChange() {
  const val = document.getElementById('since-preset').value;
  document.getElementById('since-date').style.display = val === 'custom' ? '' : 'none';
}
function getSince() {
  const preset = document.getElementById('since-preset').value;
  if (preset === 'custom') return document.getElementById('since-date').value;
  return preset;
}

// ── 流水线
function runPipeline(cmd) {
  const source = document.getElementById('pipeline-source').value.trim();
  const since = getSince();
  let qs = [];
  if (source) qs.push('source=' + encodeURIComponent(source));
  if (since)  qs.push('since=' + encodeURIComponent(since));
  const url = '/api/run/' + cmd + (qs.length ? '?' + qs.join('&') : '');
  document.querySelectorAll('#tab-pipeline .btn').forEach(b => b.disabled = true);
  streamGet(url, document.getElementById('log-pipeline'),
    () => document.querySelectorAll('#tab-pipeline .btn').forEach(b => b.disabled = false));
}

// ── 来源管理
let _sources = [];
let _editingName = null;   // null = 新增模式；字符串 = 正在编辑的来源名称

function loadSources() {
  fetch('/api/sources').then(r=>r.json()).then(d => {
    _sources = d.sources || [];
    renderSources();
  });
}
function renderSources() {
  const tb = document.getElementById('sources-body');
  if (!_sources.length) {
    tb.innerHTML = '<tr><td colspan="6" class="empty">sources.yaml 中暂无来源</td></tr>'; return;
  }
  tb.innerHTML = _sources.map(s => {
    const typeBadge = s.type === 'youtube_channel'
      ? '<span class="badge badge-blue">YouTube</span>'
      : '<span class="badge badge-gray">RSS</span>';
    const detail = s.feed_url
      ? `<span style="font-size:11px;color:#aaa" title="${esc(s.feed_url)}">${esc(s.feed_url.slice(0,45))}${s.feed_url.length>45?'…':''}</span>`
      : `<span style="font-size:12px">@${esc(s.channel_handle||'')}${s.title_filter?` · 过滤: ${esc(s.title_filter)}`:''}` + '</span>';
    return `<tr>
      <td><strong>${esc(s.name||'')}</strong></td>
      <td>${typeBadge}</td>
      <td>${esc(s.category||'—')}</td>
      <td style="text-align:center">${s.max_episodes||'—'}</td>
      <td>${detail}</td>
      <td style="white-space:nowrap">
        <button class="btn btn-ghost" style="font-size:12px;padding:5px 10px;margin-right:4px" onclick="editSource('${esc(s.name||'')}')">编辑</button>
        <button class="btn btn-red" onclick="deleteSource('${esc(s.name||'')}')">删除</button>
      </td>
    </tr>`;
  }).join('');
}
function _resetAddForm() {
  _editingName = null;
  document.getElementById('add-form-title').textContent = '添加新来源';
  document.getElementById('add-form-submit').textContent = '保存';
  document.getElementById('add-name').value = '';
  document.getElementById('add-feed-url').value = '';
  document.getElementById('add-handle').value = '';
  document.getElementById('add-filter').value = '';
  document.getElementById('add-category').value = '';
  document.getElementById('add-max').value = '3';
  document.getElementById('add-lock-category').checked = false;
  document.querySelectorAll('input[name=add-type]').forEach(r => r.checked = false);
  document.getElementById('cond-rss').style.display = 'none';
  document.getElementById('cond-yt').style.display = 'none';
  document.getElementById('add-error').textContent = '';
}
function toggleAddForm() {
  const f = document.getElementById('add-form');
  const willOpen = !f.classList.contains('visible');
  if (!willOpen) _resetAddForm();
  f.classList.toggle('visible');
  if (!willOpen) document.getElementById('add-error').textContent = '';
}
function editSource(name) {
  const s = _sources.find(x => x.name === name);
  if (!s) return;
  _editingName = name;
  document.getElementById('add-form-title').textContent = `编辑来源：${name}`;
  document.getElementById('add-form-submit').textContent = '保存修改';
  document.getElementById('add-name').value = s.name || '';
  document.getElementById('add-category').value = s.category || '';
  document.getElementById('add-max').value = s.max_episodes || 3;
  document.getElementById('add-lock-category').checked = !!s.lock_category;
  // 设置类型单选框
  const radio = document.querySelector(`input[name=add-type][value="${s.type}"]`);
  if (radio) { radio.checked = true; onTypeChange(); }
  if (s.type === 'rss') {
    document.getElementById('add-feed-url').value = s.feed_url || '';
  } else {
    document.getElementById('add-handle').value = s.channel_handle || '';
    document.getElementById('add-filter').value = s.title_filter || '';
  }
  document.getElementById('add-error').textContent = '';
  document.getElementById('add-form').classList.add('visible');
  document.getElementById('add-form').scrollIntoView({behavior: 'smooth', block: 'nearest'});
}
function onTypeChange() {
  const val = document.querySelector('input[name=add-type]:checked')?.value;
  document.getElementById('cond-rss').style.display = val === 'rss' ? 'block' : 'none';
  document.getElementById('cond-yt').style.display  = val === 'youtube_channel' ? 'block' : 'none';
}
function submitAddSource() {
  const name = document.getElementById('add-name').value.trim();
  const type = document.querySelector('input[name=add-type]:checked')?.value || '';
  const errEl = document.getElementById('add-error');
  if (!name) { errEl.textContent = '请填写名称'; return; }
  if (!type) { errEl.textContent = '请选择类型'; return; }
  const body = {
    name, type,
    category: document.getElementById('add-category').value.trim() || '其他',
    max_episodes: parseInt(document.getElementById('add-max').value) || 3,
    lock_category: document.getElementById('add-lock-category').checked,
  };
  if (type === 'rss') {
    body.feed_url = document.getElementById('add-feed-url').value.trim();
    if (!body.feed_url) { errEl.textContent = '请填写 Feed URL'; return; }
  } else {
    body.channel_handle = document.getElementById('add-handle').value.trim().replace(/^@/, '');
    if (!body.channel_handle) { errEl.textContent = '请填写频道 Handle'; return; }
    const f = document.getElementById('add-filter').value.trim();
    if (f) body.title_filter = f;
  }
  const isEdit = _editingName !== null;
  const url = isEdit
    ? '/api/sources/' + encodeURIComponent(_editingName)
    : '/api/sources';
  fetch(url, {method: isEdit ? 'PUT' : 'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})
    .then(r=>r.json()).then(d => {
      if (d.ok) {
        _resetAddForm();
        document.getElementById('add-form').classList.remove('visible');
        loadSources(); refreshStats();
      } else {
        errEl.textContent = d.error || (isEdit ? '保存失败' : '添加失败');
      }
    });
}
function deleteSource(name) {
  if (!confirm(`确定删除来源「${name}」吗？`)) return;
  fetch('/api/sources/' + encodeURIComponent(name), {method:'DELETE'})
    .then(r=>r.json()).then(d => {
      if (d.ok) { loadSources(); refreshStats(); }
      else alert('删除失败：' + d.error);
    });
}

// ── 纪要列表（带分类过滤）
let _allSummaries = [], _activeCategory = '全部';
function loadSummaries() {
  fetch('/api/summaries').then(r=>r.json()).then(d => {
    _allSummaries = d.summaries || [];
    const cats = ['全部', ...(d.categories || [])];
    const bar = document.getElementById('cat-bar');
    bar.innerHTML = cats.map(c =>
      `<button class="cat-btn${c===_activeCategory?' active':''}" onclick="filterSummaries('${esc(c)}')">${esc(c)}</button>`
    ).join('');
    renderSummaries();
  });
}
function filterSummaries(cat) {
  _activeCategory = cat;
  document.querySelectorAll('.cat-btn').forEach(b => {
    b.classList.toggle('active', b.textContent === cat);
  });
  renderSummaries();
}
function renderSummaries() {
  const list = _activeCategory === '全部'
    ? _allSummaries
    : _allSummaries.filter(s => s.category === _activeCategory);
  const tb = document.getElementById('summaries-body');
  if (!list.length) { tb.innerHTML = '<tr><td colspan="5" class="empty">暂无纪要</td></tr>'; return; }
  tb.innerHTML = list.map((s, i) => `
    <tr>
      <td style="color:#ccc;width:36px;font-size:12px">${list.length - i}</td>
      <td>
        <div class="sum-title">${esc(s.title)}</div>
        ${s.abstract ? `<div class="sum-abstract">${esc(s.abstract)}</div>` : ''}
        <div class="sum-meta">${esc(s.slug)}</div>
      </td>
      <td><span class="badge badge-blue">${esc(s.category||'—')}</span></td>
      <td style="font-size:12px;color:#888;white-space:nowrap">${esc(s.date||'—')}</td>
      <td style="white-space:nowrap">
        <button class="btn btn-red" onclick="deleteSummary('${esc(s.slug)}','${esc(s.title)}')">删除</button>
      </td>
    </tr>`).join('');
}
function deleteSummary(slug, title) {
  if (!confirm(`确定删除「${title}」？\n\n将同时删除纪要文件并重新部署到 Cloudflare。`)) return;
  const logCard = document.getElementById('delete-log-card');
  const logEl = document.getElementById('log-delete');
  logCard.style.display = '';
  logEl.scrollIntoView({behavior:'smooth', block:'nearest'});
  // 先删文件
  fetch('/api/summaries/' + encodeURIComponent(slug), {method:'DELETE'})
    .then(r => r.json())
    .then(d => {
      if (!d.ok) { appendLog(logEl, '❌ 删除失败：' + d.error); return; }
      appendLog(logEl, `✅ 已删除：${slug}`);
      appendLog(logEl, '正在重建并部署...');
      // 触发重建 HTML + 部署到 Cloudflare（只跑 generator.py）
      streamGet('/api/run/rebuild', logEl, () => {
        loadSummaries();
        refreshStats();
      });
    })
    .catch(e => appendLog(logEl, '❌ ' + e));
}

// ── 设置
function loadSettings() {
  fetch('/api/settings').then(r=>r.json()).then(d => {
    if (!d.ok) return;
    const ark = d.settings['ARK_API_KEY'];
    const arkEl = document.getElementById('ark-status');
    if (ark && ark.set) {
      arkEl.textContent = '✓ 已设置 ' + ark.hint;
      arkEl.style.color = '#34a853';
    } else {
      arkEl.textContent = '⚠ 未设置';
      arkEl.style.color = '#ea8600';
    }
    const cf = d.settings['CLOUDFLARE_API_TOKEN'];
    const cfEl = document.getElementById('cf-status');
    if (cf && cf.set) {
      cfEl.textContent = '✓ 已设置 ' + cf.hint;
      cfEl.style.color = '#34a853';
    } else {
      cfEl.textContent = '⚠ 未设置（部署将跳过）';
      cfEl.style.color = '#ea8600';
    }
    const bc = d.settings['BROWSER_COOKIES'];
    const bcEl = document.getElementById('bc-status');
    if (bc && bc.set) {
      bcEl.textContent = '✓ 已设置：' + bc.hint;
      bcEl.style.color = '#34a853';
    } else {
      bcEl.textContent = '未设置（仅公开内容可用）';
      bcEl.style.color = '#aaa';
    }
  });
}
function toggleArkVisible() {
  const inp = document.getElementById('ark-key-input');
  const btn = event.target;
  if (inp.type === 'password') { inp.type = 'text';  btn.textContent = '隐藏'; }
  else                         { inp.type = 'password'; btn.textContent = '显示'; }
}
function toggleCfVisible() {
  const inp = document.getElementById('cf-key-input');
  const btn = event.target;
  if (inp.type === 'password') { inp.type = 'text';  btn.textContent = '隐藏'; }
  else                         { inp.type = 'password'; btn.textContent = '显示'; }
}
function saveSettings() {
  const arkKey = document.getElementById('ark-key-input').value.trim();
  const cfKey  = document.getElementById('cf-key-input').value.trim();
  const bcVal  = document.getElementById('bc-input').value.trim();
  const msg = document.getElementById('settings-msg');
  if (!arkKey && !cfKey && !bcVal) { msg.style.color='#ea8600'; msg.textContent = '未填写任何字段，无需保存。'; return; }
  const body = {};
  if (arkKey) body.ARK_API_KEY = arkKey;
  if (cfKey)  body.CLOUDFLARE_API_TOKEN = cfKey;
  if (bcVal)  body.BROWSER_COOKIES = bcVal;
  fetch('/api/settings', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body),
  }).then(r=>r.json()).then(d => {
    if (d.ok) {
      msg.style.color = '#34a853';
      msg.textContent = '✅ 保存成功，已立即生效。';
      document.getElementById('ark-key-input').value = '';
      document.getElementById('cf-key-input').value = '';
      document.getElementById('bc-input').value = '';
      loadSettings();
    } else {
      msg.style.color = '#c62828';
      msg.textContent = '❌ 保存失败：' + d.error;
    }
  });
}

// ── 状态统计
function refreshStats() {
  fetch('/api/status').then(r=>r.json()).then(d => {
    document.getElementById('chip-sources').textContent = d.sources + ' 来源';
    document.getElementById('chip-summaries').textContent = d.summaries + ' 纪要';
  }).catch(()=>{});
}
refreshStats();
</script>
</body>
</html>
"""

# ── 入口 ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('🎙 播客纪要管理界面已启动')
    print('   请在浏览器打开：http://localhost:8080')
    app.run(host='127.0.0.1', port=8080, debug=False, threaded=True)
