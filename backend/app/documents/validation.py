"""Upload validation: type, size, magic bytes and document integrity."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, UnidentifiedImageError

from ..core.config import Settings
from .types import DocumentFormat, DocumentRejected, reason

_ALLOWED_EXTENSIONS = {
    ".pdf": DocumentFormat.PDF,
    ".png": DocumentFormat.PNG,
    ".jpg": DocumentFormat.JPEG,
    ".jpeg": DocumentFormat.JPEG,
}
_ALLOWED_MIMES = {
    DocumentFormat.PDF: {"application/pdf"},
    DocumentFormat.PNG: {"image/png"},
    DocumentFormat.JPEG: {"image/jpeg", "image/jpg"},
}


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    format: DocumentFormat
    mime_type: str
    extension: str
    page_count: int


def _reject(code: str, message: str) -> DocumentRejected:
    return DocumentRejected(code, message, [reason(code, message, "ERROR")])


def validate_upload(
    *, filename: str, declared_mime: str, data: bytes, settings: Settings
) -> ValidatedUpload:
    if not data:
        raise _reject("EMPTY_FILE", "The uploaded file is empty.")
    maximum = settings.security.max_upload_bytes
    if len(data) > maximum:
        raise _reject(
            "FILE_TOO_LARGE",
            f"The file is {len(data)} bytes; the limit is {maximum} bytes.",
        )

    extension = Path(filename or "").suffix.lower()
    detected: DocumentFormat
    if data.startswith(b"%PDF-"):
        detected = DocumentFormat.PDF
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = DocumentFormat.PNG
    elif data.startswith(b"\xff\xd8\xff"):
        detected = DocumentFormat.JPEG
    else:
        raise _reject(
            "UNSUPPORTED_TYPE",
            "Only PDF, PNG and JPEG documents are accepted; the file signature was not recognised.",
        )

    if extension and extension not in _ALLOWED_EXTENSIONS:
        raise _reject(
            "UNSUPPORTED_TYPE",
            f"The extension {extension!r} is not accepted.",
        )
    if extension and _ALLOWED_EXTENSIONS[extension] is not detected:
        raise _reject(
            "MIME_MISMATCH",
            "The file extension does not match the file's actual format.",
        )

    provided = (declared_mime or "").split(";", 1)[0].strip().lower()
    if (
        provided
        and provided not in {"application/octet-stream"}
        and provided not in _ALLOWED_MIMES[detected]
    ):
        raise _reject(
            "MIME_MISMATCH",
            f"The declared content type {provided!r} does not match the file's actual format.",
        )

    if detected is DocumentFormat.PDF:
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except (pymupdf.FileDataError, RuntimeError, ValueError) as error:
            raise _reject("CORRUPT_PDF", "The PDF could not be opened.") from error
        try:
            if document.needs_pass:
                raise _reject("PDF_ENCRYPTED", "The PDF is password-protected.")
            pages = document.page_count
            if pages < 1:
                raise _reject("EMPTY_DOCUMENT", "The PDF has no pages.")
            if pages > settings.ingestion.max_pages:
                raise _reject(
                    "TOO_MANY_PAGES",
                    f"The PDF has {pages} pages; the limit is {settings.ingestion.max_pages}.",
                )
        finally:
            document.close()
        return ValidatedUpload(
            format=detected,
            mime_type="application/pdf",
            extension=".pdf",
            page_count=pages,
        )

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = image.format
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise _reject("CORRUPT_IMAGE", "The image could not be decoded.") from error
    if image_format not in {"PNG", "JPEG"}:
        raise _reject("UNSUPPORTED_TYPE", "Only PNG and JPEG images are accepted.")
    if width < 1 or height < 1:
        raise _reject("EMPTY_DOCUMENT", "The image has no pixels.")
    if width * height > settings.ingestion.max_image_pixels:
        raise _reject(
            "IMAGE_TOO_LARGE",
            f"The image is {width}x{height}; the pixel limit is "
            f"{settings.ingestion.max_image_pixels}.",
        )
    return ValidatedUpload(
        format=detected,
        mime_type="image/png" if detected is DocumentFormat.PNG else "image/jpeg",
        extension=".png" if detected is DocumentFormat.PNG else ".jpg",
        page_count=1,
    )
