"""
飞书机器人 Webhook 服务
接收飞书消息 → 执行 feed_monitor.py 命令 → 回复结果

部署方式：
  python feishu_bot.py          # 前台运行（测试用）
  nohup python feishu_bot.py &  # 后台运行

环境变量（放在 .env 文件中）：
  FEISHU_APP_ID         飞书应用 App ID
  FEISHU_APP_SECRET     飞书应用 App Secret
  FEISHU_VERIFY_TOKEN   事件订阅验证 Token
  ARK_API_KEY           豆包 API Key（运行完整流水线时需要）

飞书后台配置：
  1. 开发者后台 → 创建企业自建应用
  2. 能力 → 机器人
  3. 事件订阅 → 请求地址：http://YOUR_ECS_IP:8080/feishu
  4. 事件订阅 → 添加事件：im.message.receive_v1
  5. 权限管理 → 开通：im:message（读取消息）+ im:message:send_as_bot（发送消息）
  6. 发布应用
"""

import os
import json
import hashlib
import hmac
import subprocess
import threading
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.parse import urlencode

# ── 配置 ────────────────────────────────────────────────────────────
APP_ID       = os.environ.get('FEISHU_APP_ID', '')
APP_SECRET   = os.environ.get('FEISHU_APP_SECRET', '')
VERIFY_TOKEN = os.environ.get('FEISHU_VERIFY_TOKEN', '')

APP_DIR  = os.path.dirname(os.path.abspath(__file__))
PYTHON   = os.path.join(APP_DIR, '.venv', 'bin', 'python3')
if not os.path.exists(PYTHON):
    PYTHON = sys.executable

PORT = 8080

HELP_TEXT = """\
🤖 播客纪要助手

可用指令：
  检查      — dry-run，列出新集数（不处理）
  抓取      — 只抓取原文，不调用 AI
  处理      — 完整流水线：抓取 + 生成纪要 + 重建网页
  来源      — 列出当前订阅的来源
  纪要      — 列出已生成的纪要
  帮助      — 显示本说明

示例：
  "处理 Lex Fridman"  → 只处理该来源
  "抓取 Latent Space" → 只抓取该来源原文
"""


# ── 飞书 API ─────────────────────────────────────────────────────────

def get_tenant_access_token():
    """获取 tenant_access_token"""
    url = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
    body = json.dumps({'app_id': APP_ID, 'app_secret': APP_SECRET}).encode()
    req = Request(url, data=body, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data.get('tenant_access_token', '')


def send_message(chat_id, text):
    """向飞书会话发送文本消息"""
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


# ── 命令解析与执行 ────────────────────────────────────────────────────

def parse_command(text):
    """
    解析用户消息，返回 (cmd, source_name)
    cmd: 'dry-run' | 'scrape' | 'process' | 'sources' | 'summaries' | 'help'
    source_name: 指定来源（可为空）
    """
    text = text.strip()
    lower = text.lower()

    # 提取来源名（"处理 Lex Fridman" → "Lex Fridman"）
    source = ''
    for prefix in ['处理 ', '抓取 ', 'process ', 'scrape ']:
        if lower.startswith(prefix):
            source = text[len(prefix):].strip()
            break

    if any(k in lower for k in ['检查', 'dry-run', 'dry run', '有什么新的', '有新的']):
        return 'dry-run', source
    if any(k in lower for k in ['抓取', 'scrape', 'scrape-only']):
        return 'scrape', source
    if any(k in lower for k in ['处理', 'process', '运行', '更新', '流水线']):
        return 'process', source
    if any(k in lower for k in ['来源', 'sources', '频道', '列表']):
        return 'sources', ''
    if any(k in lower for k in ['纪要', 'summaries', '有哪些']):
        return 'summaries', ''
    return 'help', ''


def run_command(cmd, source=''):
    """执行命令，返回输出字符串（最多 2000 字符）"""
    env = {**os.environ, 'PYTHONUNBUFFERED': '1'}

    if cmd == 'dry-run':
        args = [PYTHON, 'feed_monitor.py', '--dry-run']
        if source:
            args += ['--source', source]

    elif cmd == 'scrape':
        args = [PYTHON, 'feed_monitor.py', '--scrape-only']
        if source:
            args += ['--source', source]

    elif cmd == 'process':
        args = [PYTHON, 'feed_monitor.py']
        if source:
            args += ['--source', source]

    elif cmd == 'sources':
        try:
            with open(os.path.join(APP_DIR, 'sources.yaml'), encoding='utf-8') as f:
                return f.read()[:2000]
        except Exception as e:
            return f'读取来源配置失败：{e}'

    elif cmd == 'summaries':
        summaries_dir = os.path.join(APP_DIR, 'summaries')
        try:
            files = sorted(os.listdir(summaries_dir))
            md_files = [f for f in files if f.endswith('.md')]
            return f'共 {len(md_files)} 篇纪要：\n' + '\n'.join(md_files[:50])
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


def handle_message_async(chat_id, text):
    """在后台线程处理消息，避免 HTTP handler 超时"""
    try:
        send_message(chat_id, '⏳ 处理中，请稍候...')
    except Exception:
        pass

    cmd, source = parse_command(text)
    output = run_command(cmd, source)

    try:
        send_message(chat_id, output)
    except Exception as e:
        print(f'[Error] 发送消息失败：{e}')


# ── HTTP 服务 ─────────────────────────────────────────────────────────

class FeishuHandler(BaseHTTPRequestHandler):

    def do_POST(self):
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

        # 飞书事件验证（URL 验证握手）
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
        content_raw = msg.get('content', '{}')
        try:
            content = json.loads(content_raw)
        except Exception:
            content = {}
        text = content.get('text', '').strip()

        # @机器人时飞书会在文本前加 @_user_1 等，去掉
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
    print(f'飞书 Bot 监听 :{PORT}/feishu ...')
    server = HTTPServer(('0.0.0.0', PORT), FeishuHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')
