# 云服务器部署指南

## 前提条件

- Ubuntu 22.04 LTS VPS（1 核 1GB 内存够用）
- 域名（可选，有更好）
- SSH 访问权限（root）
- ARK_API_KEY（豆包 API）

---

## 第一步：购买并连接服务器

推荐云服务商（国内访问 GitHub/YouTube 注意网络）：
- 阿里云 ECS / 腾讯云 CVM（国内访问快，但需备案才能开 80/443）
- AWS EC2 / DigitalOcean（海外，无需备案，可直接访问 YouTube）

```bash
ssh root@YOUR_SERVER_IP
```

---

## 第二步：上传代码到服务器

**方式 A：Git（推荐，方便后续更新）**
```bash
# 在服务器上
git clone https://github.com/YOUR_USERNAME/podcast-summary.git /opt/podcast-summary
cd /opt/podcast-summary
```

**方式 B：rsync 直接同步本地文件**
```bash
# 在本机执行
rsync -avz --exclude='.git' --exclude='raw/' --exclude='summaries/' --exclude='output/' \
    "/Users/zongbocai/AI Playground/podcast-summary/" \
    root@YOUR_SERVER_IP:/opt/podcast-summary/
```

---

## 第三步：运行初始化脚本

```bash
cd /opt/podcast-summary
bash deploy/setup.sh
```

脚本会自动完成：
- 安装系统依赖（Python3、Nginx、Certbot）
- 创建 `podcast` 用户
- 创建 Python 虚拟环境并安装依赖
- 创建 `/opt/podcast-summary/.env` 环境变量文件

---

## 第四步：填入 API Key

```bash
nano /opt/podcast-summary/.env
```

将 `your_key_here` 替换为真实的 ARK_API_KEY：
```
ARK_API_KEY=d3309bf2-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

---

## 第五步：配置 Nginx

```bash
# 替换域名
sed -i 's/YOUR_DOMAIN/your-domain.com/g' /opt/podcast-summary/deploy/nginx.conf

# 安装配置
cp /opt/podcast-summary/deploy/nginx.conf /etc/nginx/sites-available/podcast
ln -s /etc/nginx/sites-available/podcast /etc/nginx/sites-enabled/podcast
rm -f /etc/nginx/sites-enabled/default   # 移除默认配置

# 测试并重启
nginx -t && systemctl reload nginx
```

**申请免费 SSL 证书（有域名才能做）：**
```bash
certbot --nginx -d your-domain.com
# Certbot 会自动修改 nginx.conf 加入 HTTPS 配置
```

---

## 第六步：手动跑一次测试

```bash
su - podcast
cd /opt/podcast-summary
source .env

# 先 dry-run 确认能发现新集数
python3 feed_monitor.py --dry-run

# 确认没问题后正式运行
python3 feed_monitor.py
```

---

## 第七步：设置自动定时任务

```bash
su - podcast
crontab -e
```

将 [crontab.txt](crontab.txt) 中的内容粘贴进去，保存退出。

创建日志目录：
```bash
mkdir -p /opt/podcast-summary/logs
```

验证 cron 是否生效：
```bash
crontab -l
```

---

## 日常操作

**手动触发更新：**
```bash
su - podcast -c "cd /opt/podcast-summary && source .env && python3 feed_monitor.py"
```

**查看运行日志：**
```bash
tail -f /opt/podcast-summary/logs/cron.log
```

**更新代码（Git 方式）：**
```bash
cd /opt/podcast-summary
git pull
su - podcast -c "/opt/podcast-summary/.venv/bin/pip install -q -r /opt/podcast-summary/requirements.txt"
```

**修改来源配置：**
```bash
nano /opt/podcast-summary/sources.yaml
```

---

## 目录结构

```
/opt/podcast-summary/
├── .env              ← API Key（仅 root/podcast 可读）
├── .venv/            ← Python 虚拟环境
├── raw/              ← 抓取的原始文字稿
├── summaries/        ← 生成的 Markdown 纪要
├── output/           ← 最终 HTML（Nginx 对外 serve 这个目录）
├── logs/             ← cron 运行日志
├── sources.yaml      ← 来源配置
├── feed_monitor.py   ← 主流水线
├── auto_summarize.py ← AI 纪要生成
├── generator.py      ← HTML 生成
└── deploy/           ← 本部署配置目录
```
