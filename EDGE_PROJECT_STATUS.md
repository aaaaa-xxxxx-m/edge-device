# 边缘设备系统 · 项目进程记录（EDGE PROJECT STATUS）

> 记录「智能蜂箱」边缘设备系统（树莓派侧）的设计决策与实施进度。
> 关联：云端项目见 `云服务器 PROJECT_STATUS.md`；硬件见同目录 `DEVICE_STATUS.md`。

最近更新：2026-10-08（设计定稿，编码未开始）

---

## 一、目标

为**树莓派边缘设备**构建一套采集 + 本地推理 + 上传 + 本地状态显示的边缘系统：

- 采集蜂箱 **温湿度** 与 **音频**，本地提取 **60 维特征**、本地 **SVM 推理失王概率**；
- 经 **预签名直传 MinIO** 上传音频/特征，向新云端 `POST /api/v1/devices/inference` 上报推理与指标；
- 按需**协助云端训练**（采集正样本），并**自动拉取/校验/替换**新模型；
- 用**接在树莓派上的 HDMI 屏**在实地离线显示蜂箱情况。

---

## 二、硬件现状（见 `DEVICE_STATUS.md`）

| 部件 | 型号 | 接口 |
|------|------|------|
| 边缘计算单元 | 树莓派 **Zero WH**（ARM1176JZF-S 1GHz / 512MB / armv6） | — |
| 温湿度 | DHT22（±0.5℃ / ±2%RH） | 单总线 GPIO（默认 BCM 11） |
| 声音 | SA_WS10 有线 USB 麦克风（70Hz–10kHz） | USB 2.0 |
| 存储 | SanDisk Ultra 32GB Class10 SD | — |
| 显示 | **HDMI 显示屏**（能否触摸未知） | mini-HDMI |

> ⚠️ 资源约束：1 核 / 512MB / armv6 → **不跑浏览器/桌面**；推理与渲染都要轻量。

---

## 三、关键设计决策（已确认）

1. **特征规格**：**16kHz、去环境维 → 60 维** `[MFCC40, 对比度7, STFT-mel-DCT12, ZCR1]`，与云端 `app/services/feature_extract.py` **逐位一致**
   （旧 `sys.py` 为 48kHz、62 维含温湿度 2 维 → **需改**）。
2. **推理位置**：边缘**本地**做（`joblib` 加载 `svm.pkl`+`scaler.pkl`，`p_no_queen = predict_proba[:,1]`）。
3. **运行模式**：
   - **正常 90s/轮**（保证在线；前端离线阈值 5 分钟，90s 安全）；
   - **采集 30s/轮**：轮询到本设备有 `waiting/pending/running` 训练任务时切换，约 **5h** 凑满 600 条正样本，结束后回 90s。
   - 每轮都上传：**音频 + 特征 + 推理**。
4. **模型获取**：新增**设备端模型清单接口**，设备比对版本后下载。
5. **模型校验**：**Ed25519 签名校验**（云端已有 `/models/public-key`），验签通过才原子替换。
6. **部署形态**：**venv + systemd**（两个服务），**开机进控制台（无桌面）**。
7. **显示**：**纯本地、断网可用**（内容全部本地可算），pygame + SDL2 `kmsdrm` 全屏 HDMI，**中文**，设备名 + 温湿度 + 失王概率 + 状态 + 更新时间。
8. **不采用**：树莓派跑浏览器 kiosk（太重）；显示依赖服务器出图（破坏离线可用）。

---

## 四、与云端对接

### 已存在（设备鉴权 `X-API-Key`）
- `GET /api/v1/devices/me/presigned-url?kind=audio|feature&filename=&content_type=` → 预签名 **PUT**（**本次新增**，按密钥自识身份，无需设备 id）
- `GET /api/v1/devices/{id}/presigned-url`（旧，按数字 id）→ 预签名 **PUT**
- `GET /api/v1/devices/{id}/download-url/{object_key}` → 预签名 **GET**
- `POST /api/v1/devices/inference` → 上报推理+环境指标（并置设备在线）

