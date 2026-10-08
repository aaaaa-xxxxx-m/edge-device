"""云端接口客户端（设备端，X-API-Key）。

封装：预签名上传、推理上报、模型清单/训练状态、公钥获取。带重试与超时。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional, Tuple

import requests

log = logging.getLogger(__name__)


class ServerError(Exception):
    """网络/服务端错误（可重试）。"""


class AuthError(Exception):
    """鉴权失败（401/403，密钥失效或设备注销，不宜频繁重试）。"""


class ServerClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 20.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": api_key, "Accept": "application/json"})

    def _url(self, path: str) -> str:
        return f"{self.base}/api/v1{path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        retries: int = 3,
    ) -> Any:
        url = self._url(path)
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                resp = self.session.request(
                    method, url, params=params, json=json_body, timeout=self.timeout
                )
                if resp.status_code in (401, 403):
                    raise AuthError(f"{resp.status_code} {resp.text[:200]}")
                if resp.status_code >= 500:
                    raise ServerError(f"{resp.status_code} {resp.text[:200]}")
                if resp.status_code >= 400:
                    raise ServerError(f"{resp.status_code} {resp.text[:200]}")
                if not resp.content:
                    return None
                return resp.json()
            except AuthError:
                raise
            except (requests.RequestException, ServerError, ValueError) as e:
                last = e
                log.warning("请求失败 %s %s（第 %d 次）：%s", method, path, attempt + 1, e)
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
        raise ServerError(f"请求最终失败 {method} {path}: {last}")

    # ---- 上传 ----
    def presign_upload(self, kind: str, filename: str, content_type: str) -> Tuple[str, str]:
        r = self._request(
            "GET",
            "/devices/me/presigned-url",
            params={"kind": kind, "filename": filename, "content_type": content_type},
        )
        data = (r or {}).get("data") or {}
        return data["upload_url"], data["object_key"]

    def put_upload(self, url: str, data: bytes, content_type: str, retries: int = 3) -> None:
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                resp = requests.put(
                    url, data=data, headers={"Content-Type": content_type}, timeout=self.timeout
                )
                if resp.status_code >= 400:
                    raise ServerError(f"PUT {resp.status_code} {resp.text[:120]}")
                return
            except (requests.RequestException, ServerError) as e:
                last = e
                log.warning("上传失败（第 %d 次）：%s", attempt + 1, e)
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
        raise ServerError(f"上传最终失败：{last}")

    # ---- 上传（先预签名再直传，含一次重新预签名） ----
    def upload_audio(self, device_name: str, wav_bytes: bytes, ts: str) -> str:
        url, key = self.presign_upload("audio", f"{ts}.wav", "audio/wav")
        self.put_upload(url, wav_bytes, "audio/wav")
        return key

    def upload_feature(self, device_name: str, npy_bytes: bytes, ts: str) -> str:
        url, key = self.presign_upload("feature", f"{ts}.npy", "application/octet-stream")
        self.put_upload(url, npy_bytes, "application/octet-stream")
        return key

    # ---- 推理上报 ----
    def post_inference(self, payload: dict) -> dict:
        return self._request("POST", "/devices/inference", json_body=payload, retries=2)

    # ---- 模型 ----
    def get_model(self, device_name: str) -> dict:
        r = self._request("GET", f"/devices/{device_name}/model")
        return (r or {}).get("data") or {}

    def get_model_status(self, device_name: str) -> dict:
        r = self._request("GET", f"/devices/{device_name}/model-status", retries=2)
        return r or {}

    def get_public_key_pem(self) -> str:
        r = self._request("GET", "/models/public-key")
        return (r or {}).get("public_key_pem", "")
