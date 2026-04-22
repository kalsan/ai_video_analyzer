import glob
import logging
import os
import subprocess
from pathlib import Path

from . import config, llm

log = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


def run(url: str, workdir: str) -> str:
    """Download video, extract frames + transcript, call LLM, return analysis."""
    Path(workdir).mkdir(parents=True, exist_ok=True)
    video_path = _download_video(url, workdir)
    frames_dir = _extract_frames(video_path, workdir)
    transcript = _extract_transcript(video_path, workdir)
    return _analyze(frames_dir, transcript)


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    log.info("exec: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise PipelineError(
            f"{cmd[0]} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc


def _update_yt_dlp() -> None:
    proc = _run(["yt-dlp", "-U"], check=False)
    if proc.returncode != 0:
        log.warning("yt-dlp -U exited %s: %s", proc.returncode, proc.stderr.strip())


def _download_video(url: str, workdir: str) -> str:
    _update_yt_dlp()
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


def _extract_frames(video_path: str, workdir: str) -> str:
    frames_dir = os.path.join(workdir, "frames")
    Path(frames_dir).mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg", "-i", video_path,
            "-vf", f"fps=1/{config.FRAME_INTERVAL_SECONDS}",
            "-q:v", "2",
            os.path.join(frames_dir, "frame_%04d.jpg"),
        ]
    )
    return frames_dir


def _extract_transcript(video_path: str, workdir: str) -> str:
    _run(
        [
            "whisper", video_path,
            "--language", config.WHISPER_LANGUAGE,
            "--output_dir", workdir,
            "--output_format", "vtt",
            "--model", config.WHISPER_MODEL,
        ]
    )
    vtt_files = glob.glob(os.path.join(workdir, "*.vtt"))
    if vtt_files:
        return Path(vtt_files[0]).read_text()
    txt_files = glob.glob(os.path.join(workdir, "*.txt"))
    if txt_files:
        return Path(txt_files[0]).read_text()
    return ""


def _analyze(frames_dir: str, transcript: str) -> str:
    frame_paths = sorted(glob.glob(os.path.join(frames_dir, "*.jpg")))
    if not frame_paths:
        raise PipelineError("No frames extracted")

    step = max(-(-len(frame_paths) // config.MAX_FRAMES_TO_LLM), 1)
    selected = frame_paths[::step]
    log.info("sending %d/%d frames to LLM", len(selected), len(frame_paths))

    parts: list[dict] = []
    for idx, path in enumerate(selected):
        ts = idx * step * config.FRAME_INTERVAL_SECONDS
        parts.append({"type": "text", "text": f"[Frame at {ts // 60}:{ts % 60:02d}]"})
        parts.append(
            {
                "type": "image",
                "data": Path(path).read_bytes(),
                "media_type": "image/jpeg",
            }
        )
    parts.append({"type": "text", "text": f"## Transcript with timestamps\n\n{transcript}"})

    content = llm.chat(system=config.ANALYSIS_PROMPT, user_parts=parts)
    if not content.strip():
        raise PipelineError("LLM returned empty content")
    return content