### 需新增（本阶段后端小改，改服务器容器 + 回写仓库）
- `GET /api/v1/devices/{name}/model`（X-API-Key）→
  `{has_model, version, sha256, signature(b64), model_url, scaler_url, updated_at}`
- `GET /api/v1/devices/{name}/model-status`（X-API-Key）→
  `{status, feature_count, required, has_active}`
- 复用 `ModelVersion`（取 `minio_object_key == models/<name>/svm.pkl` 最新）+ MinIO 预签名；**无 DB 迁移**。

### 签名口径（与云端一致）
- 训练侧：`signature = Ed25519_sign( sha256(svm_bytes).hex() + sha256(scaler_bytes).hex() )`，Base64 存储于 `model_versions.signature`。
- 设备侧：下载 svm/scaler → 各自 sha256 → 拼接待验数据 → 用 `GET /models/public-key` 的 PEM 公钥验签。

---

## 五、系统设计

### 进程/服务
```
bee-edge.service     主循环：采集→特征→本地推理→上传→(按需)切换采集频率；每轮原子写 state.json
bee-display.service  显示：读 state.json → pygame 全屏渲染；每 5s 刷新(文件变化即重绘)
```
解耦：采集崩溃时屏幕仍显示最后状态（更新时间变旧 = 异常提示）。

### 主循环流程
1. 读 DHT22（失败则温湿度为空）
2. `arecord` 录 **6s / 16kHz / 单声道 / 16bit WAV**
3. 计算 **60 维特征**
4. 本地 SVM 推理 → `p_no_queen / p_normal / label / confidence`（无模型则跳过）
5. 预签名上传音频(`kind=audio`) → `audio_object_key`
6. 预签名上传特征(`kind=feature`) → `feature_object_key`
7. `POST /api/v1/devices/inference`（含音频键/特征键/模型版本/概率/label/置信度/耗时/温湿度）
8. 原子写 `state.json`
9. 周期查 `model-status`：有训练任务 → 本轮后用 30s；查 `model`：版本/sha 变化 → 下载校验替换
10. 休眠到下一周期（90s / 30s）

### 显示（离线优先）
- 渲染：pygame + SDL2 `kmsdrm`，无 X、全屏；**自适应 HDMI 原生分辨率，上限 1080p**，字号按屏高比例；中文需 CJK 字体。
- 内容：
  - **设备名**（顶部大号）
  - **温度 ℃ / 湿度 %** 与 **失王概率 %**（超大 + 颜色条）
  - **状态文字**（阈值与前端一致：<20% 正常 / <40% 轻微波动 / <60% 明显波动 / <80% 显著波动 / ≥80% 失王）
  - **更新时间**（相对“x 分钟前” + 绝对时间；超期变黄/红）
- `state.json`：`{device_name, temperature, humidity, probability_no_queen, status, model_version, updated_at}`

### 可靠性
- 网络失败指数退避重试；单周期失败不中断；
- 401（密钥失效）/403（已注销）→ 降级告警、定期重试，不崩溃；
- 无模型时先拉取，拉不到则“采集/上传、跳过推理”；
- 模型原子替换（临时文件 + rename）+ 验签；
- 建议 NTP 对时（非强依赖）。

---

## 六、项目结构（`edge-device/`，待建）

```
edge-device/
├── bee_edge/
│   ├── config.py        # TOML 配置 + 校验
│   ├── state.py         # 状态读写(原子)
│   ├── sensors.py       # DHT22
│   ├── audio.py         # arecord 16k/mono/6s WAV
│   ├── features.py      # 60 维(与服务器一致)
│   ├── inference.py     # 本地 SVM 推理
│   ├── model_store.py   # 加载/版本/sha/Ed25519验签/原子替换
│   ├── server.py        # 预签名上传·推理上报·模型清单/状态·退避重试
│   ├── setup.py         # 命令行配置向导
│   ├── websetup.py      # 本地网页配置(手机填写)
│   ├── netinfo.py       # 主机名/本机 IP
│   ├── showip.py        # 全屏显示本机 IP
│   ├── app.py           # 主循环 + 模式切换
│   └── display.py       # pygame 全屏渲染(读 state，含主机名·IP)
├── main.py              # 入口(--mode edge|display)
├── config.example.toml
├── requirements.txt
├── install.sh           # venv + 依赖 + 字体 + systemd 安装
├── bee-edge.service
├── bee-display.service
└── README.md
```

