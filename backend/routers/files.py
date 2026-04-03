"""Serve uploaded audio files for browser playback and download."""

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from utils import get_upload_path, validate_file_id

logger = logging.getLogger(__name__)

router = APIRouter()

_MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}


@router.get("/files/{file_id}")
async def serve_file(file_id: str) -> FileResponse:
    """Stream an uploaded or processed audio file.

    Used by the frontend <audio> element for playback and the export download link.
    Range requests are handled automatically by FileResponse (Starlette supports it).
    """
    validate_file_id(file_id)
    path: Path = get_upload_path(file_id)
    media_type = _MEDIA_TYPES.get(path.suffix, "application/octet-stream")
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=path.name,
        headers={"Accept-Ranges": "bytes"},
    )
