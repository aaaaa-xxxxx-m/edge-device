# 智能蜂箱 · 边缘设备系统（edge-device）

运行于 **树莓派 Zero WH**：采集蜂箱温湿度与音频 → 本地提取 60 维特征 → 本地 SVM 推理失王概率 →
经预签名直传 MinIO（音频/特征）并上报云端 → 自动拉取校验新模型 → HDMI 屏离线显示蜂箱情况。

## 目录

```
edge-device/
├── bee_edge/
│   ├── config.py        配置(TOML)加载
│   ├── state.py         本地状态原子读写
│   ├── sensors.py       DHT22 温湿度
│   ├── audio.py         arecord 录音 + WAV 解码
│   ├── features.py      60 维特征（与云端逐位一致）
│   ├── inference.py     本地 SVM 推理 + 状态分级
│   ├── model_store.py   模型验签(Ed25519)/原子替换/加载
│   ├── server.py        云端接口客户端（预签名/上报/清单/状态）
│   ├── setup.py         命令行配置向导（校验并写入密钥）
│   ├── websetup.py      本地网页配置（手机浏览器填写）
│   ├── netinfo.py       主机名 / 本机 IP
│   ├── showip.py        全屏显示本机 IP
│   ├── app.py           采集主循环 + 模式切换
│   └── display.py       pygame 全屏状态显示（含主机名·IP）
├── main.py              入口（--mode edge|display）
├── config.example.toml
├── requirements.txt
├── install.sh
├── bee-edge.service
├── bee-display.service
└── README.md
```

## 依赖

- 系统：`python3-venv python3-dev alsa-utils fonts-noto-cjk python3-pygame`
- Python（piwheels 优先）：`numpy scipy scikit-learn joblib python-speech-features requests cryptography`
- 硬件库：`Adafruit_DHT`（DHT22）

## 安装

```sh
# 在树莓派上，于本目录执行
sudo sh install.sh
```

或手动：

```sh
sudo mkdir -p /opt/bee-edge && sudo cp -r . /opt/bee-edge
cd /opt/bee-edge
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install Adafruit_DHT          # 或使用 apt 的 DHT 包
cp config.example.toml config.toml
```

## 首次接入 / 配置密钥（向导，推荐）

设备需要一个**云端下发的 API Key** 才能与服务器交互。密钥在**云端注册设备时生成、仅显示一次**，
因此需要在设备上把它写入配置。流程：

1. **在云端注册设备**：登录网页端（主页「新增设备」或管理端）→ 注册设备名（如 `hive001`）→
   **复制返回的 API Key**（只显示一次）。
2. **在设备上运行配置向导**（会联网校验密钥）：

   ```sh
   # 交互式（在树莓派接键盘/SSH）
   python main.py --mode setup

   # 或直接传入
   python main.py --mode setup --device-name hive001 --api-key bee_xxx --server http://8.156.79.6

   # 或从一个 key 文件读取（格式：device_name: xxx / key: bee_xxx）
   python main.py --mode setup --key-file device_key.txt
   ```

   向导会调用 `GET /devices/{name}/model-status`（X-API-Key）**校验密钥**，
   通过后写入 `config.toml`；校验失败会提示（密钥无效 / 设备不存在 / 名称不匹配）。

3. 之后按需 `arecord -l` 设置 `alsa_device`，再启动服务（见下文）。

> 也可不用向导，直接编辑 `config.toml`，或用环境变量 `BEE_API_KEY` 提供密钥。

### 手机网页配置（现场免 SSH，可选）

在树莓派上启动一个仅局域网可访问的小网页，用手机浏览器填写设备名与密钥：

```sh
python main.py --mode websetup [--host 0.0.0.0] [--port 8080] [--setup-token 123456]
```

然后手机/电脑打开 `http://<树莓派IP>:8080/`（若设了口令：`http://<ip>:8080/?t=123456`），
填「服务器地址 / 设备名 / API Key」→「保存并校验」→ 校验通过即写入 `config.toml`。

**显示本机 IP（方便手机连接）**：

```sh
python main.py --mode showip [--port 8080]
```

全屏显示「主机名 + 本机 IP + 手机访问地址」，方便现场一眼看到。此外：

