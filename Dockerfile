FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    OCR_PROVIDER=auto

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY config ./config
COPY data ./data
COPY frontend ./frontend

RUN mkdir -p /app/outputs/api_runs

EXPOSE 8770

CMD ["python", "-m", "uvicorn", "ai_design_review.api:app", "--host", "0.0.0.0", "--port", "8770"]
