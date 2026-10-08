"""DHT22 温湿度读取（Adafruit_DHT）。读取失败返回 (None, None)。"""
from __future__ import annotations

import logging
import time
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
    """返回 (温度℃, 湿度%)；任意失败（含驱动缺失/接线问题）返回 (None, None)，不抛出。

    用单次读 + 少量重试（避免 read_retry 默认 15×2s 的长时间阻塞）。
    """
    sensor = _sensor_type(sensor_name)
    if _DHT is None or sensor is None:
        return None, None
    for _ in range(3):
        try:
            humidity, temperature = _DHT.read(sensor, pin)
        except Exception as e:  # noqa: BLE001 - 驱动/权限/接线等
            log.warning("读取 DHT 失败：%s", e)
            break
        if humidity is not None and temperature is not None:
            return float(round(temperature, 1)), float(round(humidity, 1))
        time.sleep(0.5)
    return None, None
