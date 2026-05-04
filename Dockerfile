FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    HF_HOME=/root/.cache/huggingface \
    MODELSCOPE_CACHE=/root/.cache/modelscope \
    TIKTOKEN_CACHE_DIR=/app/tiktoken_cache

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxrender1 \
        libxext6 \
        libgomp1 \
        libreoffice \
        libreoffice-l10n-ko \
        fonts-noto-cjk \
        fonts-noto-cjk-extra \
        curl \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml setup.py MANIFEST.in README.md requirements.txt ./
COPY raganything ./raganything

RUN uv pip install --system -e .[all] \
        python-dotenv \
        openai \
        PyJWT \
        passlib \
        bcrypt \
        docling

COPY examples ./examples
COPY scripts ./scripts
COPY docs ./docs

RUN mkdir -p /app/inputs /app/rag_storage /app/output \
        /root/.cache/huggingface /root/.cache/modelscope

EXPOSE 9621

# 기본 동작: lightrag-server 웹 UI (포트 9621)
# 일회성 예제는 `podman compose run --rm raganything python examples/...` 로 실행
CMD ["lightrag-server", "--host", "0.0.0.0", "--port", "9621", \
     "--working-dir", "/app/rag_storage", \
     "--input-dir", "/app/inputs"]
