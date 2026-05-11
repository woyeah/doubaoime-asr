"""
并发实测脚本

用同一个 device_id（共用 credentials.json）同时开 N 路 ASR 任务，
观察成功率、尾延迟、错误类型，定位风控/限流拐点。

用法：
    python examples/concurrency_test.py --n 4 --audio ./test.wav
    # 或拉一段公开样本
    python examples/concurrency_test.py --n 4

参考策略（每档跑 3 次取中位数）：
    n=1, 2, 4, 8, 16
错误类型解读：
    - websockets.ConnectionClosed 1008 / 1011  → 服务端主动断（风控嫌疑）
    - asyncio.TimeoutError                       → 限流排队超时
    - ASRError 含 "token"/"auth"                 → 设备凭据被回收
"""
import argparse
import asyncio
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import requests

from doubaoime_asr import transcribe, ASRConfig
from doubaoime_asr.asr import ASRError


SAMPLE_AUDIO_URL = (
    "https://github.com/liangstein/Chinese-speech-to-text/raw/refs/heads/master/1.wav"
)
LOCAL_SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "test.wav"


def load_audio_path(path: Optional[str]) -> Path:
    """
    返回音频文件 Path（不读字节）。

    transcribe 看到 bytes 入参会把字节当 raw PCM 用，wav header + 原采样率
    被当 16k PCM 喂给 Opus → 服务端 InternalError。必须传 Path 走
    miniaudio.decode_file 解码。
    """
    if path and Path(path).exists():
        return Path(path)
    if LOCAL_SAMPLE.exists():
        print(f"使用 repo 内样本 {LOCAL_SAMPLE} …", flush=True)
        return LOCAL_SAMPLE
    print(f"未指定 --audio 且 repo 内无 samples/test.wav，从 GitHub 拉公开样本…", flush=True)
    tmp = Path(tempfile.gettempdir()) / "doubaoime_asr_sample.wav"
    tmp.write_bytes(requests.get(SAMPLE_AUDIO_URL, timeout=30).content)
    return tmp


async def one_call(idx: int, audio: Path, cfg: ASRConfig) -> dict:
    t0 = time.monotonic()
    try:
        text = await transcribe(audio, config=cfg)
        return {
            "idx": idx,
            "status": "ok",
            "elapsed": time.monotonic() - t0,
            "chars": len(text),
            "text_head": text[:30],
            "error": None,
        }
    except ASRError as e:
        return {
            "idx": idx,
            "status": "asr_error",
            "elapsed": time.monotonic() - t0,
            "chars": 0,
            "text_head": "",
            "error": f"{type(e).__name__}: {e}",
        }
    except Exception as e:
        return {
            "idx": idx,
            "status": "other_error",
            "elapsed": time.monotonic() - t0,
            "chars": 0,
            "text_head": "",
            "error": f"{type(e).__name__}: {e}",
        }


async def run(n: int, audio: Path, credential_path: str, proxy: Optional[str]) -> None:
    cfg = ASRConfig(credential_path=credential_path, proxy=proxy)
    # 预热：确保 device_id / token 已经就绪，避免并发时 N 个任务全去注册
    cfg.ensure_credentials()
    print(f"device_id={cfg.device_id}  proxy={proxy or '(env or none)'}", flush=True)

    print(f"\n>>> launching {n} concurrent transcribe() ...", flush=True)
    wall_t0 = time.monotonic()
    results = await asyncio.gather(*[one_call(i, audio, cfg) for i in range(n)])
    wall = time.monotonic() - wall_t0

    ok = [r for r in results if r["status"] == "ok"]
    fail = [r for r in results if r["status"] != "ok"]

    print(f"\n=== summary (N={n}) ===")
    print(f"wall time      : {wall:.2f}s")
    print(f"success        : {len(ok)}/{n}")
    print(f"failure        : {len(fail)}/{n}")
    if ok:
        elapsed = sorted(r["elapsed"] for r in ok)
        print(f"latency p50    : {statistics.median(elapsed):.2f}s")
        print(f"latency max    : {elapsed[-1]:.2f}s")
    if fail:
        print(f"\nfailures:")
        for r in fail:
            print(f"  [{r['idx']:02d}] {r['status']:12s} {r['elapsed']:.2f}s  {r['error']}")

    print(f"\nper-task detail:")
    for r in sorted(results, key=lambda x: x["idx"]):
        tag = "OK" if r["status"] == "ok" else "FAIL"
        print(
            f"  [{r['idx']:02d}] {tag:4s} {r['elapsed']:6.2f}s "
            f"chars={r['chars']:3d}  head={r['text_head']!r}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=4, help="concurrency level")
    parser.add_argument("--audio", type=str, default=None, help="local wav/mp3 path")
    parser.add_argument(
        "--credential",
        type=str,
        default="./credentials.json",
        help="credential cache path",
    )
    parser.add_argument(
        "--proxy", type=str, default=None, help="override HTTPS_PROXY for websocket"
    )
    args = parser.parse_args()

    audio = load_audio_path(args.audio)
    print(f"audio path: {audio} ({audio.stat().st_size} bytes)")

    try:
        asyncio.run(run(args.n, audio, args.credential, args.proxy))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