### 配置项（`config.toml`）
`device_name`、`api_key`、`server_base_url`（如 `http://8.156.79.6`）、`normal_interval_s=90`、`collect_interval_s=30`、`sample_rate=16000`、`audio_seconds=6`、`dht_pin=11`、`alsa_device`、`model_dir`、`state_file`、`display_width/height`(可选,默认自适应)、`font_path`、`log_level`。

---

## 七、部署

- Raspberry Pi OS：`python3-venv` + venv；依赖 `numpy scipy scikit-learn joblib python-speech-features requests cryptography`（apt/piwheels）+ `Adafruit_DHT` + `alsa-utils`(arecord) + `python3-pygame` + CJK 字体（`fonts-noto-cjk`/`wqy-zenhei`）。
- `raspi-config` → **Console Autologin（无桌面）**；`SDL_VIDEODRIVER=kmsdrm`。
- `bee-edge.service`、`bee-display.service`：`Restart=always`、开机自启；display 无 HDMI 时重试不崩溃。
- 首次接入：管理端**注册设备** → 复制 **API Key** 写入 `config.toml`；待用户触发一次「更新检测模型」→ 采集 → 出首个模型 → 正常推理。
- 流量/存储参考：正常 90s ≈ **182MB/天**音频；采集一轮额外 ≈ **114MB**。

---

## 八、进度与待办

| 项 | 状态 |
|----|------|
| 需求/接口/特征规格梳理（对照新云端 + 旧 `sys.py`） | ✅ 完成 |
| 设计定稿（模式/采集/模型/校验/显示/部署） | ✅ 完成 |
| **云端新增接口**：`/devices/{name}/model`、`/devices/{name}/model-status`、`/devices/me/presigned-url` | ✅ 已部署并推送（`a7968f47`、`1ebb0b8b`） |
| 边缘系统代码（`bee_edge/*`、入口、配置、systemd、README） | ✅ 完成（本地） |
| 显示服务（pygame 中文全屏 + state.json） | ✅ 完成（本地） |
| 本地离线自测（特征=60 维、上传/验签、state→渲染） | ✅ 通过（`tests/test_offline.py`） |
| 边缘端 Git 仓库（`edge-device`，私有）+ README | ✅ 已完成并推送（`github.com/aaaaa-xxxxx-m/edge-device`） |
| 上机联调（树莓派 + DHT22 + 麦克风 + HDMI 屏） | 🟡 进行中：采集+上传已跑通；待接 DHT/HDMI、触发训练 |
| 将「部署/使用/介绍」文档同步到文档存档目录 | ⬜ 待做 |

### 已完成实现（2026-10-08）
- **云端**（`app/api/v1/devices.py`）：`GET /{name}/model`、`GET /{name}/model-status`、`GET /me/presigned-url`（均 X-API-Key）；已部署服务器容器 + 回写仓库。
- **边缘端**（`edge-device/`）：`bee_edge/`（config/state/sensors/audio/features/inference/model_store/server/setup/websetup/netinfo/showip/app/display）、`main.py`、`config.example.toml`、`requirements.txt`、`install.sh`、`bee-edge.service`、`bee-display.service`、`README.md`、`tests/test_offline.py`。
- **设备密钥配置**：① 命令行向导 `main.py --mode setup`（可 `--key-file device_key.txt`）；② **本地网页配置** `main.py --mode websetup`（树莓派开小页面，手机浏览器填设备名+key，联网校验后写入，可选 `--setup-token` 口令；实测 GET/POST 通过）。也可直接编辑 `config.toml` 或用环境变量 `BEE_API_KEY`。
- **本机 IP 展示**：`main.py --mode showip` 全屏显示主机名+IP+手机访问地址（无需 config）；正常状态屏左上角亦显示 `主机名 · IP`；`websetup` 启动时控制台打印可访问地址（`bee_edge/netinfo.py`）。
- **离线自测通过**：60 维特征 `(60,)`；状态分级；state 原子读写；模型 sha256+Ed25519 验签与原子安装（拒绝坏签名）。

