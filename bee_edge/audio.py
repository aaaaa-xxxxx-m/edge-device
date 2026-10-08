"""录音与音频解码。

录音优先使用 ALSA `arecord`（树莓派上最稳，无需编译 pyaudio）；
返回标准 WAV 字节，再解码为 int16 单声道 PCM 供特征提取。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import wave
from typing import Tuple

import numpy as np

log = logging.getLogger(__name__)


def record_wav(seconds: float, sample_rate: int, device: str) -> bytes:
    """用 arecord 录制 WAV，返回文件字节。"""
    arecord = shutil.which("arecord")
    if not arecord:
        raise RuntimeError("未找到 arecord，请安装 alsa-utils")

    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        cmd = [
            arecord,
            "-D", device,
            "-c", "1",
            "-r", str(int(sample_rate)),
            "-f", "S16_LE",
            "-t", "wav",
            "-d", str(max(1, int(round(seconds)))),
            path,
        ]
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(f"arecord 失败：{proc.stderr.decode(errors='replace').strip()}")
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def decode_wav(wav_bytes: bytes) -> Tuple[np.ndarray, int, int]:
    """解码 WAV → (int16 一维数组, 采样率, 声道数)。多声道取第一声道。"""
    import io

    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        channels = w.getnchannels()
        rate = w.getframerate()
        width = w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"仅支持 16bit PCM，当前 {width * 8}bit")
    data = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels)[:, 0]
    return data.copy(), rate, channels


def to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    """int16 数组 → WAV 字节（用于测试/回放）。"""
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(samples.astype("<i2").tobytes())
    return buf.getvalue()
