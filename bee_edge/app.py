"""采集主循环：录音→特征→本地推理→上传→状态→模型更新检查→按模式休眠。"""
from __future__ import annotations

import io
import logging
import time
from datetime import datetime
from typing import Optional

import numpy as np
import requests

from .audio import decode_wav, record_wav
from .config import EdgeConfig
from .features import extract_60d_feature
from .inference import LocalModel, status_of
from .model_store import ModelStore
from .sensors import read_dht
from .server import AuthError, ServerClient, ServerError
from .state import write_state

log = logging.getLogger("bee_edge.app")


def _utc_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _ts() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%S")


def _npy_bytes(vec: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, vec)
    return buf.getvalue()


class EdgeApp:
    def __init__(self, cfg: EdgeConfig):
        self.cfg = cfg
        self.client = ServerClient(cfg.server_base_url, cfg.api_key, cfg.http_timeout_s)
        self.store = ModelStore(cfg.model_dir, cfg.public_key_file)
        self.model: Optional[LocalModel] = None
        self.auth_failed = False

    # ---------- 模型 ----------
    def _fetch_url(self, url: str) -> bytes:
        resp = requests.get(url, timeout=self.cfg.http_timeout_s)
        resp.raise_for_status()
        return resp.content

    def _sync_public_key(self) -> None:
        try:
            pem = self.client.get_public_key_pem()
            if pem:
                self.store.set_public_key_pem(pem)
        except Exception as e:  # noqa: BLE001
            log.warning("获取公钥失败：%s", e)

    def refresh_model(self, force: bool = False) -> None:
        """检查云端模型清单，有新版本则下载校验安装并加载。"""
        manifest = self.client.get_model(self.cfg.device_name)
        if not manifest.get("has_model"):
            if not self.store.have_model():
                log.info("云端暂无该设备模型")
            return
        version = manifest.get("version")
        if not force and self.store.have_model() and version == self.store.current_version():
            if self.model is None:
                self.model = self.store.load()
            return
        log.info("发现新模型 version=%s，开始下载", version)
        svm_bytes = self._fetch_url(manifest["model_url"])
        scaler_bytes = self._fetch_url(manifest["scaler_url"]) if manifest.get("scaler_url") else None
        if self.store.verify_and_install(svm_bytes, scaler_bytes, manifest):
            self.model = self.store.load()
        else:
            log.error("模型校验/安装失败，保留原模型")

    # ---------- 单轮 ----------
    def _cycle(self) -> None:
        cfg = self.cfg
        t_start = time.time()

        # 1. 温湿度
        temperature, humidity = read_dht(cfg.dht_pin, cfg.dht_sensor)

        # 2. 录音
        wav_bytes: Optional[bytes] = None
        try:
            wav_bytes = record_wav(cfg.audio_seconds, cfg.sample_rate, cfg.alsa_device)
        except Exception as e:  # noqa: BLE001
            log.error("录音失败：%s", e)

        # 3. 特征
        feature: Optional[np.ndarray] = None
        if wav_bytes is not None:
            try:
                samples, rate, _ch = decode_wav(wav_bytes)
                feature = extract_60d_feature(samples, rate)
            except Exception as e:  # noqa: BLE001
                log.error("特征提取失败：%s", e)

        ts = _ts()

        # 4. 上传音频 + 特征
        audio_key: Optional[str] = None
        feature_key: Optional[str] = None
        if wav_bytes is not None:
            try:
                audio_key = self.client.upload_audio(cfg.device_name, wav_bytes, ts)
            except AuthError:
                raise
            except Exception as e:  # noqa: BLE001
                log.error("上传音频失败：%s", e)
        if feature is not None:
            try:
                feature_key = self.client.upload_feature(cfg.device_name, _npy_bytes(feature), ts)
            except AuthError:
                raise
            except Exception as e:  # noqa: BLE001
                log.error("上传特征失败：%s", e)

        # 5. 本地推理 + 上报
        p_no = None
        p_norm = None
        label = None
        conf = None
        infer_ms = None
        version = self.store.current_version() or "unknown"
        if self.model is not None and feature is not None:
            try:
                t0 = time.time()
                pred = self.model.predict(feature)
                infer_ms = int((time.time() - t0) * 1000)
                p_no, p_norm, label, conf = (
                    pred.probability_no_queen,
                    pred.probability_normal,
                    pred.label,
                    pred.confidence,
                )
            except Exception as e:  # noqa: BLE001
                log.error("本地推理失败：%s", e)

        synced = False
        if audio_key and p_no is not None:
            payload = {
                "audio_object_key": audio_key,
                "feature_object_key": feature_key,
                "model_version": version,
                "probability_no_queen": p_no,
                "probability_normal": p_norm,
                "label": label,
                "confidence": conf,
                "inference_time_ms": infer_ms,
                "temperature": temperature,
                "humidity": humidity,
            }
            try:
                self.client.post_inference(payload)
                synced = True
            except AuthError:
                raise
            except Exception as e:  # noqa: BLE001
                log.error("上报推理失败：%s", e)

        # 6. 写状态
        status_text, tone = status_of(p_no)
        write_state(cfg.state_file, {
            "device_name": cfg.device_name,
            "temperature": temperature,
            "humidity": humidity,
            "probability_no_queen": p_no,
            "status": status_text,
            "tone": tone,
            "model_version": version,
            "updated_at": _utc_iso(),
            "synced": synced,
            "cycle_ms": int((time.time() - t_start) * 1000),
        })

    # ---------- 主循环 ----------
    def run(self) -> None:
        cfg = self.cfg
        log.info("边缘系统启动：device=%s server=%s", cfg.device_name, cfg.server_base_url)

        # 初始：公钥 + 模型
        self._sync_public_key()
        try:
            self.refresh_model(force=True)
        except AuthError:
            log.error("鉴权失败：请检查 API Key")
            self.auth_failed = True
        except Exception as e:  # noqa: BLE001
            log.warning("初始模型检查失败：%s", e)

        while True:
            interval = cfg.normal_interval_s
            try:
                self._cycle()
            except AuthError as e:
                self.auth_failed = True
                log.error("鉴权失败（密钥失效/设备注销）：%s", e)
            except Exception as e:  # noqa: BLE001
                log.exception("本轮采集异常：%s", e)

            # 模型更新检查
            try:
                self.refresh_model()
            except AuthError as e:
                self.auth_failed = True
                log.error("鉴权失败：%s", e)
            except Exception as e:  # noqa: BLE001
                log.warning("模型检查失败：%s", e)

            # 决定下一轮间隔（有训练任务 → 采集模式）
            try:
                st = self.client.get_model_status(cfg.device_name)
                if st.get("has_active"):
                    interval = cfg.collect_interval_s
                    log.info("采集模式：feature %s/%s", st.get("feature_count"), st.get("required"))
            except AuthError:
                self.auth_failed = True
            except Exception as e:  # noqa: BLE001
                log.warning("查询训练状态失败：%s", e)

            if self.auth_failed:
                interval = max(interval, 300.0)  # 鉴权失败时放慢重试

            log.info("本轮结束，休眠 %.0fs", interval)
            time.sleep(interval)
