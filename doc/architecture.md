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
│  pipeline.py          │  yt-dlp → vidwit (engine) → llm.chat synthesis
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
worker, not add more queue consumers. vidwit's per-window vision LLM
calls are CPU/GPU-bound anyway — parallelism buys little.

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
2. `pip install --user -U yt-dlp yt-dlp-ejs`. Picks up the latest
   extractor + n-challenge solver into the runner's user site. Failure
   is logged and ignored (falls back to the image-baked version).
3. `UPDATE jobs SET status='queued' WHERE status='running'`. Crash
   recovery: if the process died mid-pipeline, the row is now back in the
   queue and will be retried on next worker pick-up.
4. `SELECT id FROM jobs WHERE status='queued' ORDER BY created_at` →
   `Queue.put(id)` for each.
5. Spawn worker thread.

This is the *only* retry path. Failed jobs (`status='failed'`) are NOT
re-enqueued on startup. A failed job is a decision, not a transient state.

## Pipeline

Per-job working directory: `$WORK_DIR/<job_id>`. Created fresh, removed
in `finally` even on exception. Contains:

- `video.<ext>` — raw download from yt-dlp.
- `vidwit-scratch/` — vidwit's per-video scratch (audio.wav, frames,
  per-window chunks, transcript.json). Wiped after successful run unless
  `keep_scratch` is on.
- `witness/video.md` — vidwit's witness markdown (TOC + timecoded
  blocks + content warnings). Fed into the synthesis call.

### Engine: vidwit

The analysis engine is the [vidwit](https://pypi.org/project/vidwit/)
package (PyPI). It
runs per-window (`VIDWIT_WINDOW_S` seconds, `VIDWIT_OVERLAP_S` overlap)
with rolling context, so videos that don't fit in a single LLM call still
produce a coherent output. Internally:

```
ffmpeg → frames (at VIDWIT_FPS) ┐
faster-whisper word-level ──────┼─► per-window vision LLM ─► chunk_NNNN.md
rolling tail + capture metadata ┘                            (resumable)
                                                                │
                                                                ▼
                                                        assemble + TOC
                                                                │
                                                                ▼
                                                        witness markdown
```

### Synthesis call

A second LLM call applies `config/prompt.md` (`ANALYSIS_PROMPT`) over the
witness markdown to produce the job result. Text-only — frames have
already been described by vidwit:

```python
llm.chat(
    system=ANALYSIS_PROMPT,
    user_parts=[{"type": "text", "text": witness_md}],
)
```

This two-stage design keeps the service contract unchanged (one
freeform markdown per job) while delegating the expensive
multimodal grounding to vidwit's chunked pipeline.

## Error handling

Every worker exception is caught, logged with `logging.exception`, and
written to `jobs.error` as a plain string. The pipeline does NOT retry —
if yt-dlp hit a 403, vidwit failed transcription, or the LLM timed out, the operator or
the caller decides whether to resubmit.

HTTP handlers translate DB state to status codes (see [api.md](api.md)).