- `websetup` 启动时会在控制台打印所有可访问地址；
- **正常状态屏左上角也显示 `主机名 · IP`**。

## 配置（`config.toml`）

关键项：

| 键 | 说明 |
|----|------|
| `device_name` | 设备名（需先在云端管理端注册） |
| `api_key` | 设备 API Key（注册时返回；也可用环境变量 `BEE_API_KEY`） |
| `server_base_url` | 云端地址，如 `http://8.156.79.6` |
| `normal_interval_s` | 正常周期，默认 **90**（须 < 5 分钟，否则被判离线） |
| `collect_interval_s` | 采集模式周期，默认 **30**（有训练任务时） |
| `sample_rate` | **16000**，与云端特征口径一致，勿改 |
| `audio_seconds` | 每轮录音时长，默认 6 |
| `dht_pin` / `dht_sensor` | DHT22 数据脚（BCM）/ 型号 |
| `alsa_device` | USB 麦克风（用 `arecord -l` 查得） |
| `display_width/height` | 0 = 自适应 HDMI 分辨率 |
| `font_path` | 留空自动查找 CJK 字体 |

> 首次接入：在云端管理端注册设备 → 复制 API Key → 写入 `config.toml`；
> 待用户在设备详情页触发一次「更新检测模型」→ 设备采集样本 → 云端出首个模型 → 设备自动拉取后开始推理。

## 运行

```sh
# 采集（含推理与上传）
/opt/bee-edge/.venv/bin/python main.py --config /opt/bee-edge/config.toml --mode edge

# 显示（读 state.json，全屏 HDMI）
SDL_VIDEODRIVER=kmsdrm /opt/bee-edge/.venv/bin/python main.py --config /opt/bee-edge/config.toml --mode display
```

## 开机自启（systemd）

```sh
sudo systemctl enable --now bee-edge bee-display
journalctl -u bee-edge -f          # 查看采集日志
journalctl -u bee-display -f       # 查看显示日志
```

- **建议 `raspi-config` → Boot → Console Autologin（无桌面）**，以支持 pygame 的 `kmsdrm` 直出并节省内存。
- 若显示初始化失败（无 HDMI / 驱动不符），`bee-display` 会每 5s 重试，不影响采集。
- SDL 驱动可切换：新版用 `kmsdrm`；旧版 fbdev 可试 `SDL_VIDEODRIVER=fbcon`。

## 与云端交互（设备端，`X-API-Key`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/devices/me/presigned-url?kind=audio\|feature&filename=…` | 预签名上传 |
| POST | `/api/v1/devices/inference` | 上报推理+环境指标 |
| GET | `/api/v1/devices/{name}/model` | 模型清单（含预签名下载链接） |
| GET | `/api/v1/devices/{name}/model-status` | 训练状态（切换采集模式） |
| GET | `/api/v1/models/public-key` | 模型验签公钥 |

## 数据流

1. 读 DHT22 → 录 6s/16k WAV → 60 维特征
2. 本地 SVM 推理 → 失王概率/标签/置信度
3. 预签名直传音频、特征到 MinIO → `POST /inference`
4. 写 `state.json`（供显示服务）
5. 查模型清单：版本变化 → 下载 → **sha256 + Ed25519 验签** → 原子替换 → 重载
6. 查训练状态：有任务 → 采集模式（30s），否则正常（90s）

## 故障排查

- **录音失败**：`arecord -l` 查设备号，设置 `alsa_device`（如 `plughw:1,0`）。
- **温湿度为空**：确认 DHT22 接线与 `dht_pin`；`Adafruit_DHT` 是否安装。
- **中文显示方块**：安装 `fonts-noto-cjk` 或在 `config.toml` 指定 `font_path`。
- **显示无输出**：确认已进控制台（无桌面）且用户对 `/dev/dri` 有权限；尝试 `SDL_VIDEODRIVER=fbcon`。
- **401/403**：API Key 失效或设备被删除/注销；在云端重置密钥后更新 `config.toml`。
- **一直“等待模型”**：尚无该设备的模型；需在云端触发一次训练，待模型生成后自动拉取。
