"""Render validated PDFs/images into page PNGs and assess every page."""

from __future__ import annotations

import io
from dataclasses import replace

import pymupdf
from PIL import Image, ImageOps

from ..core.config import Settings
from ..core.ids import sha256_hex
from .ordering import assess_ordering, extracted_page_number
from .quality import assess_png, average_hash, hamming
from .types import (
    DocumentFormat,
    DocumentRejected,
    OrderingStatus,
    PageRender,
    RenderedDocument,
    reason,
)
from .validation import ValidatedUpload


def _pdf_pages(data: bytes, settings: Settings) -> list[PageRender]:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError, ValueError) as error:
        raise DocumentRejected(
            "CORRUPT_PDF",
            "The PDF could not be rendered.",
            [reason("CORRUPT_PDF", "The PDF could not be rendered.", "ERROR")],
        ) from error
    pages: list[PageRender] = []
    try:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text")
            pixmap = page.get_pixmap(
                dpi=settings.ingestion.render_dpi,
                colorspace=pymupdf.csRGB,
                alpha=False,
            )
            png = pixmap.tobytes("png")
            rotation = int(page.rotation) % 360
            quality, quality_reasons, width, height = assess_png(
                png, rotation_degrees=rotation, settings=settings.ingestion
            )
            pages.append(
                PageRender(
                    page_index=index,
                    png=png,
                    width=width,
                    height=height,
                    rotation_degrees=rotation,
                    text=text,
                    quality_status=quality,
                    quality_reasons=quality_reasons,
                    checksum=sha256_hex(png),
                    printed_page_number=extracted_page_number(text),
                )
            )
    finally:
        document.close()
    return pages


def _image_page(data: bytes, upload: ValidatedUpload, settings: Settings) -> list[PageRender]:
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            png = buffer.getvalue()
            width, height = image.size
    except (OSError, ValueError) as error:
        raise DocumentRejected(
            "CORRUPT_IMAGE",
            "The image could not be rendered.",
            [reason("CORRUPT_IMAGE", "The image could not be rendered.", "ERROR")],
        ) from error
    quality, quality_reasons, width, height = assess_png(
        png, rotation_degrees=0, settings=settings.ingestion
    )
    del upload
    return [
        PageRender(
            page_index=1,
            png=png,
            width=width,
            height=height,
            rotation_degrees=0,
            text="",
            quality_status=quality,
            quality_reasons=quality_reasons,
            checksum=sha256_hex(png),
            printed_page_number=None,
        )
    ]


def _mark_duplicates(pages: list[PageRender], settings: Settings) -> list[PageRender]:
    hashes = [average_hash(page.png) for page in pages]
    duplicate_of: dict[int, int] = {}
    for index, digest in enumerate(hashes):
        for earlier in range(index):
            first_text = pages[earlier].text.strip()
            second_text = pages[index].text.strip()
            if first_text and second_text and first_text != second_text:
                # Different text layers are different pages even when the page
                # template makes their downsampled images look alike.
                continue
            if hamming(digest, hashes[earlier]) <= settings.ingestion.duplicate_hash_distance:
                duplicate_of[index] = earlier
                break
    updated: list[PageRender] = []
    for index, page in enumerate(pages):
        earlier = duplicate_of.get(index)
        if earlier is None:
            updated.append(page)
            continue
        updated.append(
            replace(
                page,
                duplicate_of_index=earlier + 1,
                quality_reasons=[
                    *page.quality_reasons,
                    reason(
                        "DUPLICATE_PAGE",
                        f"This page looks the same as page {earlier + 1}; "
                        "it may have been scanned twice.",
                    ),
                ],
            )
        )
    return updated


def render_document(data: bytes, upload: ValidatedUpload, settings: Settings) -> RenderedDocument:
    if upload.format is DocumentFormat.PDF:
        pages = _pdf_pages(data, settings)
    else:
        pages = _image_page(data, upload, settings)
    pages = _mark_duplicates(pages, settings)
    ordering_status, ordering_reasons, page_ordering_reasons = assess_ordering(
        pages, settings.ingestion
    )
    duplicate_pages = [page.page_index for page in pages if page.duplicate_of_index is not None]
    if duplicate_pages:
        ordering_reasons.append(
            reason(
                "DUPLICATE_PAGE",
                "Duplicate-looking pages were found on page(s): "
                + ", ".join(str(index) for index in duplicate_pages)
                + ".",
            )
        )
        if ordering_status is not OrderingStatus.ORDER_SUSPECT:
            ordering_status = OrderingStatus.ORDER_SUSPECT
    return RenderedDocument(
        pages=pages,
        ordering_status=ordering_status,
        ordering_reasons=ordering_reasons,
        page_ordering_reasons=page_ordering_reasons,
    )
