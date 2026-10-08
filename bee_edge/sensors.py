"""DHT22 温湿度读取（Adafruit_DHT）。读取失败返回 (None, None)。"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)

try:
    import Adafruit_DHT as _DHT  # type: ignore
except Exception:  # noqa: BLE001 - 本地/无 GPIO 环境无此库
    _DHT = None
    log.warning("Adafruit_DHT 不可用：温湿度将为空")


def _sensor_type(name: str):
    if _DHT is None:
        return None
    return getattr(_DHT, name, getattr(_DHT, "DHT22", None))


def read_dht(pin: int, sensor_name: str = "DHT22") -> Tuple[Optional[float], Optional[float]]:
    """返回 (温度℃, 湿度%)；失败返回 (None, None)。"""
    sensor = _sensor_type(sensor_name)
    if _DHT is None or sensor is None:
        return None, None
    for _ in range(3):
        humidity, temperature = _DHT.read_retry(sensor, pin)
        if humidity is not None and temperature is not None:
            try:
                return float(round(temperature, 1)), float(round(humidity, 1))
            except (TypeError, ValueError):
                return None, None
    return None, None
