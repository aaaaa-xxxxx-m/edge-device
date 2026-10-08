"""智能蜂箱 · 边缘设备系统（bee_edge）。

模块：
- config   配置加载
- state    本地状态读写（原子）
- sensors  DHT22 温湿度
- audio    录音(WAV) 与解码
- features 60 维特征提取（与云端一致）
- inference 本地 SVM 推理
- model_store 模型下载校验与原子替换
- server  云端接口客户端
- app      采集主循环
- display  HDMI 屏渲染（pygame）
"""

__version__ = "0.1.0"
