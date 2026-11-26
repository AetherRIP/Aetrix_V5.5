"""Attachment classification and deterministic local inspection.

Nothing here calls Google or a model.  Classification decides what an attachment
*is* before anything is fetched, so an external link is recorded and never
crawled.  Inspection decides whether the bytes are a readable, non-empty answer
script, and reports what it found rather than guessing a mark.

The rules are deliberately explainable: every finding carries a code and a
sentence a teacher can act on.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError

from ..core.config import IngestionSettings

PDF_MIME = "application/pdf"
PNG_MIME = "image/png"
JPEG_MIME = "image/jpeg"

#: Formats the ingestion pipeline can accept directly.
DIRECT_MIMES = frozenset({PDF_MIME, PNG_MIME, JPEG_MIME})
IMAGE_MIMES = frozenset({PNG_MIME, JPEG_MIME})

_GOOGLE_DOC = "application/vnd.google-apps.document"
_GOOGLE_SLIDES = "application/vnd.google-apps.presentation"
_GOOGLE_DRAWING = "application/vnd.google-apps.drawing"
_GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
_GOOGLE_FORM = "application/vnd.google-apps.form"

#: Google Workspace types with a lossless PDF export path.  A spreadsheet has
#: no reliable page layout, so it is refused with a reason instead of exported
#: into something nobody can mark.
EXPORTABLE_MIMES = frozenset({_GOOGLE_DOC, _GOOGLE_SLIDES, _GOOGLE_DRAWING})

#: Google types that are genuinely not an answer script.
_UNSUPPORTED_GOOGLE = {
    _GOOGLE_SHEET: "a Google Sheet has no reliable single-script layout",
    _GOOGLE_FORM: "a Google Form is a questionnaire, not submitted work",
}


@dataclass(frozen=True, slots=True)
class ClassifiedAttachment:
    """What one Google attachment is, and what may be done with it."""

    position: int
    kind: str
    title: str | None
    google_file_id: str | None
    declared_mime: str | None
    #: ``DOWNLOAD``, ``EXPORT_PDF``, ``IGNORE`` or ``UNSUPPORTED``.
    action: str
    reason: str | None = None


def _normalise_mime(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def classify_attachments(
    attachments: list[dict[str, Any]] | None,
) -> list[ClassifiedAttachment]:
    """Classify every attachment, preserving Google's order.

    An external link is never downloaded.  A Drive file is fetched only when it
    is a supported format or a Workspace document with a safe PDF export.
    """

    classified: list[ClassifiedAttachment] = []
    for position, raw in enumerate(attachments or [], start=1):
        if not isinstance(raw, dict):
            classified.append(
                ClassifiedAttachment(
                    position=position,
                    kind="UNKNOWN",
                    title=None,
                    google_file_id=None,
                    declared_mime=None,
                    action="UNSUPPORTED",
                    reason="Google returned an attachment this engine cannot read.",
                )
            )
            continue
        kind = str(raw.get("kind") or "UNKNOWN").upper()
        title = (str(raw.get("title")).strip() or None) if raw.get("title") else None
        file_id = raw.get("drive_file_id")
        mime = _normalise_mime(raw.get("mime_type"))

        if kind in {"LINK", "EXTERNAL_LINK"}:
            classified.append(
                ClassifiedAttachment(
                    position=position,
                    kind="LINK",
                    title=title,
                    google_file_id=None,
                    declared_mime=None,
                    action="IGNORE",
                    reason=(
                        "An external website link is not fetched: only a file the "
                        "student uploaded can be marked."
                    ),
                )
            )
            continue
        if kind in {"YOUTUBE_VIDEO", "FORM"}:
            classified.append(
                ClassifiedAttachment(
                    position=position,
                    kind=kind,
                    title=title,
                    google_file_id=None,
                    declared_mime=None,
                    action="IGNORE",
                    reason=(
                        "This attachment type is a link or a form, not a submitted "
                        "document, so it was not fetched."
                    ),
                )
            )
            continue
        if kind != "DRIVE_FILE":
            classified.append(
                ClassifiedAttachment(
                    position=position,
                    kind="UNKNOWN",
                    title=title,
                    google_file_id=str(file_id) if file_id else None,
                    declared_mime=mime or None,
                    action="UNSUPPORTED",
                    reason=f"Attachment type {kind!r} is not supported.",
                )
            )
            continue

        if not file_id:
            classified.append(
                ClassifiedAttachment(
                    position=position,
                    kind="DRIVE_FILE",
                    title=title,
                    google_file_id=None,
                    declared_mime=mime or None,
                    action="UNSUPPORTED",
                    reason="Google reported a Drive file without an identifier.",
                )
            )
            continue

        if mime in DIRECT_MIMES:
            action = "DOWNLOAD"
            reason = None
        elif mime in EXPORTABLE_MIMES:
            action = "EXPORT_PDF"
            reason = None
        elif not mime:
            # Classroom's ``StudentSubmission`` DriveFile carries no
            # ``mimeType``.  The bytes are downloaded and ``inspect_bytes``
            # sniffs the real format, refusing anything that is not a PDF or an
            # image; an absent header is not treated as an unsupported file.
            action = "DOWNLOAD"
            reason = None
        elif mime in _UNSUPPORTED_GOOGLE:
            action = "UNSUPPORTED"
            reason = f"{mime} cannot be marked: {_UNSUPPORTED_GOOGLE[mime]}."
        elif mime.startswith("application/vnd.google-apps"):
            action = "UNSUPPORTED"
            reason = f"Google Workspace type {mime!r} has no safe export to a PDF."
        else:
            action = "UNSUPPORTED"
            reason = f"{mime or 'an unknown type'} is not supported (supported: PDF, PNG, JPEG)."

        classified.append(
            ClassifiedAttachment(
                position=position,
                kind="DRIVE_FILE",
                title=title,
                google_file_id=str(file_id),
                declared_mime=mime or None,
                action=action,
                reason=reason,
            )
        )
    return classified


# -- inspection ------------------------------------------------------------


class AttachmentRejected(Exception):
    """The bytes cannot be inspected; ``code`` and ``message`` are actionable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PageFinding:
    page_index: int
    width: int
    height: int
    text_chars: int
    ink_ratio: float
    blank: bool


