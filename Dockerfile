# syntax=docker/dockerfile:1
FROM python:3.12-slim

RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y ffmpeg curl ca-certificates && \
    rm -rf /var/lib/apt/lists /var/cache/apt/archives

# yt-dlp as direct binary so runtime self-update works.
RUN curl -fsSL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
      -o /usr/local/bin/yt-dlp && \
    chmod 0755 /usr/local/bin/yt-dlp

WORKDIR /srv
COPY requirements.txt .
# openai-whisper 20240930 setup.py imports pkg_resources, which setuptools>=81 removed.
# Pre-install setuptools<81 and disable build isolation so whisper builds against it.
RUN pip install --no-cache-dir --upgrade pip "setuptools<81" wheel && \
    pip install --no-cache-dir --no-build-isolation -r requirements.txt

COPY app ./app
COPY config ./config

RUN groupadd --system --gid 1000 runner && \
    useradd runner --uid 1000 --gid 1000 --create-home --shell /bin/bash && \
    mkdir -p /work /data && \
    chown runner:runner /work /data /usr/local/bin/yt-dlp
USER 1000:1000

ENV DB_PATH=/data/jobs.db \
    WORK_DIR=/work \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
