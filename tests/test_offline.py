"""离线自测：不依赖硬件，验证核心纯逻辑。运行： python tests/test_offline.py"""
import base64
import hashlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np


def test_feature_dim():
    from bee_edge.features import extract_60d_feature, FEATURE_DIM
    rng = np.random.default_rng(0)
    pcm = rng.integers(-32768, 32767, size=16000 * 3, dtype=np.int16)
    f = extract_60d_feature(pcm, 16000)
    assert f.shape == (FEATURE_DIM,), f.shape
    print(f"[ok] 60维特征 shape={f.shape}")


def test_status_of():
    from bee_edge.inference import status_of
    assert status_of(None)[0] == "等待模型"
    assert status_of(0.1)[0] == "正常"
    assert status_of(0.5)[1] == "warn"
    assert status_of(0.9)[0] == "失王"
    print("[ok] 状态分级")


def test_state_roundtrip():
    from bee_edge.state import write_state, read_state
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "sub", "state.json")
        write_state(p, {"device_name": "hive001", "temperature": 34.1, "中文": "值"})
        s = read_state(p)
        assert s["device_name"] == "hive001" and s["中文"] == "值"
    print("[ok] state 原子读写")


def test_model_verify_install():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from bee_edge.model_store import ModelStore

    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    svm = b"fake-svm-bytes"
    scaler = b"fake-scaler-bytes"
    sha_svm = hashlib.sha256(svm).hexdigest()
    sha_scaler = hashlib.sha256(scaler).hexdigest()
    sig = base64.b64encode(priv.sign((sha_svm + sha_scaler).encode())).decode()

    with tempfile.TemporaryDirectory() as d:
        store = ModelStore(os.path.join(d, "models"), os.path.join(d, "pub.pem"))
        store.set_public_key_pem(pub_pem)
        ok = store.verify_and_install(svm, scaler, {"version": "v1", "sha256": sha_svm, "signature": sig})
        assert ok and store.have_model() and store.current_version() == "v1"
        # 篡改签名 → 失败
        bad = store.verify_and_install(svm, scaler, {"version": "v2", "sha256": sha_svm, "signature": "AAAA"})
        assert not bad and store.current_version() == "v1"
    print("[ok] 模型验签 + 原子安装（且拒绝坏签名）")


if __name__ == "__main__":
    test_feature_dim()
    test_status_of()
    test_state_roundtrip()
    test_model_verify_install()
    print("\n全部通过")
