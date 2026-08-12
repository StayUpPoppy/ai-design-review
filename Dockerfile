FROM python:3.11-slim

ARG DEBIAN_APT_MIRROR=mirrors.aliyun.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    OCR_PROVIDER=auto

RUN if [ -n "$DEBIAN_APT_MIRROR" ]; then \
      sed -i "s|deb.debian.org|${DEBIAN_APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends poppler-utils libgomp1 libgl1 libglib2.0-0 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" --upgrade pip \
    && python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY src ./src
COPY config ./config
COPY data ./data
COPY frontend ./frontend
COPY alembic.ini ./
COPY migrations ./migrations

RUN mkdir -p /app/outputs/api_runs

EXPOSE 8770

CMD ["python", "-m", "uvicorn", "ai_design_review.api:app", "--host", "0.0.0.0", "--port", "8770"]
