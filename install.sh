#!/bin/sh
# 智能蜂箱 · 边缘设备安装脚本（在树莓派上以 root/sudo 运行）
set -e

APP_DIR=/opt/bee-edge
HERE=$(cd "$(dirname "$0")" && pwd)

echo "[1/5] 安装系统依赖 ..."
apt-get update
apt-get install -y python3-venv python3-dev alsa-utils fonts-noto-cjk python3-pygame

echo "[2/5] 拷贝程序到 $APP_DIR ..."
mkdir -p "$APP_DIR"
cp -r "$HERE"/. "$APP_DIR"/

echo "[3/5] 创建 venv 并安装 Python 依赖 ..."
cd "$APP_DIR"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
# DHT22（需要编译）；失败可尝试 apt 包
./.venv/bin/pip install Adafruit_DHT || echo "!! Adafruit_DHT 安装失败，请手动处理（见 README）"

echo "[4/5] 生成配置 ..."
[ -f config.toml ] || cp config.example.toml config.toml

echo "[5/5] 安装 systemd 服务 ..."
install -m 644 bee-edge.service /etc/systemd/system/bee-edge.service
install -m 644 bee-display.service /etc/systemd/system/bee-display.service
systemctl daemon-reload

echo ""
echo "安装完成。请："
echo "  1) 编辑 $APP_DIR/config.toml 填写 device_name 与 api_key"
echo "  2) 用 \`arecord -l\` 确认麦克风设备并设置 alsa_device"
echo "  3) raspi-config 选择 'Console Autologin'（无桌面），以支持 pygame kmsdrm"
echo "  4) 启用服务：sudo systemctl enable --now bee-edge bee-display"
echo "  5) 查看日志：journalctl -u bee-edge -f"
