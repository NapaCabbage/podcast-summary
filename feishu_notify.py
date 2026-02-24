"""
飞书推送通知模块
流水线完成后主动向飞书群发送更新摘要。

支持两种方式（优先用 Webhook，更简单）：

方式 A：群自定义机器人 Webhook（推荐）
  飞书群 → 设置 → 机器人 → 添加机器人 → 自定义机器人 → 复制 Webhook 地址
  .env 中添加：FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx

方式 B：应用机器人（需要 App ID/Secret + 群 Chat ID）
  .env 中添加：
    FEISHU_APP_ID=cli_xxx
    FEISHU_APP_SECRET=xxx
    FEISHU_CHAT_ID=oc_xxx     （群 Chat ID，在群设置 → 群信息中获取）
"""

import os
import json
from urllib.request import urlopen, Request
from datetime import datetime


def _send_webhook(webhook_url, text):
    """向群自定义机器人 Webhook 发送文本消息"""
    body = json.dumps({
        'msg_type': 'text',
        'content': {'text': text},
    }).encode()
    req = Request(webhook_url, data=body, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _get_token(app_id, app_secret):
    url = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
    body = json.dumps({'app_id': app_id, 'app_secret': app_secret}).encode()
    req = Request(url, data=body, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read()).get('tenant_access_token', '')


def _send_bot(app_id, app_secret, chat_id, text):
    """通过应用机器人向指定群发送文本消息"""
    token = _get_token(app_id, app_secret)
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


def build_message(episodes, site_url=''):
    """
    构建推送消息文本。
    episodes: [(title, category), ...]
    """
    today = datetime.now().strftime('%Y-%m-%d')
    lines = [f'📬 播客纪要 · {today} 更新（{len(episodes)} 篇）', '']

    # 按分类分组
    groups = {}
    for title, category in episodes:
        groups.setdefault(category, []).append(title)

    for category, titles in groups.items():
        for title in titles:
            lines.append(f'[{category}] {title}')

    if site_url:
        lines.append('')
        lines.append(f'🌐 {site_url}')

    return '\n'.join(lines)


def notify(episodes, site_url=''):
    """
    发送流水线完成通知。
    episodes: [(title, category), ...]
    有 FEISHU_WEBHOOK_URL 时用 Webhook，否则用 Bot API。
    若两者都没配置，静默跳过。
    """
    if not episodes:
        return

    webhook_url = os.environ.get('FEISHU_WEBHOOK_URL', '')
    app_id      = os.environ.get('FEISHU_APP_ID', '')
    app_secret  = os.environ.get('FEISHU_APP_SECRET', '')
    chat_id     = os.environ.get('FEISHU_CHAT_ID', '')
    site_url    = os.environ.get('SITE_URL', site_url)

    if not webhook_url and not (app_id and app_secret and chat_id):
        # 未配置推送，静默跳过
        return

    text = build_message(episodes, site_url)

    try:
        if webhook_url:
            _send_webhook(webhook_url, text)
            print(f'[飞书通知] 已推送到群 Webhook（{len(episodes)} 篇）')
        else:
            _send_bot(app_id, app_secret, chat_id, text)
            print(f'[飞书通知] 已推送到群 {chat_id}（{len(episodes)} 篇）')
    except Exception as e:
        print(f'[飞书通知] 推送失败（不影响主流程）：{e}')
