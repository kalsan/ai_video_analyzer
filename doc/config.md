# Configuration

All config via environment variables. Defaults live in
[app/config.py](../app/config.py).

## Paths

| Var        | Default          | Purpose                                         |
|------------|------------------|-------------------------------------------------|
| `DB_PATH`  | `/data/jobs.db`  | SQLite file. Bind-mount the parent dir for persistence. |
| `WORK_DIR` | `/work`          | Ephemeral per-job workdir. Wiped on startup. Do NOT bind-mount. |

### `/data/cookies.txt` (optional)

After a few requests, YouTube now requires users to log in. The session can be shared with this tool via cookie export, after which the YouTube will see the tool as logged in via your YouTube session.

If a Netscape-format `cookies.txt` file exists at `/data/cookies.txt`,
it is passed to `yt-dlp` via `--cookies`. Required for age-gated,
member-only, or bot-challenged YouTube videos.

**Export procedure**

Under Firefox, use the `cookies.txt` extension and click "Copy website and container".

If yt-dlp reports *"The provided YouTube account cookies are no longer
valid"*, the cookies were rotated — re-export per the above.

Omit the file entirely to skip cookie auth (fine for plain public
videos).

## Pipeline knobs

| Var                      | Default | Notes                                                       |
|--------------------------|---------|-------------------------------------------------------------|
| `FRAME_INTERVAL_SECONDS` | `5`     | One frame every N seconds via ffmpeg.                       |
| `MAX_FRAMES_TO_LLM`      | `30`    | Hard cap on frames sent to the vision model; subsampled.    |
| `WHISPER_MODEL`          | `base`  | `tiny`, `base`, `small`, `medium`, `large`. Size vs accuracy. |
| `WHISPER_LANGUAGE`       | `de`    | ISO code. Set to the dominant narration language of your videos. |

## LLM

| Var                 | Default                                              | Notes                                               |
|---------------------|------------------------------------------------------|-----------------------------------------------------|
| `LLM_PROVIDER`      | `lmstudio`                                           | `lmstudio` or `anthropic`.                          |
| `LLM_READ_TIMEOUT`  | `900`                                                | Seconds. Vision calls with 30 frames can be slow.   |
| `LLM_MAX_TOKENS`    | `4000`                                               | Per response.                                       |
| `LLM_TEMPERATURE`   | `0.2`                                                | Low — we want consistent structured output.         |
| `LM_STUDIO_URL`     | `http://localhost:1234/v1/chat/completions`          | OpenAI-compatible endpoint.                         |
| `LM_STUDIO_MODEL`   | `gemma4`                                             | Must be vision-capable.                             |
| `ANTHROPIC_API_KEY` | —                                                    | Required when `LLM_PROVIDER=anthropic`.             |
| `LLM_ANTHROPIC_MODEL` | `claude-sonnet-4-6`                                | Any vision-capable Claude model.                    |

## System prompt

The **system prompt** is loaded from `config/prompt.md` at process
start. If that file is missing (e.g. fresh checkout of the public repo),
`config/prompt.md.sample` is used as a fallback.

To customise: copy `config/prompt.md.sample` to `config/prompt.md` and
edit. `config/prompt.md` is gitignored so domain-specific prompts stay
out of the public repo. Override the path with `PROMPT_PATH=/abs/file`
if you want to bind-mount it from outside the image.
