# doubaoime-asr

豆包输入法语音识别 Python 客户端。

## 免责声明

本项目通过对安卓豆包输入法客户端通信协议分析并参考客户端代码实现，**非官方提供的 API**。

- 本项目仅供学习和研究目的
- 不保证未来的可用性和稳定性
- 服务端协议可能随时变更导致功能失效

## 安装

```bash
# 从本地安装
git clone https://github.com/starccy/doubaoime-asr.git
cd doubaoime-asr
pip install -e .

# 或从 Git 仓库安装
pip install git+https://github.com/starccy/doubaoime-asr.git
```

### 系统依赖

本项目依赖 Opus 音频编解码库，需要先安装系统库：

```bash
# Debian/Ubuntu
sudo apt install libopus0

# Arch Linux
sudo pacman -S opus

# macOS
brew install opus
```

## 快速开始

### 基本用法

```python
import asyncio
from doubaoime_asr import transcribe, ASRConfig

async def main():
    # 配置（首次运行会自动注册设备，并将凭据保存到指定文件）
    config = ASRConfig(credential_path="./credentials.json")

    # 识别音频文件
    result = await transcribe("audio.wav", config=config)
    print(f"识别结果: {result}")

asyncio.run(main())
```

### 流式识别

如果需要获取中间结果或更详细的状态信息，可以使用 `transcribe_stream`：

```python
import asyncio
from doubaoime_asr import transcribe_stream, ASRConfig, ResponseType

async def main():
    config = ASRConfig(credential_path="./credentials.json")

    async for response in transcribe_stream("audio.wav", config=config):
        match response.type:
            case ResponseType.INTERIM_RESULT:
                print(f"[中间结果] {response.text}")
            case ResponseType.FINAL_RESULT:
                print(f"[最终结果] {response.text}")
            case ResponseType.ERROR:
                print(f"[错误] {response.error_msg}")

asyncio.run(main())
```

### 实时麦克风识别

实时语音识别需要配合音频采集库使用，请参考 [examples/mic_realtime.py](examples/mic_realtime.py)。

运行示例需要安装额外依赖：

```bash
pip install sounddevice numpy
# 或
pip install doubaoime-asr[examples]
```

## API 参考

### transcribe

非流式语音识别，直接返回最终结果。

```python
async def transcribe(
    audio: str | Path | bytes,
    *,
    config: ASRConfig | None = None,
    on_interim: Callable[[str], None] | None = None,
    realtime: bool = False,
) -> str
```

参数：
- `audio`: 音频文件路径或 PCM 字节数据
- `config`: ASR 配置
- `on_interim`: 中间结果回调
- `realtime`: 是否模拟实时发送（每个音频数据帧之间加入固定的发送延迟）
    - `True`: 模拟实时发送，加入固定的延迟，表现得更像正常的客户端，但会增加整体识别时间
    - `False`: 尽可能快地发送所有数据帧，整体识别时间更短（貌似也不会被风控）

### transcribe_stream

流式语音识别，返回 `ASRResponse` 异步迭代器。

```python
async def transcribe_stream(
    audio: str | Path | bytes,
    *,
    config: ASRConfig | None = None,
    realtime: bool = False,
) -> AsyncIterator[ASRResponse]
```

### transcribe_realtime

实时流式语音识别，接收 PCM 音频数据的异步迭代器。

```python
async def transcribe_realtime(
    audio_source: AsyncIterator[bytes],
    *,
    config: ASRConfig | None = None,
) -> AsyncIterator[ASRResponse]
```

### ASRConfig

配置类，支持以下主要参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `credential_path` | str | None | 凭据缓存文件路径 |
| `device_id` | str | None | 设备 ID（空则自动注册） |
| `token` | str | None | 认证 Token（空则自动获取） |
| `sample_rate` | int | 16000 | 采样率 |
| `channels` | int | 1 | 声道数 |
| `enable_punctuation` | bool | True | 是否启用标点 |

### ResponseType

响应类型枚举：

| 类型 | 说明 |
|------|------|
| `TASK_STARTED` | 任务已启动 |
| `SESSION_STARTED` | 会话已启动 |
| `VAD_START` | 检测到语音开始 |
| `INTERIM_RESULT` | 中间识别结果 |
| `FINAL_RESULT` | 最终识别结果 |
| `SESSION_FINISHED` | 会话结束 |
| `ERROR` | 错误 |

## 凭据管理

首次使用时会自动向服务器注册虚拟设备（设备参数定义在 `constants.py` 的 `DEFAULT_DEVICE_CONFIG` 中）并获取认证 Token。

推荐指定 `credential_path` 参数，凭据会自动缓存到文件，避免重复注册：

```python
config = ASRConfig(credential_path="~/.config/doubaoime-asr/credentials.json")
```

## 代理

