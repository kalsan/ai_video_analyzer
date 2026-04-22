# Integration contract

How any caller should interact with this service.

## The contract

1. Caller POSTs `{"url": "..."}` to kick off analysis.
2. Caller polls `GET /jobs?url=...` periodically until `status=done` or
   `status=failed`.
3. Caller persists the result (or error) on its side, keyed by whatever
   makes sense to it. This service keeps its own copy keyed by URL.
4. This service never calls back. No webhooks. No push.

## Expected caller behaviour

- POST the URL. Check HTTP code: 202 means wait, 200 means result ready.
- Poll GET. Don't hammer — interval ≥ 1 minute is fine. Whisper + LLM on
  a long video can take many minutes; shorter polling wastes worker
  slots on the caller side for no benefit.
- On 404, treat it as "resubmit", not as an error. The analyzer's DB
  could have been wiped / migrated / this is a fresh deploy.
- On 422 with `error` body, surface the error to a human; don't
  auto-retry. Re-POSTing the same URL IS the retry mechanism and should
  be a deliberate action.

## Suggested status mapping on the caller side

Callers typically collapse `queued` + `running` into a single
`dispatched`/`pending` state, since both mean "keep polling":

| Analyzer `status` | HTTP | Typical caller state          |
|-------------------|------|-------------------------------|
| `queued`          | 202  | `dispatched`                  |
| `running`         | 202  | `dispatched`                  |
| `done`            | 200  | `completed`                   |
| `failed`          | 422  | `failed` (surface the error)  |
| (404 unknown)     | 404  | resubmit                      |

## What the analyzer will NOT do

- Reach back into caller DBs.
- Send webhooks, emails, or push notifications.
- Honour "priority" or "cancel" semantics. All jobs are FIFO, uncancellable
  once running. (A queued job that's not yet running can be wiped directly
  in SQLite, but there's no endpoint for it.)
- Store caller metadata. The URL is the only identifier.
