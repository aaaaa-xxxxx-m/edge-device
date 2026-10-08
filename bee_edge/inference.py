"""本地 SVM 推理（joblib 加载 svm.pkl + scaler.pkl）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import joblib
import numpy as np


@dataclass
class Prediction:
    probability_no_queen: float
    probability_normal: float
    label: str  # "no_queen" | "normal"
    confidence: float


class LocalModel:
    """封装 model + scaler 的本地推理。

    训练口径：正样本(设备正常) = 0，负样本(预置失王) = 1；
    因此 class 1 的预测概率即「失王概率」。
    """

    def __init__(self, model, scaler):
        self.model = model
        self.scaler = scaler
        classes = list(getattr(model, "classes_", [0, 1]))
        self._idx_no = classes.index(1) if 1 in classes else 1

    @classmethod
    def load(cls, svm_path: str, scaler_path: str) -> "LocalModel":
        model = joblib.load(svm_path)
        scaler = joblib.load(scaler_path)
        return cls(model, scaler)

    def predict(self, feature: np.ndarray) -> Prediction:
        x = self.scaler.transform(np.asarray(feature, dtype=np.float64).reshape(1, -1))
        proba = self.model.predict_proba(x)[0]
        p_no = float(proba[self._idx_no])
        p_norm = float(1.0 - p_no)
        label = "no_queen" if p_no >= 0.5 else "normal"
        return Prediction(
            probability_no_queen=p_no,
            probability_normal=p_norm,
            label=label,
            confidence=max(p_no, p_norm),
        )


def status_of(p_no: Optional[float]) -> Tuple[str, str]:
    """由失王概率给出（状态文字, 色调）——阈值与前端一致。"""
    if p_no is None:
        return "等待模型", "neutral"
    if p_no < 0.2:
        return "正常", "ok"
    if p_no < 0.4:
        return "轻微波动", "ok"
    if p_no < 0.6:
        return "明显波动", "warn"
    if p_no < 0.8:
        return "显著波动", "warn"
    return "失王", "danger"
