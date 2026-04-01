import logging
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, HTTPException, UploadFile

from utils import ALLOWED_CONTENT_TYPES, ALLOWED_EXTENSIONS, UPLOADS_DIR

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
CHUNK_SIZE = 256 * 1024  # 256 KB


@router.post("/upload")
async def upload_audio(file: UploadFile) -> dict:
    """Accept an mp3/wav file, save it under a UUID, and return the file_id.

    Validation checks both file extension and content-type to prevent spoofed uploads.
    File is written in chunks to avoid loading large files into memory.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported file type '{suffix}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported content type '{content_type}'.",
        )

    file_id = str(uuid.uuid4())
    dest_path = UPLOADS_DIR / f"{file_id}{suffix}"
    bytes_written = 0

    try:
        async with aiofiles.open(dest_path, "wb") as out:
            while chunk := await file.read(CHUNK_SIZE):
                bytes_written += len(chunk)
                if bytes_written > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413, detail="File exceeds 100 MB limit"
                    )
                await out.write(chunk)
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        logger.exception("Upload failed for %s", file.filename)
        raise HTTPException(status_code=500, detail="Upload failed") from exc

    logger.info(
        "Uploaded '%s' as %s%s (%d bytes)",
        file.filename,
        file_id,
        suffix,
        bytes_written,
    )
    return {
        "file_id": file_id,
        "filename": file.filename,
        "size_bytes": bytes_written,
        "format": suffix.lstrip("."),
    }
