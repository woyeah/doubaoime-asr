"""
音频文件语音识别示例

演示 transcribe 和 transcribe_stream 两个函数的用法
"""
import asyncio
import tempfile
from pathlib import Path

import requests

from doubaoime_asr import transcribe, transcribe_stream, ASRConfig, ResponseType


async def demo_transcribe(audio_path: Path, config: ASRConfig):
    """
    非流式识别 (transcribe)

    直接返回最终识别结果
    """
    print("=" * 50)
    print("非流式识别 (transcribe)")
    print("=" * 50)

    # 简单用法：直接获取结果
    result = await transcribe(audio_path, config=config)
    print(f"识别结果: {result}")
    print()

    # 带中间结果回调
    print("带中间结果回调:")

    def on_interim(text: str):
        print(f"  [中间] {text}")

    result = await transcribe(audio_path, config=config, on_interim=on_interim)
    print(f"  [最终] {result}")
    print()


async def demo_transcribe_stream(audio_path: Path, config: ASRConfig):
    """
    流式识别 (transcribe_stream)

    返回 ASRResponse 流，可以获取中间结果、VAD 事件等详细信息
    """
    print("=" * 50)
    print("流式识别 (transcribe_stream)")
    print("=" * 50)

    async for response in transcribe_stream(audio_path, config=config, realtime=False):
        match response.type:
            case ResponseType.TASK_STARTED:
                print("[系统] 任务已启动")
            case ResponseType.SESSION_STARTED:
                print("[系统] 会话已启动")
            case ResponseType.VAD_START:
                print("[VAD] 检测到语音开始")
            case ResponseType.INTERIM_RESULT:
                print(f"[中间] {response.text}")
            case ResponseType.FINAL_RESULT:
                # 获取该段文本的起止时间
                start_time = response.results[0].start_time if response.results else 'N/A'
                end_time = response.results[0].end_time if response.results else 'N/A'

                print(f"[最终] ({start_time} ~ {end_time}) {response.text}")
            case ResponseType.SESSION_FINISHED:
                print("[系统] 会话结束")
            case ResponseType.ERROR:
                print(f"[错误] {response.error_msg}")


def get_audio_path() -> Path:
    """
    优先用 repo 内 samples/test.wav（离线 / 国内 NAS 不挂代理也能跑）；
    没找到再从 Github 下载到临时文件。

    返回 Path（不是 bytes）—— 让 transcribe 自己走 miniaudio.decode_file 解码，
    避免 wav header + 原始采样率被当 raw PCM 喂给 Opus 编码器导致服务端 InternalError。
    """
    local = Path(__file__).resolve().parent.parent / "samples" / "test.wav"
    if local.exists():
        return local

    audio_url = 'https://github.com/liangstein/Chinese-speech-to-text/raw/refs/heads/master/1.wav'
    tmp = Path(tempfile.gettempdir()) / "doubaoime_asr_sample.wav"
    tmp.write_bytes(requests.get(audio_url).content)
    return tmp


async def main():
    # 配置
    config = ASRConfig(credential_path="./credentials.json")

    audio_path = get_audio_path()

    await demo_transcribe(audio_path, config)
    await demo_transcribe_stream(audio_path, config)


if __name__ == "__main__":
    asyncio.run(main())
