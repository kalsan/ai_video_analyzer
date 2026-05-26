# syntax=docker/dockerfile:1
FROM python:3.12-slim

RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y ffmpeg curl ca-certificates nodejs && \
    rm -rf /var/lib/apt/lists /var/cache/apt/archives

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -U yt-dlp yt-dlp-ejs

COPY app ./app
COPY config ./config

RUN groupadd --system --gid 1000 runner && \
    useradd runner --uid 1000 --gid 1000 --create-home --shell /bin/bash && \
    mkdir -p /work /data && \
    chown runner:runner /work /data
USER 1000:1000

ENV DB_PATH=/data/jobs.db \
    WORK_DIR=/work \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
