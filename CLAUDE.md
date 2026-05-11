# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目本质

豆包输入法 ASR 的**逆向协议客户端**——不是官方 API。任何"应该这么调"的猜测必须以实际抓包/源码为准，服务端协议变了就坏。当前主要风险点：
- 单 device 并发只能跑 2–4 路稳定，8+ 路开始 1008/1011 断连，所以禁止当生产 ASR 用
- credentials.json 丢失 = 重新注册虚拟设备，频繁注册同 IP 会触发风控；首次跑出来后**必须备份**

## 常用命令

```bash
# ── 本地开发 ──
pip install -e .                        # 库本身
pip install -e .[examples]              # 例子用的 sounddevice/numpy
pip install -e .[dev]                   # grpc_tools + pytest（改 proto 时才需要）

python examples/file_transcribe.py      # 拉一段 GitHub 上的中文 wav 跑一遍
python examples/mic_realtime.py         # 实时麦克风
python examples/concurrency_test.py --n 4   # 风控/限流拐点实测
python examples/ner.py                  # NER（命名实体识别）链路

# ── Protobuf 重新生成（改 asr.proto 之后） ──
bash gen_proto.sh                       # 产 asr_pb2.py + asr_pb2.pyi
# asr_pb2.* 是生成产物，不要手动改

# ── 本地 Docker（开发） ──
docker compose build
docker compose run --rm doubao-asr python examples/file_transcribe.py
# 走代理：-e HTTPS_PROXY=http://host.docker.internal:7890

# ── NAS 部署（生产个人用） ──
bash deploy-local.sh                    # 完整：build → push → scp compose → ssh NAS pull/up
bash deploy-local.sh --skip-build       # 源码无改动跳过 build，仍同步 compose 重启
bash deploy-local.sh --build-proxy http://127.0.0.1:7890   # build 时加 pip 代理

# 在 NAS 上 exec 进容器跑（容器命令是 sleep infinity）
ssh $NAS_USER@$NAS_HOST 'sudo docker exec -w /app doubao-asr python examples/file_transcribe.py'
```

系统依赖：`libopus0`（音频编解码）、`ffmpeg`（音频解码非 PCM 输入）。Dockerfile 已经 apt 装好。

## 架构（big picture）

入口三件套（都是 async，定义在 `doubaoime_asr/asr.py`）：

| 函数 | 用途 |
|------|------|
| `transcribe(audio, config=…)` | 非流式，吃文件路径或 PCM bytes，直接返回最终文本 |
| `transcribe_stream(audio, …)` | 流式，`AsyncIterator[ASRResponse]`，能拿到中间结果/VAD/会话事件 |
| `transcribe_realtime(audio_source, …)` | 实时，吃 `AsyncIterator[bytes]` 边采边送 |

下面的协议栈是**两套独立链路**，搞清楚不要混：

```
ASR 链路（语音识别主体）              NER 链路（命名实体识别，可选）
────────────────────────              ──────────────────────────────────
1. register_device()  ─HTTP─►        1. WaveClient.handshake()  ─HTTPS─►
   返回 device_id/cdid                    POST keyhub.zijieapi.com/handshake
                                          ECDH(P-256) + ECDSA-SHA256 签名
2. get_asr_token()    ─HTTP─►             派生 ChaCha20 对称密钥
   返回 ASR token                          会话缓存到 credentials.json
                                       
3. WebSocket          ─WSS───►        2. ner() 通过 WaveClient 发请求
   wss://frontier-audio-ime-ws            payload 用 ChaCha20 流加密
   .doubao.com/ocean/api/v1/ws
   protobuf 帧（asr.proto）
   PCM→Opus per 20ms 帧
   (audio.py 编码 + asr.py 收发)
```

`ASRConfig.ensure_credentials()` 是凭据生命周期的入口，惰性触发：
1. 直传 `device_id`/`token` → 用之
2. `credential_path` 文件存在且可读 → 用文件
3. 都没有 → 自动 `register_device()` + `get_asr_token()`，写回文件（如果 `credential_path` 给了）

`credentials.json` 不只是 device_id/token，还缓存 `wave_session`（NER 用的 ChaCha20 派生会话）和 `sami_token`（JWT，过期前自动续）。**改这块要保证向后兼容已有缓存文件**。

### 模块职责

| 文件 | 职责 |
|------|------|
| `asr.py` | top-level `transcribe*` + `DoubaoASR` WebSocket 收发循环 + 所有响应 dataclass |
| `config.py` | `ASRConfig`（凭据生命周期 + 代理 + 会话参数）、`SessionConfig`（服务端会话初始化 payload schema） |
| `device.py` | HTTP 设备注册 + ASR token 换取 |
| `sami.py` | SAMI token（NER 用，JWT 过期检测在 config.py 的 `_jwt_is_expired`） |
| `wave_client.py` | ECDH P-256 / HKDF-SHA256 / ChaCha20 / ECDSA-SHA256 加密层；`WaveSession` 可序列化进缓存 |
| `ner.py` | 在 WaveClient 上的 NER 请求/响应封装 |
| `audio.py` | PCM → Opus 帧编码器（20ms 帧） |
| `constants.py` | `WEBSOCKET_URL`、`AID=401734`、`USER_AGENT`、`DEFAULT_DEVICE_CONFIG`（虚拟设备伪造参数） |
| `asr.proto` / `asr_pb2.py` / `asr_pb2.pyi` | protobuf 定义；改 `.proto` 后必须 `bash gen_proto.sh` 重生 |

