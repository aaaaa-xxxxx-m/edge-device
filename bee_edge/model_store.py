"""本地模型管理：版本记录、Ed25519 验签、原子替换与加载。"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import tempfile
from typing import Optional

from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .inference import LocalModel

log = logging.getLogger(__name__)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: str, data: bytes) -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".m_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


class ModelStore:
    def __init__(self, model_dir: str, public_key_file: str):
        self.dir = model_dir
        os.makedirs(self.dir, exist_ok=True)
        self.svm_path = os.path.join(self.dir, "svm.pkl")
        self.scaler_path = os.path.join(self.dir, "scaler.pkl")
        self.manifest_path = os.path.join(self.dir, "manifest.json")
        self.public_key_path = public_key_file

    # ---- 状态 ----
    def have_model(self) -> bool:
        return os.path.exists(self.svm_path) and os.path.exists(self.scaler_path)

    def current_version(self) -> Optional[str]:
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                return json.load(f).get("version")
        except (OSError, ValueError):
            return None

    def load(self) -> LocalModel:
        return LocalModel.load(self.svm_path, self.scaler_path)

    # ---- 公钥 ----
    def set_public_key_pem(self, pem: str) -> None:
        _atomic_write(self.public_key_path, pem.encode("utf-8"))

    def _public_key(self):
        with open(self.public_key_path, "r", encoding="utf-8") as f:
            return load_pem_public_key(f.read().encode("utf-8"))

    # ---- 校验并安装 ----
    def verify_and_install(
        self,
        svm_bytes: bytes,
        scaler_bytes: Optional[bytes],
        manifest: dict,
    ) -> bool:
        """校验 sha256 + Ed25519 签名，通过后原子替换。返回是否成功。"""
        if not scaler_bytes:
            log.error("模型包缺少 scaler，拒绝安装")
            return False

        sha_svm = _sha256_hex(svm_bytes)
        sha_scaler = _sha256_hex(scaler_bytes)

        expect_sha = manifest.get("sha256")
        if expect_sha and expect_sha != sha_svm:
            log.error("模型 sha256 不匹配：期望 %s 实际 %s", expect_sha, sha_svm)
            return False

        signature = manifest.get("signature") or ""
        if not signature:
            log.error("模型清单缺少签名，拒绝安装")
            return False
        try:
            pub = self._public_key()
            pub.verify(base64.b64decode(signature), (sha_svm + sha_scaler).encode())
        except FileNotFoundError:
            log.error("缺少公钥文件，无法验签")
            return False
        except Exception as e:  # noqa: BLE001 - 验签失败
            log.error("模型签名校验失败：%s", e)
            return False

        # 原子写入（先 scaler 再 svm 再 manifest；svm 最后保证 have_model 一致）
        _atomic_write(self.scaler_path, scaler_bytes)
        _atomic_write(self.svm_path, svm_bytes)
        _atomic_write(
            self.manifest_path,
            json.dumps(
                {
                    "version": manifest.get("version"),
                    "sha256": sha_svm,
                    "scaler_sha256": sha_scaler,
                    "signature": signature,
                    "updated_at": manifest.get("updated_at"),
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        log.info("模型已更新：version=%s", manifest.get("version"))
        return True
