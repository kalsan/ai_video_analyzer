import logging
import queue as _queue
import shutil
import threading
from pathlib import Path

from . import config, db, pipeline

log = logging.getLogger(__name__)

_q: "_queue.Queue[int]" = _queue.Queue()
_thread: threading.Thread | None = None
_stopping = threading.Event()


def start() -> None:
    """Startup recovery + worker boot.

    1. Wipe WORK_DIR (abandoned frames/video from crashed jobs).
    2. Flip any 'running' rows back to 'queued' (crash recovery).
    3. Enqueue all 'queued' rows in creation order.
    4. Spawn worker thread.
    """
    global _thread
    _wipe_workdir()
    pipeline.update_yt_dlp()
    requeued = db.requeue_running()
    if requeued:
        log.info("recovered %d interrupted job(s): %s", len(requeued), requeued)
    queued = db.queued_ids()
    for job_id in queued:
        _q.put(job_id)
    log.info("enqueued %d job(s) on startup", len(queued))

    _thread = threading.Thread(target=_run, name="video-worker", daemon=True)
    _thread.start()


def stop() -> None:
    _stopping.set()
    _q.put(-1)  # sentinel


def enqueue(job_id: int) -> None:
    _q.put(job_id)


def _wipe_workdir() -> None:
    root = Path(config.WORK_DIR)
    if root.exists():
        for child in root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
    else:
        root.mkdir(parents=True, exist_ok=True)


def _run() -> None:
    while not _stopping.is_set():
        job_id = _q.get()
        if job_id < 0:
            break
        _process(job_id)


def _process(job_id: int) -> None:
    row = db.find(job_id)
    if row is None:
        log.warning("job %s vanished", job_id)
        return
    if row["status"] != db.STATUS_QUEUED:
        log.info("job %s status=%s, skipping", job_id, row["status"])
        return

    workdir = str(Path(config.WORK_DIR) / str(job_id))
    db.mark_running(job_id)
    log.info("job %s starting: %s", job_id, row["url"])
    try:
        result = pipeline.run(row["url"], workdir=workdir)
        db.mark_done(job_id, result)
        log.info("job %s done", job_id)
    except Exception as e:
        log.exception("job %s failed", job_id)
        db.mark_failed(job_id, str(e))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
