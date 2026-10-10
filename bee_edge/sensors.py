"""DHT22 温湿度读取（Adafruit_DHT）。读取失败返回 (None, None)，不抛出。

Adafruit_DHT 的位操作对时序极敏感：在 Pi Zero + 新内核 + 系统负载下，单次读取
会偶发校验失败（实测失败率 20%~60%）。因此这里：
  1. 多次重试，间隔 ≥2s（满足 DHT22 采样周期）；
  2. 全部失败时，若上次成功读数足够新（< CACHE_MAX_AGE_S），则沿用上次读数，
     避免偶发失败导致上游「无温湿度数据」；超过保鲜期才置空（交上游判定暂无数据）；
  3. 记录失败日志以便观测。
"""
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

MAX_RETRIES = 5              # 单轮最多读取次数
RETRY_SPACING_S = 2.1        # 重试间隔（DHT22 要求采样周期 ≥2s）
CACHE_MAX_AGE_S = 900.0      # 上次读数最多沿用多久（超过则视为无数据）

_last_ok: Optional[Tuple[float, float]] = None
_last_ok_ts: float = 0.0


def _sensor_type(name: str):
    if _DHT is None:
        return None
    return getattr(_DHT, name, getattr(_DHT, "DHT22", None))


def read_dht(pin: int, sensor_name: str = "DHT22") -> Tuple[Optional[float], Optional[float]]:
    """返回 (温度℃, 湿度%)；任意失败（含驱动缺失/接线问题）返回 (None, None)，不抛出。"""
    global _last_ok, _last_ok_ts

    sensor = _sensor_type(sensor_name)
    if _DHT is None or sensor is None:
        return None, None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            humidity, temperature = _DHT.read(sensor, pin)
        except Exception as e:  # noqa: BLE001 - 驱动/权限/接线等
            log.warning("读取 DHT 异常（第 %d/%d 次）：%s", attempt, MAX_RETRIES, e)
            humidity = temperature = None
        if humidity is not None and temperature is not None:
            _last_ok = (float(round(temperature, 1)), float(round(humidity, 1)))
            _last_ok_ts = time.time()
            return _last_ok
        if attempt < MAX_RETRIES:
            log.info("DHT 读取失败（第 %d/%d 次），%.1fs 后重试", attempt, MAX_RETRIES, RETRY_SPACING_S)
            time.sleep(RETRY_SPACING_S)

    age = time.time() - _last_ok_ts
    if _last_ok is not None and age < CACHE_MAX_AGE_S:
        log.warning("DHT 连续 %d 次失败，沿用 %.0fs 前的读数 %.1f℃/%.1f%%",
                    MAX_RETRIES, age, _last_ok[0], _last_ok[1])
        return _last_ok
    log.warning("DHT 连续 %d 次失败且无新鲜缓存，本轮温湿度置空", MAX_RETRIES)
    return None, None
