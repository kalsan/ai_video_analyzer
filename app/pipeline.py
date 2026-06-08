import glob
import logging
import os
import subprocess
import sys
from pathlib import Path

from vidwit import config as vidwit_cfg_mod
from vidwit import pipeline as vidwit_pipeline

from . import config, llm

log = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


def run(url: str, workdir: str) -> str:
    """Download video, run vidwit witness pass, then synthesize via LLM."""
    Path(workdir).mkdir(parents=True, exist_ok=True)
    video_path = _download_video(url, workdir)
    witness_md = _vidwit_witness(video_path, workdir)
    return _synthesize(witness_md)


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    log.info("exec: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise PipelineError(
            f"{cmd[0]} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc


def update_yt_dlp() -> None:
    """Upgrade yt-dlp + yt-dlp-ejs into user site-packages. User site wins over system."""
    proc = _run(
        [sys.executable, "-m", "pip", "install", "--user", "--quiet",
         "--no-cache-dir", "-U", "yt-dlp", "yt-dlp-ejs"],
        check=False,
    )
    if proc.returncode != 0:
        log.warning("yt-dlp pip upgrade exited %s: %s",
                    proc.returncode, proc.stderr.strip())


def _download_video(url: str, workdir: str) -> str:
    output_template = os.path.join(workdir, "video.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--js-runtimes", "node",
        "--format", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "--merge-output-format", "mkv",
        "--output", output_template,
    ]
    cookies = "/data/cookies.txt"
    if os.path.isfile(cookies):
        cmd += ["--cookies", cookies]
    cmd.append(url)
    _run(cmd)
    matches = glob.glob(os.path.join(workdir, "video.*"))
    if not matches:
        raise PipelineError("yt-dlp produced no output file")
    return matches[0]


def _vidwit_witness(video_path: str, workdir: str) -> str:
    """Run vidwit on the downloaded video. Returns its markdown record."""
    video = Path(video_path)
    out_dir = Path(workdir) / "witness"
    scratch_dir = Path(workdir) / "vidwit-scratch"
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir.mkdir(parents=True, exist_ok=True)

    cfg = vidwit_cfg_mod.Config(
        fps=config.VIDWIT_FPS,
        window=config.VIDWIT_WINDOW_S,
        overlap=config.VIDWIT_OVERLAP_S,
        overwrite=True,
        resume=False,
        keep_scratch=False,
        paths_home=out_dir,
        paths_temp=scratch_dir,
        whisper_model=config.WHISPER_MODEL,
        whisper_device=config.WHISPER_DEVICE,
        audio_language=config.WHISPER_LANGUAGE,
        max_tokens=config.VIDWIT_MAX_TOKENS,
        llm=vidwit_cfg_mod.LLMConfig(
            provider=config.LLM_PROVIDER,
            model=_vidwit_model_for(config.LLM_PROVIDER),
            base_url=_vidwit_base_url_for(config.LLM_PROVIDER),
            api_key=config.ANTHROPIC_API_KEY,
            max_output_tokens=config.LLM_MAX_TOKENS,
            request_timeout=float(config.LLM_READ_TIMEOUT),
        ),
    )

    log.info(
        "vidwit: model=%s lang=%s fps=%g window=%gs overlap=%gs",
        cfg.whisper_model, cfg.audio_language, cfg.fps, cfg.window, cfg.overlap,
    )
    try:
        out_md_path = vidwit_pipeline.run_one(video, cfg)
    except Exception as e:
        raise PipelineError(f"vidwit failed: {e}") from e
    log.info("vidwit: wrote %s", out_md_path)
    return out_md_path.read_text(encoding="utf-8")


def _vidwit_model_for(provider: str) -> str:
    if provider == "lmstudio":
        return config.LM_STUDIO_MODEL
    if provider == "anthropic":
        return config.ANTHROPIC_MODEL
    return ""


def _vidwit_base_url_for(provider: str) -> str | None:
    if provider == "lmstudio":
        # vidwit appends `/chat/completions`; strip it from our config so
        # we don't end up with `.../v1/chat/completions/chat/completions`.
        url = config.LM_STUDIO_URL
        suffix = "/chat/completions"
        return url[: -len(suffix)] if url.endswith(suffix) else url
    return None


def _synthesize(witness_md: str) -> str:
    """Second-stage call: apply ANALYSIS_PROMPT over vidwit's witness markdown."""
    log.info("synthesize: %d chars of witness markdown", len(witness_md))
    content = llm.chat(
        system=config.ANALYSIS_PROMPT,
        user_parts=[{"type": "text", "text": witness_md}],
    )
    if not content.strip():
        raise PipelineError("LLM returned empty synthesis")
    return content
