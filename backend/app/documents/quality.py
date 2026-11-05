"""Deterministic page-quality assessment.

The assessment is deliberately conservative and explainable: every flag carries
a code and a sentence a teacher can act on.  It is not a substitute for reading
the page, and it never drops a page.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from ..core.config import IngestionSettings
from .types import QualityStatus, reason


def _reasons_for(
    *,
    width: int,
    height: int,
    rotation: int,
    ink_ratio: float,
    contrast: float,
    edge_energy: float,
    settings: IngestionSettings,
) -> tuple[QualityStatus, list[dict[str, str]]]:
    reasons: list[dict[str, str]] = []
    status = QualityStatus.READABLE

    if width < settings.unreadable_width_px:
        reasons.append(
            reason(
                "LOW_RESOLUTION",
                f"The rendered page is only {width}px wide; text may be unreadable.",
                "ERROR",
            )
        )
        status = QualityStatus.UNREADABLE
    elif width < settings.min_page_width_px:
        reasons.append(
            reason(
                "LOW_RESOLUTION",
                f"The rendered page is {width}px wide, below the preferred "
                f"{settings.min_page_width_px}px.",
            )
        )
        if status is QualityStatus.READABLE:
            status = QualityStatus.LOW_QUALITY

    if rotation % 360 in {90, 180, 270}:
        reasons.append(
            reason(
                "PAGE_ROTATED",
                f"The page is rotated {rotation % 360} degrees; the reader may need to "
                "rotate it before marking.",
            )
        )
        status = QualityStatus.ROTATED

    if ink_ratio < settings.blank_ink_ratio:
        reasons.append(reason("BLANK_PAGE", "The page contains almost no visible ink.", "ERROR"))
        return QualityStatus.EMPTY, reasons

    if ink_ratio < settings.low_ink_ratio:
        reasons.append(
            reason(
                "LOW_INK_COVERAGE",
                f"Only {ink_ratio:.2%} of the page contains ink; "
                "part of the answer may be missing.",
            )
        )
        if status is QualityStatus.READABLE:
            status = QualityStatus.LOW_QUALITY

    if contrast < settings.low_contrast_std:
        reasons.append(
            reason(
                "LOW_CONTRAST",
                f"Page contrast is low (grayscale spread {contrast:.1f}); faint writing may "
                "be missed.",
            )
        )
        if status is QualityStatus.READABLE:
            status = QualityStatus.LOW_QUALITY

    if edge_energy < settings.low_edge_energy:
        reasons.append(
            reason(
                "LOW_EDGE_DETAIL",
                f"The page has little edge detail ({edge_energy:.2f}); strokes may be blurred.",
            )
        )
        if status is QualityStatus.READABLE:
            status = QualityStatus.LOW_QUALITY

    return status, reasons


def assess_png(
    png: bytes, *, rotation_degrees: int, settings: IngestionSettings
) -> tuple[QualityStatus, list[dict[str, str]], int, int]:
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        width, height = image.size
        gray = np.asarray(image.convert("L"), dtype=np.float32)
    if gray.size == 0:
        return (
            QualityStatus.EMPTY,
            [reason("BLANK_PAGE", "The page image is empty.", "ERROR")],
            width,
            height,
        )
    ink_ratio = float(np.mean(gray < 245.0))
    contrast = float(np.std(gray))
    edge_energy = float(np.abs(np.diff(gray, axis=0)).mean() + np.abs(np.diff(gray, axis=1)).mean())
    status, reasons = _reasons_for(
        width=width,
        height=height,
        rotation=rotation_degrees,
        ink_ratio=ink_ratio,
        contrast=contrast,
        edge_energy=edge_energy,
        settings=settings,
    )
    return status, reasons, width, height


def average_hash(png: bytes) -> int:
    """A small perceptual hash used only for duplicate-page detection."""
    with Image.open(io.BytesIO(png)) as image:
        resized = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
        values = np.asarray(resized, dtype=np.float32).flatten()
    mean = float(values.mean())
    bits = 0
    for value in values:
        bits = (bits << 1) | (1 if value >= mean else 0)
    return bits


def hamming(first: int, second: int) -> int:
    return (first ^ second).bit_count()
