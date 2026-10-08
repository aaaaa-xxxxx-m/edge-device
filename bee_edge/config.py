"""配置加载（TOML）。"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    import tomllib as _toml  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as _toml  # 兼容旧 Python
    except ModuleNotFoundError:  # pragma: no cover
        _toml = None


@dataclass
class EdgeConfig:
    device_name: str
    api_key: str
    server_base_url: str = "http://8.156.79.6"
    # 采集
    normal_interval_s: float = 90.0
    collect_interval_s: float = 30.0
    sample_rate: int = 16000
    audio_seconds: float = 6.0
    dht_pin: int = 11
    dht_sensor: str = "DHT22"
    alsa_device: str = "plughw:1,0"
    # 本地文件
    model_dir: str = "models"
    state_file: str = "state.json"
    public_key_file: str = "model_public_key.pem"
    # 网络
    http_timeout_s: float = 20.0
    # 其它
    log_level: str = "INFO"
    # 显示（0 = 自适应）
    display_width: int = 0
    display_height: int = 0
    font_path: str = ""


def _resolve(base: str, p: str) -> str:
    return p if os.path.isabs(p) else os.path.join(base, p)


def load_config(path: str) -> EdgeConfig:
    if _toml is None:
        raise RuntimeError("加载配置需要 Python 3.11+（tomllib）或安装 tomli")
    with open(path, "rb") as f:
        raw = _toml.load(f)

    base = os.path.dirname(os.path.abspath(path))

    def g(key: str, default=None):
        return raw.get(key, default)

    device_name = g("device_name")
    api_key = g("api_key") or os.environ.get("BEE_API_KEY", "")
    if not device_name:
        raise ValueError("配置缺少 device_name")
    if not api_key:
        raise ValueError("配置缺少 api_key（可放 config.toml 或环境变量 BEE_API_KEY）")

    return EdgeConfig(
        device_name=str(device_name),
        api_key=str(api_key),
        server_base_url=str(g("server_base_url", "http://8.156.79.6")),
        normal_interval_s=float(g("normal_interval_s", 90.0)),
        collect_interval_s=float(g("collect_interval_s", 30.0)),
        sample_rate=int(g("sample_rate", 16000)),
        audio_seconds=float(g("audio_seconds", 6.0)),
        dht_pin=int(g("dht_pin", 11)),
        dht_sensor=str(g("dht_sensor", "DHT22")),
        alsa_device=str(g("alsa_device", "plughw:1,0")),
        model_dir=_resolve(base, str(g("model_dir", "models"))),
        state_file=_resolve(base, str(g("state_file", "state.json"))),
        public_key_file=_resolve(base, str(g("public_key_file", "model_public_key.pem"))),
        http_timeout_s=float(g("http_timeout_s", 20.0)),
        log_level=str(g("log_level", "INFO")).upper(),
        display_width=int(g("display_width", 0)),
        display_height=int(g("display_height", 0)),
        font_path=str(g("font_path", "")),
    )
