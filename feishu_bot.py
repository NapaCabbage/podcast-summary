"""
飞书机器人 Webhook 服务
接收飞书消息 → 执行命令或处理 URL → 回复结果

支持两类消息：
  1. 指令消息：检查 / 抓取 / 处理 / 来源 / 纪要 / 帮助
  2. URL 消息：直接发送链接（自动抓取 + 生成纪要 + 重建网页）

部署方式：
  python feishu_bot.py          # 前台运行（测试用）
  nohup python feishu_bot.py &  # 后台运行

环境变量（放在 .env 文件中）：
  FEISHU_APP_ID         飞书应用 App ID
  FEISHU_APP_SECRET     飞书应用 App Secret
  FEISHU_VERIFY_TOKEN   事件订阅验证 Token
  ARK_API_KEY           豆包 API Key（生成纪要时需要）

飞书后台配置：
  1. 开发者后台 → 创建企业自建应用
  2. 能力 → 机器人
  3. 事件订阅 → 请求地址：http://YOUR_ECS_IP:8080/feishu
  4. 事件订阅 → 添加事件：im.message.receive_v1
  5. 权限管理 → 开通：im:message + im:message:send_as_bot
  6. 发布应用
"""

import os
import re
import json
import subprocess
import threading
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request

# ── 配置 ─────────────────────────────────────────────────────────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))
# 确保工作目录在 APP_DIR，使 feed_monitor 的相对路径生效
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

APP_ID       = os.environ.get('FEISHU_APP_ID', '')
APP_SECRET   = os.environ.get('FEISHU_APP_SECRET', '')
VERIFY_TOKEN = os.environ.get('FEISHU_VERIFY_TOKEN', '')

PYTHON = os.path.join(APP_DIR, '.venv', 'bin', 'python3')
if not os.path.exists(PYTHON):
    PYTHON = sys.executable

PORT = 8080

# URL 检测正则
URL_RE = re.compile(r'https?://[^\s\u3000\uff0c\u3001\u3002\uff1f\uff01]+')

HELP_TEXT = """\
🤖 播客纪要助手

━━ 发送链接，自动处理 ━━
  直接发 URL         → 抓取 + 生成纪要 + 更新网页
  标题：xxx + URL    → 用指定标题处理
  只抓 URL           → 只抓原文，不调用 AI

  示例：
    https://youtu.be/xxxxx
    标题：Dario on AI Safety  https://youtu.be/xxxxx
    只抓 https://www.dwarkesh.com/p/episode

━━ 订阅来源管理 ━━
  检查    — 列出新集数（不处理）
  抓取    — 抓取所有新集数（不调用 AI）
  处理    — 完整流水线：抓取 + 生成纪要 + 重建网页
  抓取 Lex Fridman  → 只处理该来源
  处理 Latent Space → 只处理该来源

━━ 查询 ━━
  来源    — 列出当前订阅来源
  纪要    — 列出已生成的纪要
  帮助    — 显示本说明
"""


# ── 飞书 API ─────────────────────────────────────────────────────────

def get_tenant_access_token():
    url = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
    body = json.dumps({'app_id': APP_ID, 'app_secret': APP_SECRET}).encode()
    req = Request(url, data=body, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data.get('tenant_access_token', '')


def send_message(chat_id, text):
    token = get_tenant_access_token()
    url = 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id'
    body = json.dumps({
        'receive_id': chat_id,
        'msg_type': 'text',
        'content': json.dumps({'text': text}),
    }).encode()
    req = Request(url, data=body, headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}',
    })
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ── URL 处理 ──────────────────────────────────────────────────────────

def extract_url_and_title(text):
    """
    从消息中提取 (url, title, scrape_only)。
    支持格式：
      https://...
      标题：xxx  https://...
      只抓 https://...
    返回 (url, title, scrape_only)，无 URL 返回 (None, '', False)
    """
    urls = URL_RE.findall(text)
    if not urls:
        return None, '', False

    url = urls[0]
    title = ''
    scrape_only = any(k in text for k in ['只抓', '只爬', 'scrape only', '不生成纪要'])

    # 提取用户给的标题
    for prefix in ['标题：', '标题:', 'title:', 'Title:']:
        if prefix in text:
            after = text.split(prefix, 1)[1]
            # 标题到 URL 或换行为止
            candidate = re.split(r'https?://|\n', after)[0].strip()
            if candidate:
                title = candidate
            break

    return url, title, scrape_only


