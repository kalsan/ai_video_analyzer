# Architecture

## Components

```
┌───────────────────────┐
│   FastAPI (main.py)   │  HTTP: POST /jobs, GET /jobs, GET /health
└──────────┬────────────┘
           │ enqueue(job_id)
           ▼
┌───────────────────────┐
│  queue.py worker      │  single threading.Thread, queue.Queue[int]
│  (one job at a time)  │
└──────────┬────────────┘
           │ run(url, workdir)
           ▼
┌───────────────────────┐
│  pipeline.py          │  yt-dlp → ffmpeg → whisper → llm.chat
└──────────┬────────────┘
           │
           ▼
┌───────────────────────┐
│  db.py (SQLite)       │  /data/jobs.db — bind-mounted
└───────────────────────┘
```

## Process model

One Python process, one uvicorn worker, one background thread.

The worker is `threading.Thread(daemon=True)` driven by a
`queue.Queue[int]`. It blocks on `Queue.get()` when idle. HTTP handlers
push job IDs onto the queue; the worker pulls and runs one at a time.

Serial-by-construction: if you want concurrency, you must change the
worker, not add more queue consumers. `openai-whisper` and multi-frame
vision LLM calls are CPU/GPU-bound anyway — parallelism buys little.

## Database

SQLite at `$DB_PATH` (default `/data/jobs.db`). Single table:

```sql
CREATE TABLE jobs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  url        TEXT NOT NULL UNIQUE,     -- natural key
  status     TEXT NOT NULL,            -- queued | running | done | failed
  result     TEXT,                     -- analysis string when status=done
  error      TEXT,                     -- error message when status=failed
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_jobs_status ON jobs(status);
```

`url` is the natural key. One row per URL lifetime. Rows are never deleted
by the service — persistence is intentional so callers can read historical
results. Add a cleanup cron if the table grows unbounded.

WAL mode is on. A single `threading.Lock` (`db._lock`) serialises all
writes to avoid `database is locked` races between the HTTP thread pool
and the worker thread.

### Status transitions

```
          POST (new)
             │
             ▼
         ┌───────┐   worker picks up   ┌─────────┐
         │queued │ ──────────────────▶ │ running │
         └───────┘                     └────┬────┘
              ▲                             │
              │ POST (was failed)   ┌───────┴──────┐
              │                     ▼              ▼
              │                 ┌──────┐      ┌────────┐
              └─ POST resets ◀─ │failed│      │  done  │
                                └──────┘      └────────┘
```

- `POST /jobs` on a `failed` row resets it to `queued` (one-shot retry).
- `POST /jobs` on a `done` row is a no-op (idempotent, returns existing
  result). This is intentional: re-analysing the same URL produces roughly
  the same output and wastes GPU.
- `POST /jobs` on a `queued`/`running` row is a no-op.
- On unclean shutdown a job may stay in `running`. Next startup flips all
  `running` → `queued` (see below).

## Queue

`queue.py` module-level state:

- `_q: queue.Queue[int]` — job IDs waiting for the worker.
- `_thread: Thread | None` — worker thread handle.
- `_stopping: Event` — shutdown flag.

Public API:

- `start()` — called from FastAPI lifespan. Wipes `$WORK_DIR`, requeues
  any `running` rows (crash recovery), pushes all `queued` rows onto the
  in-memory queue in `created_at` order, spawns the worker thread.
- `enqueue(job_id)` — called by `POST /jobs` after the DB insert/update.
- `stop()` — called from FastAPI lifespan on shutdown. Sets the event and
  pushes a sentinel `-1` to unblock `Queue.get()`.

### Startup sequence

1. `shutil.rmtree` everything under `$WORK_DIR`. Abandoned frames / video
   files from crashed jobs get freed. Persistent state (DB) is never
   touched here.
2. `UPDATE jobs SET status='queued' WHERE status='running'`. Crash
   recovery: if the process died mid-pipeline, the row is now back in the
   queue and will be retried on next worker pick-up.
3. `SELECT id FROM jobs WHERE status='queued' ORDER BY created_at` →
   `Queue.put(id)` for each.
4. Spawn worker thread.

This is the *only* retry path. Failed jobs (`status='failed'`) are NOT
re-enqueued on startup. A failed job is a decision, not a transient state.

## Pipeline

Per-job working directory: `$WORK_DIR/<job_id>`. Created fresh, removed
in `finally` even on exception. Contains:

- `video.<ext>` — raw download from yt-dlp.
- `frames/frame_0001.jpg ... frame_NNNN.jpg` — one per `FRAME_INTERVAL_SECONDS`.
- `video.vtt` (or `.txt` fallback) — whisper output.

### Frame subsampling

Whisper VTT can be huge (~minutes of tokens). Vision model context is the
bottleneck, so frames are subsampled to at most `MAX_FRAMES_TO_LLM` (30 by
default) using even striding:

```python
step = ceil(len(frames) / MAX_FRAMES_TO_LLM)
selected = frames[::step]
```

Each selected frame is tagged with its timestamp (minutes:seconds) so the
LLM can cross-reference the VTT narration.

### LLM call

`llm.chat(system=ANALYSIS_PROMPT, user_parts=[...])`.

`user_parts` is an ordered list of:

- `{"type": "text", "text": "[Frame at M:SS]"}` — timestamp marker.
- `{"type": "image", "data": bytes, "media_type": "image/jpeg"}` — frame.
- A final `{"type": "text", "text": "## Transcript with timestamps\n\n..."}`.

Order matters: frame markers precede their image, transcript comes last.

## Error handling

Every worker exception is caught, logged with `logging.exception`, and
written to `jobs.error` as a plain string. The pipeline does NOT retry —
if yt-dlp hit a 403, whisper OOMed, or the LLM timed out, the operator or
the caller decides whether to resubmit.

HTTP handlers translate DB state to status codes (see [api.md](api.md)).
