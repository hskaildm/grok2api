"""
Video async task manager.

Provides in-memory task pool for async video generation:
- POST /v1/videos submits a task and returns task_id immediately
- GET /v1/videos/{task_id} polls for progress and result
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.core.logger import logger

# ---------------------------------------------------------------------------
# Task data structure
# ---------------------------------------------------------------------------

@dataclass
class VideoTask:
    """A single async video generation task."""

    id: str
    status: str  # "pending" | "in_progress" | "completed" | "failed"
    created_at: float

    # Request params (for display when polling)
    model: str = ""
    prompt: str = ""
    size: str = ""
    seconds: int = 6
    quality: str = "standard"

    # Progress (updated during generation)
    progress: int = 0           # 总进度 0-100（整数）
    progress_detail: str = ""   # round 详情，如 "round 1/2"

    # Result (set on completion)
    video_url: str = ""         # 完成时的视频链接

    # Error (set on failure)
    error: Optional[str] = None

    # Internal: the asyncio.Task handle (not serialized)
    _async_task: Optional[asyncio.Task] = field(default=None, repr=False)

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serializable snapshot for the polling endpoint."""
        return {
            "id": self.id,
            "object": "video.generation",
            "status": self.status,
            "progress": self.progress,
            "progress_detail": self.progress_detail,
            "video_url": self.video_url,
            "image_url": "",
            "error": self.error,
            "output": [{"url": self.video_url}] if self.status == "completed" and self.video_url else [],
            "result": {
                "url": self.video_url,
                "model": self.model,
                "prompt": self.prompt,
                "size": self.size,
                "seconds": self.seconds,
                "quality": self.quality,
            } if self.status == "completed" and self.video_url else None,
            "content_violation": False,
            "created_at": int(self.created_at),
            "model": self.model,
            "prompt": self.prompt,
            "size": self.size,
            "seconds": self.seconds,
            "quality": self.quality,
        }


# ---------------------------------------------------------------------------
# Global task pool
# ---------------------------------------------------------------------------

_VIDEO_TASKS: Dict[str, VideoTask] = {}

# Max tasks kept in memory (prevent unbounded growth)
_MAX_TASKS = 1000


def create_video_task(
    *,
    model: str = "",
    prompt: str = "",
    size: str = "",
    seconds: int = 6,
    quality: str = "standard",
) -> VideoTask:
    """Create a new pending video task and register it in the pool."""
    # Cleanup if pool is too large
    if len(_VIDEO_TASKS) >= _MAX_TASKS:
        _cleanup_oldest()

    task_id = f"vtask_{uuid.uuid4().hex[:16]}"
    task = VideoTask(
        id=task_id,
        status="pending",
        created_at=time.time(),
        model=model,
        prompt=prompt,
        size=size,
        seconds=seconds,
        quality=quality,
    )
    _VIDEO_TASKS[task_id] = task
    logger.info(f"Video task created: {task_id}")
    return task


def get_video_task(task_id: str) -> Optional[VideoTask]:
    """Look up a task by ID. Returns None if not found or expired."""
    return _VIDEO_TASKS.get(task_id)


def delete_video_task(task_id: str) -> None:
    """Remove a task from the pool."""
    _VIDEO_TASKS.pop(task_id, None)


async def expire_video_task(task_id: str, delay: int = 3600) -> None:
    """Auto-delete a task after `delay` seconds (default 1 hour)."""
    await asyncio.sleep(delay)
    if task_id in _VIDEO_TASKS:
        logger.debug(f"Video task expired and removed: {task_id}")
        delete_video_task(task_id)


def _cleanup_oldest() -> None:
    """Remove the oldest completed/failed tasks when pool is full."""
    # First pass: remove completed/failed tasks older than 10 minutes
    cutoff = time.time() - 600
    to_remove = [
        tid
        for tid, t in _VIDEO_TASKS.items()
        if t.status in ("completed", "failed") and t.created_at < cutoff
    ]
    for tid in to_remove:
        del _VIDEO_TASKS[tid]

    # If still too many, remove oldest regardless of status
    if len(_VIDEO_TASKS) >= _MAX_TASKS:
        sorted_tasks = sorted(_VIDEO_TASKS.items(), key=lambda x: x[1].created_at)
        remove_count = len(_VIDEO_TASKS) - _MAX_TASKS + 100  # free up 100 slots
        for tid, _ in sorted_tasks[:remove_count]:
            del _VIDEO_TASKS[tid]

    logger.debug(f"Video task pool cleanup: {len(_VIDEO_TASKS)} tasks remaining")


__all__ = [
    "VideoTask",
    "create_video_task",
    "get_video_task",
    "delete_video_task",
    "expire_video_task",
]