def fetch_url_title(url):
    """自动从 URL 提取标题（YouTube 用 oEmbed，其他抓 og:title / <title>）"""
    try:
        if 'youtube.com' in url or 'youtu.be' in url:
            oembed = f'https://www.youtube.com/oembed?url={url}&format=json'
            req = Request(oembed, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            return data.get('title', '')

        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(req, timeout=15) as resp:
            html = resp.read(80000).decode('utf-8', errors='ignore')

        # og:title 优先
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:title["\']', html, re.I)
        if m:
            return m.group(1).strip()

        m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
        if m:
            return m.group(1).strip()
    except Exception as e:
        print(f'[fetch_url_title] {e}')
    return ''


def run_url(url, title='', scrape_only=False):
    """
    处理单条 URL：抓取 → (可选) 生成纪要 → 重建网页。
    返回回复文本。
    """
    from feed_monitor import scrape_episode, detect_category, slugify

    env = {**os.environ, 'PYTHONUNBUFFERED': '1'}
    lines = []

    # ① 获取标题
    if not title:
        print(f'[run_url] 自动获取标题：{url}')
        title = fetch_url_title(url)
    if not title:
        title = url.rstrip('/').split('/')[-1] or 'untitled'
    print(f'[run_url] 标题={title!r}  scrape_only={scrape_only}')

    # ② 检查是否已存在
    slug = slugify(title)
    raw_path = os.path.join(APP_DIR, 'raw', f'{slug}.txt')
    summary_path = os.path.join(APP_DIR, 'summaries', f'{slug}.md')

    if os.path.exists(raw_path):
        lines.append(f'⚠️ 原文已存在：raw/{slug}.txt')
        if scrape_only:
            return '\n'.join(lines)
        # 已有原文但没有纪要，继续生成纪要
        if os.path.exists(summary_path):
            lines.append(f'⚠️ 纪要也已存在：summaries/{slug}.md，无需重新处理。')
            return '\n'.join(lines)
    else:
        # ③ 抓取
        try:
            category = detect_category(title, '其他')
            slug, char_count = scrape_episode(title, url, '', category)
            lines.append(f'✅ 抓取完成：{title}')
            lines.append(f'   {char_count:,} 字符 → raw/{slug}.txt')
        except Exception as e:
            return f'❌ 抓取失败：{e}'

    if scrape_only:
        lines.append(f'\n如需生成纪要，发送：处理纪要 {slug}')
        return '\n'.join(lines)

    # ④ 生成纪要
    lines.append('正在生成纪要（约 1-2 分钟）...')
    # 提前发一条进度消息（调用方负责发送，这里只返回中间状态不发送）
    result = subprocess.run(
        [PYTHON, 'auto_summarize.py', slug],
        capture_output=True, text=True,
        cwd=APP_DIR, env=env, timeout=300,
    )
    if result.returncode == 0:
        lines.append(f'✅ 纪要已生成：summaries/{slug}.md')
    else:
        err = (result.stdout + result.stderr).strip()[:300]
        lines.append(f'⚠️ 纪要生成异常：{err}')

    # ⑤ 重建网页
    subprocess.run(
        [PYTHON, 'generator.py'],
        capture_output=True, text=True,
        cwd=APP_DIR, env=env, timeout=60,
    )
    lines.append('✅ 网页已更新')

    return '\n'.join(lines)


# ── 指令处理 ──────────────────────────────────────────────────────────

def parse_command(text):
    """
    解析指令消息，返回 (cmd, source_name)
    cmd: 'dry-run' | 'scrape' | 'process' | 'sources' | 'summaries' | 'help'
         | 'make-summary'（只对已有 raw 生成纪要）
    """
    lower = text.lower()

    source = ''
    for prefix in ['处理 ', '抓取 ', 'process ', 'scrape ']:
        if lower.startswith(prefix):
            source = text[len(prefix):].strip()
            break

    # "处理纪要 <slug>" → 对已有 raw 文件生成纪要
    if lower.startswith('处理纪要 ') or lower.startswith('生成纪要 '):
        slug = text.split(' ', 1)[1].strip()
        return 'make-summary', slug

    if any(k in lower for k in ['检查', 'dry-run', 'dry run', '有什么新的', '有新的']):
        return 'dry-run', source
    if any(k in lower for k in ['只抓取', '抓取', 'scrape']):
        return 'scrape', source
    if any(k in lower for k in ['处理', 'process', '运行', '更新', '流水线']):
        return 'process', source
    if any(k in lower for k in ['来源', 'sources', '频道', '列表']):
        return 'sources', ''
    if any(k in lower for k in ['纪要', 'summaries', '有哪些']):
        return 'summaries', ''
    return 'help', ''


def run_command(cmd, arg=''):
    """执行指令，返回输出文本"""
    env = {**os.environ, 'PYTHONUNBUFFERED': '1'}

    if cmd == 'dry-run':
        args = [PYTHON, 'feed_monitor.py', '--dry-run']
        if arg:
            args += ['--source', arg]

    elif cmd == 'scrape':
        args = [PYTHON, 'feed_monitor.py', '--scrape-only']
        if arg:
            args += ['--source', arg]

    elif cmd == 'process':
        args = [PYTHON, 'feed_monitor.py']
        if arg:
            args += ['--source', arg]

    elif cmd == 'make-summary':
        slug = arg
        if not slug:
            return '用法：处理纪要 <slug>'
        result = subprocess.run(
            [PYTHON, 'auto_summarize.py', slug],
            capture_output=True, text=True,
            cwd=APP_DIR, env=env, timeout=300,
        )
        subprocess.run([PYTHON, 'generator.py'], capture_output=True,
                       cwd=APP_DIR, env=env, timeout=60)
        out = (result.stdout + result.stderr).strip()
        return (out[:1800] + '\n✅ 网页已更新') if result.returncode == 0 else f'⚠️ {out[:1800]}'

    elif cmd == 'sources':
        try:
            with open(os.path.join(APP_DIR, 'sources.yaml'), encoding='utf-8') as f:
                return f.read()[:2000]
        except Exception as e:
            return f'读取来源配置失败：{e}'

    elif cmd == 'summaries':
        summaries_dir = os.path.join(APP_DIR, 'summaries')
        try:
            files = sorted(f for f in os.listdir(summaries_dir) if f.endswith('.md'))
            return f'共 {len(files)} 篇纪要：\n' + '\n'.join(files[:50])
        except Exception as e:
            return f'读取纪要列表失败：{e}'

    else:
        return HELP_TEXT

    try:
        result = subprocess.run(
            args, capture_output=True, text=True,
            cwd=APP_DIR, env=env, timeout=300,
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 2000:
            output = output[:1900] + '\n…（输出已截断）'
        return output or '（无输出）'
    except subprocess.TimeoutExpired:
        return '⏰ 命令执行超时（5分钟），请稍后查看日志。'
    except Exception as e:
        return f'执行失败：{e}'


# ── 消息分发 ──────────────────────────────────────────────────────────

def handle_message_async(chat_id, text):
    """后台线程：解析消息类型，执行并回复"""
    try:
        send_message(chat_id, '⏳ 处理中，请稍候...')
    except Exception:
        pass

    # 优先检测 URL
    url, title, scrape_only = extract_url_and_title(text)
    if url:
        output = run_url(url, title, scrape_only)
    else:
        cmd, arg = parse_command(text)
        output = run_command(cmd, arg)

    try:
        send_message(chat_id, output)
    except Exception as e:
        print(f'[Error] 发送消息失败：{e}')


# ── HTTP 服务 ─────────────────────────────────────────────────────────
#
# 端点总览：
#   POST /feishu              飞书事件 Webhook（给飞书平台用）
#   GET  /api/check           检查新集数（dry-run）?source=可选
#   GET  /api/sources         列出订阅来源
#   GET  /api/summaries       列出已生成纪要
#   POST /api/process         完整流水线  {"source":"可选"}
#   POST /api/scrape          只抓取原文  {"source":"可选"}
#   POST /api/url             处理指定链接 {"url":"...","title":"可选","scrape_only":false}
#
# 所有 /api/* 返回 JSON：{"ok": true/false, "output": "文本结果"}

def _api_response(ok, output):
    return json.dumps({'ok': ok, 'output': output}, ensure_ascii=False)


def _run_in_thread_and_wait(fn, *args, timeout=360):
    """在子线程中运行 fn(*args)，阻塞等待结果（避免长任务卡主线程池）"""
    result = [None]
    exc    = [None]
    def target():
        try:
            result[0] = fn(*args)
        except Exception as e:
            exc[0] = e
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return '⏰ 执行超时，任务仍在后台运行，请稍后查看日志。'
    if exc[0]:
        return f'❌ 执行异常：{exc[0]}'
    return result[0]


class FeishuHandler(BaseHTTPRequestHandler):

    # ── GET /api/* ────────────────────────────────────────────────────

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        def qp(key):
            vals = params.get(key, [''])
            return vals[0].strip() if vals else ''

        if parsed.path == '/api/check':
            source = qp('source')
            output = run_command('dry-run', source)
            self._reply(200, _api_response(True, output))

        elif parsed.path == '/api/sources':
            output = run_command('sources')
            self._reply(200, _api_response(True, output))

        elif parsed.path == '/api/summaries':
            output = run_command('summaries')
            self._reply(200, _api_response(True, output))

        else:
            self._reply(404, _api_response(False, 'Unknown endpoint'))

    # ── POST /feishu  +  POST /api/* ─────────────────────────────────

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        raw_body = self.rfile.read(length)

        # ── /api/* 路由 ───────────────────────────────────────────────
        if self.path.startswith('/api/'):
            try:
                body = json.loads(raw_body) if raw_body else {}
            except Exception:
                body = {}

            if self.path == '/api/process':
                source = body.get('source', '')
                output = _run_in_thread_and_wait(run_command, 'process', source)
                self._reply(200, _api_response(True, output))

            elif self.path == '/api/scrape':
                source = body.get('source', '')
                output = _run_in_thread_and_wait(run_command, 'scrape', source)
                self._reply(200, _api_response(True, output))

            elif self.path == '/api/url':
                url        = body.get('url', '')
                title      = body.get('title', '')
                scrape_only = body.get('scrape_only', False)
                if not url:
                    self._reply(400, _api_response(False, '缺少 url 参数'))
                    return
                output = _run_in_thread_and_wait(run_url, url, title, scrape_only)
                self._reply(200, _api_response(True, output))

            else:
                self._reply(404, _api_response(False, 'Unknown endpoint'))
            return

        # ── /feishu 飞书 Webhook ──────────────────────────────────────
        if self.path != '/feishu':
            self._reply(404, 'Not found')
            return

        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._reply(400, 'Bad JSON')
            return

        # 飞书 URL 验证握手
        if data.get('type') == 'url_verification':
            challenge = data.get('challenge', '')
            self._reply(200, json.dumps({'challenge': challenge}))
            return

        # 处理消息事件
        event = data.get('event', {})
        msg = event.get('message', {})
        sender = event.get('sender', {})

        # 忽略 bot 自己发的消息
        if sender.get('sender_type') == 'app':
            self._reply(200, 'ok')
            return

        chat_id = msg.get('chat_id', '')
        try:
            content = json.loads(msg.get('content', '{}'))
        except Exception:
            content = {}
        text = content.get('text', '').strip()

        # 去掉飞书自动加的 @mention 前缀
        if text.startswith('@'):
            text = ' '.join(text.split()[1:]).strip()

        if chat_id and text:
            threading.Thread(
                target=handle_message_async,
                args=(chat_id, text),
                daemon=True,
            ).start()

        self._reply(200, 'ok')

    def _reply(self, code, body):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f'[{self.address_string()}] ' + fmt % args)


# ── 入口 ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if not APP_ID or not APP_SECRET:
        print('[警告] FEISHU_APP_ID / FEISHU_APP_SECRET 未设置，将无法主动发送消息。')
    print(f'飞书 Bot 监听 :{PORT}/feishu  工作目录={APP_DIR}')
    server = HTTPServer(('0.0.0.0', PORT), FeishuHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')