@dataclass(frozen=True, slots=True)
class Inspection:
    mime_type: str
    size_bytes: int
    page_count: int
    readable: bool
    pages: list[PageFinding]
    text_excerpt: str
    has_text: bool
    blank_pages: list[int]
    issues: list[dict[str, str]] = field(default_factory=list)

    def as_findings(self) -> dict[str, Any]:
        """The JSON stored on the cache row and the attachment."""

        return {
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "page_count": self.page_count,
            "readable": self.readable,
            "has_text": self.has_text,
            "blank_pages": self.blank_pages,
            "text_excerpt": self.text_excerpt,
            "issues": self.issues,
            "pages": [
                {
                    "page_index": page.page_index,
                    "width": page.width,
                    "height": page.height,
                    "text_chars": page.text_chars,
                    "ink_ratio": round(page.ink_ratio, 5),
                    "blank": page.blank,
                }
                for page in self.pages
            ],
        }


def _issue(code: str, message: str, severity: str = "WARNING") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


def _ink_ratio(gray: np.ndarray) -> float:
    if gray.size == 0:
        return 0.0
    return float(np.mean(gray < 245.0))


def _pdf_inspection(data: bytes) -> tuple[list[PageFinding], list[dict[str, str]], str]:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError, ValueError) as error:
        raise AttachmentRejected("CORRUPT_PDF", "The PDF could not be opened.") from error

    pages: list[PageFinding] = []
    issues: list[dict[str, str]] = []
    texts: list[str] = []
    try:
        if document.needs_pass:
            raise AttachmentRejected("PDF_ENCRYPTED", "The PDF is password-protected.")
        count = document.page_count
        if count < 1:
            raise AttachmentRejected("EMPTY_DOCUMENT", "The PDF has no pages.")
        for index, page in enumerate(document, start=1):
            try:
                text = page.get_text("text") or ""
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(1, 1),
                    colorspace=pymupdf.csGRAY,
                    alpha=False,
                )
                gray = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height, pixmap.width
                )
            except (RuntimeError, ValueError) as error:
                raise AttachmentRejected(
                    "CORRUPT_PDF", f"Page {index} of the PDF could not be read."
                ) from error
            pages.append(
                PageFinding(
                    page_index=index,
                    width=pixmap.width,
                    height=pixmap.height,
                    text_chars=len(text.strip()),
                    ink_ratio=_ink_ratio(gray),
                    blank=_ink_ratio(gray) < 0.001 and not text.strip(),
                )
            )
            texts.append(text)
    finally:
        document.close()
    return pages, issues, "\n".join(texts)


def _image_inspection(data: bytes) -> tuple[PageFinding, str, str]:
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.verify()
        with Image.open(io.BytesIO(data)) as source:
            oriented = ImageOps.exif_transpose(source)
            width, height = oriented.size
            gray = np.asarray(oriented.convert("L"), dtype=np.float32)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise AttachmentRejected("CORRUPT_IMAGE", "The image could not be decoded.") from error
    page = PageFinding(
        page_index=1,
        width=width,
        height=height,
        text_chars=0,
        ink_ratio=_ink_ratio(gray),
        blank=_ink_ratio(gray) < 0.001,
    )
    return page, "", ""


