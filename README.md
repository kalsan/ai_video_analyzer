# AI video analyzer

HTTP microservice that takes a video URL (YouTube or similar) and returns a
structured markdown analysis of the video. The analysis format is driven by
a user-supplied system prompt in [config/prompt.md](config/prompt.md) — see
[config/prompt.md.sample](config/prompt.md.sample) for a generic default.

## Purpose

Given a video URL (YouTube / any yt-dlp-supported source), produce a
structured markdown summary of the video's content. The shape of the
summary is determined by the operator-supplied system prompt.

Pipeline:

1. Download video (yt-dlp).
2. Extract 1 frame every 5 seconds (ffmpeg).
3. Transcribe audio to VTT (openai-whisper).
4. Send subsampled frames + transcript to a vision-capable LLM with the
   configured system prompt.
5. Return the LLM's markdown as the job result.

## Origin

Extracted from a larger web application so the heavy ML dependencies
(ffmpeg + python + whisper, ~2 GB) could live in their own image and
evolve independently of the caller.

The caller owns the decision *when* to analyse a video and *how to
display the result*. This service owns the *how*: download,
transcription, frame extraction, LLM call.

## Scope

In scope:

- Receive URL → run pipeline → persist result keyed by URL.
- One job at a time, serial queue.
- Crash-safe: interrupted jobs restart on process startup.
- No auth (reach via private network only).

Out of scope:

- Multi-tenancy. Caller is trusted; URL is the only identifier.
- Webhook callbacks. Callers poll.
- Retry on failure. A failed job stays failed until the caller POSTs the
  same URL again.
- Pushing results back to the caller's DB. Caller fetches and stores.

## Source of truth

The system prompt lives in [config/prompt.md](config/prompt.md) (your
customised copy, gitignored) with [config/prompt.md.sample](config/prompt.md.sample)
as a fallback default. If you tweak the prompt, that's a deliberate
change — do not try to "sync" with any other repo.

## More detailed documentation

1. [architecture.md](doc/architecture.md) — worker, queue, DB, startup recovery.
2. [api.md](doc/api.md) — HTTP contract (endpoints, status codes, JSON shapes).
3. [config.md](doc/config.md) — env vars, defaults.
4. [integration.md](doc/integration.md) — how callers use it.
5. [development.md](doc/development.md) — local run, smoke tests, deploy.
