#!/bin/bash
# 云服务器一键初始化脚本
# 适用于 Ubuntu 22.04 LTS
# 用法：bash setup.sh

set -e  # 任意步骤失败即终止

APP_DIR="/opt/podcast-summary"
APP_USER="podcast"
PYTHON="python3"

echo "=== 播客纪要服务器初始化 ==="
echo ""

# ── 1. 系统更新 & 基础依赖 ─────────────────────────────────────
echo "[1/6] 更新系统并安装依赖..."
apt-get update -q
apt-get install -y -q python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git

# ── 2. 创建专用用户 ────────────────────────────────────────────
echo "[2/6] 创建应用用户 '$APP_USER'..."
if ! id "$APP_USER" &>/dev/null; then
    useradd -r -m -s /bin/bash "$APP_USER"
fi

# ── 3. 部署应用代码 ────────────────────────────────────────────
echo "[3/6] 部署应用代码到 $APP_DIR ..."
mkdir -p "$APP_DIR"
cp -r . "$APP_DIR/"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ── 4. 安装 Python 依赖（虚拟环境） ───────────────────────────
echo "[4/6] 创建虚拟环境并安装 Python 依赖..."
su - "$APP_USER" -c "
    $PYTHON -m venv $APP_DIR/.venv
    $APP_DIR/.venv/bin/pip install -q --upgrade pip
    $APP_DIR/.venv/bin/pip install -q -r $APP_DIR/requirements.txt
"

# ── 5. 创建目录结构 ────────────────────────────────────────────
echo "[5/6] 创建数据目录..."
su - "$APP_USER" -c "
    mkdir -p $APP_DIR/raw
    mkdir -p $APP_DIR/summaries
    mkdir -p $APP_DIR/output
"

# ── 6. 写入环境变量文件（需手动填入 Key） ─────────────────────
echo "[6/6] 创建环境变量文件..."
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<'EOF'
# 填入你的 Ark API Key
ARK_API_KEY=your_key_here
EOF
    chown "$APP_USER:$APP_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo ""
    echo "⚠️  请编辑 $ENV_FILE 填入 ARK_API_KEY！"
fi

echo ""
echo "=== 初始化完成 ==="
echo ""
echo "后续步骤："
echo "  1. 编辑 $ENV_FILE，填入 ARK_API_KEY"
echo "  2. 配置 Nginx：cp deploy/nginx.conf /etc/nginx/sites-available/podcast"
echo "  3. 配置域名，申请 SSL：certbot --nginx -d your-domain.com"
echo "  4. 设置 cron：参考 deploy/crontab.txt"