def _detect_mime(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return PDF_MIME
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG_MIME
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG_MIME
    raise AttachmentRejected(
        "UNSUPPORTED_TYPE",
        "Only PDF, PNG and JPEG documents are accepted; the file signature was not recognised.",
    )


def inspect_bytes(
    data: bytes, *, settings: IngestionSettings, max_pages: int | None = None
) -> Inspection:
    """Validate and inspect one attachment without trusting its name or type."""

    if not data:
        raise AttachmentRejected("EMPTY_FILE", "The attachment is empty.")
    mime = _detect_mime(data)
    issues: list[dict[str, str]] = []
    maximum = max_pages if max_pages is not None else settings.max_pages

    if mime == PDF_MIME:
        pages, pdf_issues, text = _pdf_inspection(data)
        issues.extend(pdf_issues)
        count = len(pages)
        if count > maximum:
            raise AttachmentRejected(
                "TOO_MANY_PAGES",
                f"The PDF has {count} pages; the limit is {maximum}.",
            )
    else:
        page, text, _ = _image_inspection(data)
        pages = [page]
        count = 1
        if page.width * page.height > settings.max_image_pixels:
            raise AttachmentRejected(
                "IMAGE_TOO_LARGE",
                f"The image is {page.width}x{page.height}; the pixel limit is "
                f"{settings.max_image_pixels}.",
            )

    blank_pages = [page.page_index for page in pages if page.blank]
    non_blank = [page for page in pages if not page.blank]
    text_excerpt = text.strip()[:4000]

    narrow = [page.page_index for page in pages if page.width < settings.unreadable_width_px]
    if narrow:
        issues.append(
            _issue(
                "LOW_RESOLUTION",
                "Page(s) "
                + ", ".join(str(index) for index in narrow)
                + " are too narrow to read reliably.",
                "ERROR",
            )
        )
    if blank_pages and len(blank_pages) == len(pages):
        issues.append(_issue("BLANK_DOCUMENT", "Every page is blank or nearly blank.", "ERROR"))
    elif blank_pages:
        issues.append(
            _issue(
                "BLANK_PAGES",
                "Page(s) "
                + ", ".join(str(index) for index in blank_pages)
                + " are blank or nearly blank.",
            )
        )
    if mime == PDF_MIME and not text_excerpt:
        issues.append(
            _issue(
                "NO_TEXT_LAYER",
                "The PDF has no embedded text, so it is probably a scan or a "
                "photograph of handwritten work.",
                "INFO",
            )
        )
    if mime in IMAGE_MIMES:
        issues.append(
            _issue(
                "NO_TEXT_LAYER",
                "An image has no text layer; its content is read by the marking "
                "pipeline from the page itself.",
                "INFO",
            )
        )

    readable = bool(non_blank) and not narrow
    return Inspection(
        mime_type=mime,
        size_bytes=len(data),
        page_count=count,
        readable=readable,
        pages=pages,
        text_excerpt=text_excerpt,
        has_text=bool(text_excerpt),
        blank_pages=blank_pages,
        issues=issues,
    )


def inspection_from_findings(findings: dict[str, Any]) -> Inspection:
    """Rebuild a cached inspection without opening the file again."""

    pages = [
        PageFinding(
            page_index=int(raw.get("page_index", index + 1)),
            width=int(raw.get("width", 0)),
            height=int(raw.get("height", 0)),
            text_chars=int(raw.get("text_chars", 0)),
            ink_ratio=float(raw.get("ink_ratio", 0.0)),
            blank=bool(raw.get("blank", False)),
        )
        for index, raw in enumerate(findings.get("pages") or [])
    ]
    return Inspection(
        mime_type=str(findings.get("mime_type") or "application/octet-stream"),
        size_bytes=int(findings.get("size_bytes") or 0),
        page_count=int(findings.get("page_count") or 0),
        readable=bool(findings.get("readable")),
        pages=pages,
        text_excerpt=str(findings.get("text_excerpt") or ""),
        has_text=bool(findings.get("has_text")),
        blank_pages=[int(value) for value in findings.get("blank_pages") or []],
        issues=list(findings.get("issues") or []),
    )


def assemble_images_to_pdf(images: list[bytes]) -> bytes:
    """Combine ordered page images into one PDF, preserving their order.

    A submission made of several photos is one piece of work.  Assembling it
    locally means the correction pipeline sees one document, in the order Google
    reported, instead of several unrelated jobs.
    """

    if not images:
        raise AttachmentRejected("NO_PAGES", "There are no images to assemble.")
    frames: list[Image.Image] = []
    try:
        for data in images:
            with Image.open(io.BytesIO(data)) as source:
                frames.append(ImageOps.exif_transpose(source).convert("RGB"))
        buffer = io.BytesIO()
        frames[0].save(
            buffer,
            format="PDF",
            save_all=True,
            append_images=frames[1:],
            resolution=150.0,
        )
        return buffer.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise AttachmentRejected(
            "CORRUPT_IMAGE", "An attached image could not be combined into a PDF."
        ) from error
    finally:
        for frame in frames:
            frame.close()


def safe_filename(title: str | None, *, suffix: str) -> str:
    """A storage-safe name derived from a title that is never trusted."""

    raw = (title or "").strip()
    cleaned = "".join(
        character
        for character in raw
        if character.isalnum() or character in {" ", "-", "_", ".", "(", ")"}
    )
    cleaned = " ".join(cleaned.split())[:120]
    if cleaned and not cleaned.lower().endswith(suffix):
        cleaned = f"{cleaned}{suffix}"
    return cleaned or f"classroom-submission{suffix}"