HTTP 部分（设备注册 / token / Wave 握手）走 `requests`，自动读环境变量 `HTTPS_PROXY` / `HTTP_PROXY`。

WebSocket 部分通过 `ASRConfig.proxy` 显式传入，或留空走环境变量（依赖 `websockets>=13.1`）：

```python
config = ASRConfig(
    credential_path="./credentials.json",
    proxy="http://127.0.0.1:7890",   # 或 socks5://127.0.0.1:1080
)
```

只设环境变量也行：

```bash
export HTTPS_PROXY=http://127.0.0.1:7890
python examples/file_transcribe.py
```

## Docker

仓库自带 `Dockerfile` 和 `docker-compose.yml`，基础镜像 `python:3.11-slim`，apt 装 `libopus0`、`ffmpeg`。

```bash
# 构建镜像
docker compose build

# 跑一个示例（凭据持久化到宿主机 ./data/credentials.json）
docker compose run --rm doubao-asr python examples/file_transcribe.py

# 走宿主机代理：编辑 docker-compose.yml 取消 HTTPS_PROXY 注释，或临时传入
docker compose run --rm \
  -e HTTPS_PROXY=http://host.docker.internal:7890 \
  doubao-asr python examples/file_transcribe.py
```

凭据 `credentials.json` 在 `./data/` volume 内，**首次运行后请备份**——丢失等同于重新注册一台虚拟设备，频繁注册同 IP 容易触发风控。

## 并发测试

`examples/concurrency_test.py` 用同一 device_id 并发跑 N 路 ASR，输出成功率、p50/max 延迟、错误明细，用来定位风控/限流拐点：

```bash
# 本地（不传 --audio 默认用 repo 内 samples/test.wav，国内无代理也能跑）
python examples/concurrency_test.py --n 4

# 自带 wav
python examples/concurrency_test.py --n 4 --audio ./my.wav

# Docker
docker compose run --rm doubao-asr \
  python examples/concurrency_test.py --n 8
```

推荐序列：`n=1 → 2 → 4 → 8 → 16`，每档跑 3 次取中位数。错误信号速查：

| 错误 | 含义 |
|------|------|
| `websockets.ConnectionClosed 1008 / 1011` | 服务端主动断，疑似风控 |
| `asyncio.TimeoutError` | 排队 / 限流超时 |
| `ASRError` 含 "token" / "auth" | device 凭据被回收 |

服务端并发上限**无文档**，必须自己实测。一般经验：单 device 同时 2–4 路稳定；8+ 路开始出现拒连；多 device 池化 = 自动化滥用红线，**不建议用于生产**。

## 部署到 NAS

构建只在开发机做，NAS 只拉镜像 + 启动容器；源码经 git pull 同步到 NAS，方便 ssh 进去手动看/跑：

```
[本机] build → push → [NAS registry] ──pull──> [NAS docker]
[本机] ssh NAS: git fetch + reset --hard origin/main   # 同步源码 + compose
                 写 .env(REGISTRY,IMAGE_TAG)            # 部署期变量不入 git
                 docker compose pull && up -d
```

### 首次准备

1. 本地：`cp .env.example .env`，按你的 NAS 环境填值（`.env` 已在 `.gitignore` 不会被提交）
2. NAS：手动 `git clone` 仓库到 `.env` 里的 `NAS_DIR`（比如 `/volume1/docker/github/doubaoime-asr`），把 github 凭据（SSH key 或 PAT）配好；之后脚本每次部署会自动 `git fetch + reset --hard origin/main`

`.env` 字段：

| 字段 | 例子 | 说明 |
|------|------|------|
| `REGISTRY` | `192.168.x.x:5500` | NAS 私有 Docker registry |
| `NAS_USER` | `your_user` | NAS SSH 用户 |
| `NAS_HOST` | `192.168.x.x` | NAS IP |
| `NAS_DIR` | `/volume1/docker/github/doubaoime-asr` | NAS 上的项目目录 |

### 常用命令

```bash
# 完整部署（构建 + 推送 + 同步 compose + NAS 拉取重启）
bash deploy-local.sh

# 源码无改动时自动跳过 build，仍会同步 compose 并重启
bash deploy-local.sh --skip-build

# 走代理加速 pip
bash deploy-local.sh --build-proxy http://127.0.0.1:7890
```

脚本在 `.deploy-state` 缓存上次构建的 commit hash，比较 `doubaoime_asr/ Dockerfile pyproject.toml` 三个路径，无改动则跳过 build。

NAS 上的 `.env` 由脚本写入，包含 `REGISTRY` + `IMAGE_TAG` 两项，供 `docker-compose.prod.yml` 插值。凭据 `credentials.json` 落在 NAS 的 `$NAS_DIR/data/`，**首次跑出来后请备份**。
