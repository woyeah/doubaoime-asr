# samples

`test.wav` 来自 https://github.com/liangstein/Chinese-speech-to-text（公开仓库的中文语音样本）。

塞 280KB 进 repo 是为了：

- 国内 NAS 在不挂代理的情况下也能跑 `examples/file_transcribe.py` / `examples/concurrency_test.py`
- 离线测试 / 容器内自检不依赖 github 可达性

需要更长 / 自己的样本时，examples 都支持 `--audio` 参数或自行替换 `samples/test.wav`。
