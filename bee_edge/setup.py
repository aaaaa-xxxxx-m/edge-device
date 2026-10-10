"""设备配置向导：获取并校验云端下发的设备名 + API Key，写入 config.toml。

用法（交互）：
    python main.py --mode setup

用法（非交互 / 脚本）：
    python main.py --mode setup --device-name hive001 --api-key bee_xxx --server http://<server-ip>

也可从文件读取（形如 device_key.txt）：
    device_name: hive001
    key: bee_xxx
    python main.py --mode setup --key-file device_key.txt
"""
from __future__ import annotations

import os
import re
from typing import Optional

from .server import AuthError, ServerClient, ServerError

DEFAULT_SERVER = "http://<server-ip>"

TEMPLATE = '''# 智能蜂箱 · 边缘设备配置（由 setup 生成）
device_name = "{device_name}"
api_key = "{api_key}"
server_base_url = "{server_base_url}"

# 采样与模式
normal_interval_s = 90
collect_interval_s = 30
sample_rate = 16000
audio_seconds = 6
dht_pin = 11
dht_sensor = "DHT22"
alsa_device = "plughw:1,0"

# 本地文件
model_dir = "models"
state_file = "state.json"
public_key_file = "model_public_key.pem"

# 网络 / 日志
http_timeout_s = 20
log_level = "INFO"

# 显示
display_width = 0
display_height = 0
font_path = ""
'''


def parse_key_file(path: str) -> tuple[Optional[str], Optional[str]]:
    name = key = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip().lower(), v.strip()
            if k in ("device_name", "device", "name"):
                name = v
            elif k in ("key", "api_key", "apikey"):
                key = v
    return name, key


def _prompt(label: str, default: str = "") -> str:
    try:
        val = input(f"{label}" + (f" [{default}]" if default else "") + ": ").strip()
    except EOFError:
        val = ""
    return val or default


def _write_config(path: str, device_name: str, api_key: str, server: str) -> None:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()

        def set_kv(text: str, key: str, val: str) -> str:
            line = f'{key} = "{val}"'
            if re.search(rf"(?m)^{re.escape(key)}\s*=.*$", text):
                return re.sub(rf"(?m)^{re.escape(key)}\s*=.*$", line, text)
            return text.rstrip() + "\n" + line + "\n"

        text = set_kv(text, "device_name", device_name)
        text = set_kv(text, "api_key", api_key)
        text = set_kv(text, "server_base_url", server)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE.format(device_name=device_name, api_key=api_key, server_base_url=server))


def run_setup(config_path: str, args) -> int:
    device_name = getattr(args, "device_name", None)
    api_key = getattr(args, "api_key", None)
    server = getattr(args, "server", None) or DEFAULT_SERVER
    key_file = getattr(args, "key_file", None)
    force = getattr(args, "force", False)

    if key_file:
        n, k = parse_key_file(key_file)
        device_name = device_name or n
        api_key = api_key or k

    print("== 设备配置向导 ==")
    print(f"配置文件：{os.path.abspath(config_path)}")
    if os.path.exists(config_path) and not force:
        print("（已存在 config.toml，将仅更新 device_name / api_key / server_base_url）")

    if not server:
        server = _prompt("服务器地址", DEFAULT_SERVER)
    if not device_name:
        device_name = _prompt("设备名 (device_name)")
    if not api_key:
        api_key = _prompt("设备 API Key")

    if not device_name or not api_key:
        print("错误：device_name 与 api_key 都不能为空")
        return 2

    print(f"\n正在校验：{server} / 设备 '{device_name}' ...")
    try:
        client = ServerClient(server, api_key, timeout=15.0)
        st = client.get_model_status(device_name)
        print(f"校验通过（OK）  当前训练状态：{st.get('status', '?')}")
    except AuthError as e:
        print(f"校验失败（密钥无效 / 设备不存在 / 名称不匹配）：{e}")
        return 3
    except ServerError as e:
        print(f"无法连接服务器（请检查网络与 server_base_url）：{e}")
        return 4

    _write_config(config_path, device_name, api_key, server)
    print(f"\n已写入配置：{os.path.abspath(config_path)}")
    print("下一步：确认麦克风设备号后启动服务：")
    print("  arecord -l")
    print("  sudo systemctl enable --now bee-edge bee-display")
    return 0