### 实机部署联调（2026-10-08/09，Raspberry Pi Zero WH）
- **设备**：主机 `beehive` / `192.168.82.165`（WiFi）；Raspbian 13 (trixie) armv6l；Python 3.13。默认启动已改 **multi-user.target（控制台）**（供 pygame kmsdrm）。
- **访问**：SSH 已开；已注入本机公钥（免密登录）。密码被 cloud-init（重跑）改为 `BeeHive2026`（可自行 `passwd` 改回）；`sudo` 免密。
- **安装**：代码 → `/opt/bee-edge`；venv `--system-site-packages`；apt 装 `python3-numpy/scipy/sklearn/joblib/requests/cryptography/pygame`、`gcc`、`fonts-wqy-zenhei`；pip 装 `python-speech-features` 与 `Adafruit_DHT`（**从源码重编译**，修复 piwheels wheel 缺失 `Raspberry_Pi_2_Driver` 的问题）；apt 源改**清华 TUNA**（原镜像 18kB/s）。
- **配置**：`/opt/bee-edge/config.toml`（`device_name=hive001` + 真实 key；`alsa_device=plughw:1,0` 对应 USB 麦克风 card1）。
- **服务**：`bee-edge`、`bee-display` 均已安装并 **enable**；`bee-edge` 运行正常（一轮 ≈19–20s CPU + 休眠 90s；启动导入 scipy/sklearn ≈25s 一次性）。
- **验证**：采集→特征→预签名上传音频+特征成功（服务器 hive001 占用 `audio 10→12`、`features 0→2`）；无模型时状态「等待模型」。同时修复云端 `GET /models/public-key` 被 `/{version}` 遮蔽的 404（提交 `0ccfe5e7`）。
- **修复 / 进展（2026-10-09）**：
  - 显示：`bee-display` 曾因**缺少 `pygame.font.init()`** 崩溃重启（屏幕停在控制台登录提示）；修复后稳定运行于 HDMI **1280×800**（顶部设备名、左上角 `主机名·IP`）。
  - 模型：以桌面 `queenbee`（600 正样本）**模拟训练**出 `v20261008175642`；设备开机后**已自动拉取 → Ed25519 验签 → 原子替换**，并开始推理上报（state：`概率 0.73 / 显著波动 / model_version v20261008175642 / synced=true`）。
  - DHT22：已接在 **BCM17**（wiringPi 0 / 物理 11），读数正常（≈23.5℃ / 58%）；`dht_pin=17`。读取已容错。
  - 备注：设备端 scikit-learn 为 1.4.2（apt），云端训练为 1.3.2 → 反序列化时提示 `InconsistentVersionWarning`；SVM/Scaler 可正常 unpickle 与推理，暂可接受（如需消除，需统一两端 sklearn 版本后重训）。
  - 排查噪音：开机时的 “completed socket interaction for boot stage config/final” 属 cloud-init/systemd 正常输出，非故障。

### 实现顺序
1. 云端两接口 → 部署服务器 + 回写仓库；
2. `edge-device/` 全套代码 + 配置 + 双 systemd + README；
3. 本地离线自测 → 上机联调。

---

## 九、参考文件

- 边缘端仓库：**https://github.com/aaaaa-xxxxx-m/edge-device**（私有，`main`）
- 旧边缘程序：`C:\Users\xx\OneDrive\Desktop\sys.py`（48kHz/62 维/旧 `api1` 接口，仅作参考）
- 硬件说明：`edge-device/DEVICE_STATUS.md`
- 云端特征实现（对齐基准）：`...\ai-lab\hive_system\code\github_mirror\app\services\feature_extract.py`
- 云端设备接口：`...\app\api\v1\devices.py`
- 云端项目进程：`云服务器 PROJECT_STATUS.md`
