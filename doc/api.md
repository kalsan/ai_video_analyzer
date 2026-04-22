# HTTP API

All endpoints return JSON. No auth (run on a trusted private network).

## POST /jobs

Submit a video URL for analysis.

**Request:**

```http
POST /jobs
Content-Type: application/json

{"url": "https://youtu.be/abc123"}
```

**Semantics:** upsert keyed by `url`.

| Pre-state           | Effect                                       | Status | Response body                                         |
|---------------------|----------------------------------------------|--------|-------------------------------------------------------|
| no row              | insert `queued`, enqueue                     | 202    | `{"status":"queued","id":N}`                          |
| `queued`/`running`  | no-op                                        | 202    | `{"status":"queued\|running","id":N}`                 |
| `failed`            | reset to `queued`, clear error, enqueue      | 202    | `{"status":"queued","id":N}`                          |
| `done`              | no-op (idempotent; existing result returned) | 200    | `{"status":"done","id":N,"result":"..."}`             |
| empty / missing url | reject                                       | 400    | `{"detail":"url is required"}`                        |

**Why `POST` on `done` is a no-op:** re-analysing the same video wastes
GPU for near-identical output. If the caller wants to force-retry a done
job, delete the row first (no endpoint for that — do it in sqlite, or
extend the API).

**Why `POST` on `failed` auto-retries:** explicit caller signal. `failed`
never retries on its own (see [architecture.md](architecture.md)).

## GET /jobs?url=...

Fetch status/result for a submitted URL.

**Request:**

```http
GET /jobs?url=https%3A%2F%2Fyoutu.be%2Fabc123
```

**Response:**

| DB state  | Status | Body                                                  |
|-----------|--------|-------------------------------------------------------|
| no row    | 404    | `{"detail":"unknown url"}`                            |
| `queued`  | 202    | `{"status":"queued","id":N}`                          |
| `running` | 202    | `{"status":"running","id":N}`                         |
| `done`    | 200    | `{"status":"done","id":N,"result":"..."}`             |
| `failed`  | 422    | `{"status":"failed","id":N,"error":"..."}`            |

**Status-code rationale:**

- **200** only when the body carries the final artefact.
- **202** for both `queued` and `running` — caller treats them the same
  (keep polling). If the caller wants to distinguish, read `status` in
  the body.
- **404** means the service has no record of this URL. Caller should POST.
- **422** for `failed`: semantically valid request, but the server has
  determined the referenced job cannot complete. Distinct from 5xx
  (service is up, just this job broke).

## GET /health

Liveness probe.

```http
GET /health  →  200  {"ok": true}
```

No DB or queue check. Returns 200 as long as the HTTP server is up.

## Status vocabulary

The strings used in `status` fields, in `db.py`:

- `queued` — row exists, worker has not started it yet.
- `running` — worker is currently processing.
- `done` — pipeline completed, `result` populated.
- `failed` — pipeline raised; `error` populated.

These are the ONLY four values that appear. Callers should match exactly.
