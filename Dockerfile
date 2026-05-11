FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libopus0 \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY doubaoime_asr ./doubaoime_asr
COPY examples ./examples
COPY samples ./samples

RUN pip install --no-cache-dir -e .

VOLUME ["/data"]

ENV PYTHONUNBUFFERED=1 \
    DOUBAO_CREDENTIAL_PATH=/data/credentials.json

CMD ["python", "-c", "import asyncio; from doubaoime_asr import transcribe, ASRConfig; import os; \
print('doubaoime-asr ready. Override CMD to run your own script.'); \
print('Credential path:', os.environ.get('DOUBAO_CREDENTIAL_PATH')); \
print('HTTPS_PROXY:', os.environ.get('HTTPS_PROXY','(none)'));"]
