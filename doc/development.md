# Development

## Layout

```
ai_video_analyzer/
  Dockerfile
  docker-compose.yml
  requirements.txt
  .dockerignore
  .gitignore
  app/
    __init__.py
    main.py         # FastAPI app + lifespan wiring
    config.py       # env vars, prompt loader
    db.py           # SQLite DAO
    queue.py        # worker thread + startup recovery
    pipeline.py     # yt-dlp → ffmpeg → whisper → LLM
    llm.py          # LM Studio + Anthropic providers
  config/
    prompt.md.sample  # default/generic system prompt
    prompt.md         # your customised prompt (gitignored)
  data/
    .gitkeep        # bind-mount target for jobs.db
  doc/
    ...             # you are here
```

## Run with docker compose

```bash
docker compose up --build
```

- Binds `./data` into `/data` (jobs.db persists across restarts).
- Exposes port 8000 on the host.
- Env is loaded from `.env` (see [.env.sample](../.env.sample)). Point
  `LM_STUDIO_URL` at your own LM Studio host or switch `LLM_PROVIDER` to
  `anthropic` and set `ANTHROPIC_API_KEY`.

## Run locally without Docker

Requires ffmpeg, yt-dlp, and Python 3.12 on PATH.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DB_PATH=./data/jobs.db WORK_DIR=./tmp/work \
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`openai-whisper` pulls torch; first install is slow and ~2 GB.

## Smoke test

```bash
# submit
curl -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
# → 202 {"status":"queued","id":1}

# poll
curl 'http://localhost:8000/jobs?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DdQw4w9WgXcQ'
# → 202 {"status":"running","id":1}
# (wait minutes)
# → 200 {"status":"done","id":1,"result":"## Summary\n..."}
```

## Inspect the DB

```bash
sqlite3 data/jobs.db 'SELECT id, url, status, length(result), error FROM jobs;'
```

## Force-retry a completed job

There is no endpoint for this (by design). If you really need to:

```bash
sqlite3 data/jobs.db "DELETE FROM jobs WHERE url = '...';"
# then POST again
```

## Logs

Uvicorn logs + app logs go to stdout. Each job logs:

- `job N starting: <url>`
- `sending K/M frames to LLM`
- `job N done` or `job N failed` with full traceback.

## Known gotchas

- **yt-dlp upgrade** runs once on container startup via
  `pip install --user -U yt-dlp yt-dlp-ejs` (installs into the runner's
  user site-packages; user site wins over the image-baked version).
  Non-fatal if it fails (offline, PyPI down, etc.) — the baked version
  is used. If YouTube breaks the current version, restart the container.
- **YouTube cookies** — optional `/data/cookies.txt` (Netscape format)
  passed to yt-dlp when present. Required for age-gated / bot-challenged
  videos. See [config.md](config.md#datacookiestxt-optional) for the
  export procedure. If YouTube complains about invalid cookies, they
  were rotated during export — re-do it from a private window.
- **JS runtime for yt-dlp EJS** — image installs `nodejs`; yt-dlp is
  invoked with `--js-runtimes node`. Required for the YouTube n-challenge
  solver. Without it, only images are available and downloads fail.
- **SQLite WAL** files (`jobs.db-wal`, `jobs.db-shm`) live next to
  `jobs.db`. They're normal. Do not delete while the service is running.
- **Frames directory on crash:** workdir is wiped at startup, not
  between jobs. If the process is killed mid-job, the next boot cleans
  up.
- **Vision-capable model required.** LM Studio must have a model that
  accepts image inputs (e.g. `gemma4`). If the model refuses images the
  LLM will return text about "can't see images" and the analysis will be
  nonsense — no exception raised.
- **Whisper language is baked per deploy** (`WHISPER_LANGUAGE`). If a
  caller submits an English video while the service runs with `de`,
  whisper will still try — quality will drop. No per-request override
  yet; add to the POST body if needed.

## Deploy

Set the image tag in your `docker-compose.yml` (copy from
[docker-compose.yml.sample](../docker-compose.yml.sample)) to your own
registry, then:

```bash
docker compose build
docker push your-registry.local/ai-video-analyzer:latest
```

The service has no HA story. One instance per deployment. If you run
multiple replicas behind a load balancer they will fight over the same
SQLite file — don't.