协议细节参考 `wave_protocol.md`（Wave 握手抓包分析）。

## 代理（HTTP / WS 分两路）

- **HTTP 部分**（设备注册、token、Wave 握手）走 `requests`，自动读环境变量 `HTTPS_PROXY` / `HTTP_PROXY`
- **WebSocket 部分**走 `websockets>=13.1`，要么传 `ASRConfig.proxy="http://..."`，要么靠环境变量 `HTTPS_PROXY` / `WSS_PROXY`
- websockets 库版本必须 ≥13.1（这是 `proxy=` 关键字参数引入的版本），改 `pyproject.toml` 时别降回去

## NAS 部署机制

构建只在开发机，NAS 拉镜像 + git 同步源码 + 启动。NAS 上有完整源码是为了能 ssh 进去手动看 / 跑代码。

| 文件 | 角色 |
|------|------|
| `docker-compose.yml` | 本地开发 |
| `docker-compose.prod.yml` | NAS 生产，`command: ["sleep", "infinity"]`——把它当库容器，exec 进去跑（compose 文件由 git pull 同步） |
| `Dockerfile` | python:3.11-slim + libopus0 + ffmpeg + `pip install -e .` |
| `.env`（gitignored） | 本地：`REGISTRY` / `NAS_USER` / `NAS_HOST` / `NAS_DIR`；NAS：脚本写入 `REGISTRY` + `IMAGE_TAG` 供 compose 插值 |
| `.env.example` | 模板 |
| `.deploy-state` | 缓存上次 build 的 commit hash，对比 `doubaoime_asr/ examples/ samples/ Dockerfile pyproject.toml` 决定是否跳 build |
| `deploy-local.sh` | 编排：判断是否 build → push 镜像 → ssh NAS 单条 sudo 命令完成 `git fetch + reset --hard origin/main` + 写 .env + mkdir data + `docker compose pull && up` |

**Synology / NAS 几个非显然的坑（已处理在 deploy-local.sh）**：
- sshd 非交互 shell 不加载 `/etc/profile`，docker/git 不在 PATH → ssh 命令里显式 `export PATH=/usr/local/bin:/usr/bin:/bin:$PATH`
- 非 root 用户没有 docker.sock 权限 → 整段套 `sudo sh -c '...'`
- sudo 跨用户访问 git 仓库会报 "dubious ownership" → `git config --global --add safe.directory $NAS_DIR`
- compose volume 宿主端目录 `./data` docker 不会自动建 → 脚本 `mkdir -p data`
- 首次准备：NAS 上手动 `git clone` 仓库到 `$NAS_DIR`，配好 github 凭据（SSH key 或 PAT），之后脚本每次自动 `git fetch + reset --hard`

凭据 `credentials.json` 落在 NAS 的 `$NAS_DIR/data/`（compose volume 映射），**首次跑出来后请备份**。

## 行尾约定

`.gitattributes` 强制 `.sh`/`.yml`/`.yaml`/`Dockerfile`/`.env.example` 用 LF——Windows 默认 `core.autocrlf=true` 会把 LF 转 CRLF，部署到 Linux NAS 后 bash 直接 `'\r': command not found` 死。改 shell/yaml/Dockerfile 后如果之前没生效，需要 `sed -i 's/\r$//' deploy-local.sh` 修正工作树。

## 易踩的坑

- **`transcribe(bytes)` 把字节当 raw PCM**（不是 wav 文件字节）。`audio.py:46` 的 `convert_audio_to_pcm` 只在传 `str/Path` 时才调 `miniaudio.decode_file` 解 wav header / 重采样。直接 `transcribe(open("x.wav","rb").read())` → wav header + 原采样率被当 16k PCM 喂给 Opus → 服务端返 `InternalError`。要么传 `Path`，要么自己 PCM-ify
- **wave_client.py 需要 `cryptography`**（ECDH/HKDF/ChaCha20/ECDSA），干净 venv 缺这个 `import doubaoime_asr` 就崩；pyproject.toml 已列，别误删
- **websockets 必须 ≥13.1**（`proxy=` 关键字参数从这版起支持）
- **Synology / NAS sudo + PATH**：sshd 非交互 shell 不加载 `/etc/profile`，docker/git 不在 PATH；非 root 没 docker.sock 权限；sudo 跨用户访问 git repo 报 dubious ownership——deploy-local.sh 已经处理这三个，删之前先想清楚

## 改动 checklist

- 改 `.proto` → 必须 `bash gen_proto.sh` 重生 pb2 文件
- 改 `pyproject.toml` 的 `websockets` 版本下限 → 必须 ≥13.1
- 改 `ASRConfig` 默认值 / `credentials.json` schema → 注意已有缓存文件的兼容
- 改 `deploy-local.sh` 的 ssh 远程命令 → 记得 sudo + PATH 两个套法都要保留
- 改 shell/Dockerfile/yaml → 确认是 LF（git status 看 `.gitattributes` 是否生效）
