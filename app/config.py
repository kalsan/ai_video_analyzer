import os
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "/data/jobs.db")
WORK_DIR = os.environ.get("WORK_DIR", "/work")

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "de")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")

VIDWIT_FPS = float(os.environ.get("VIDWIT_FPS", "1.0"))
VIDWIT_WINDOW_S = float(os.environ.get("VIDWIT_WINDOW_S", "10.0"))
VIDWIT_OVERLAP_S = float(os.environ.get("VIDWIT_OVERLAP_S", "1.0"))
VIDWIT_MAX_TOKENS = (
    int(os.environ["VIDWIT_MAX_TOKENS"])
    if os.environ.get("VIDWIT_MAX_TOKENS")
    else None
)

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "lmstudio").lower()
LLM_READ_TIMEOUT = int(os.environ.get("LLM_READ_TIMEOUT", "900"))
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "4000"))
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.2"))

LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://localhost:1234/v1/chat/completions")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "gemma4")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = os.environ.get("LLM_ANTHROPIC_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_VERSION = "2023-06-01"

def _load_prompt() -> str:
    explicit = os.environ.get("PROMPT_PATH")
    if explicit:
        return Path(explicit).read_text(encoding="utf-8")
    base = Path(__file__).resolve().parent.parent / "config"
    for candidate in (base / "prompt.md", base / "prompt.md.sample"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise RuntimeError(f"No prompt.md or prompt.md.sample found in {base}")


ANALYSIS_PROMPT = _load_prompt()
