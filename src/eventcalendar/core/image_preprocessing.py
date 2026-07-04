"""Image preprocessing for faster uploads and more reliable extraction.

This module is intentionally dependency-light at import time; Pillow is imported
only inside preprocessing functions.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _get_int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_resample_name(default: str = "bicubic") -> str:
    value = os.environ.get("EVENTCALENDAR_IMAGE_RESAMPLE", default)
    return str(value).strip().lower()


# Conservative defaults: reduce huge images without hurting flyer readability.
DEFAULT_MAX_EDGE_PX = max(512, min(_get_int_env("EVENTCALENDAR_IMAGE_MAX_EDGE_PX", 2560), 8192))
DEFAULT_JPEG_QUALITY = max(50, min(_get_int_env("EVENTCALENDAR_IMAGE_JPEG_QUALITY", 88), 95))
DEFAULT_MAX_BYTES = max(256_000, min(_get_int_env("EVENTCALENDAR_IMAGE_MAX_BYTES", 2_500_000), 25_000_000))
DEFAULT_RESAMPLE = _get_resample_name("auto")
DEFAULT_JPEG_OPTIMIZE = _get_bool_env("EVENTCALENDAR_IMAGE_JPEG_OPTIMIZE", False)
DEFAULT_JPEG_PROGRESSIVE = _get_bool_env("EVENTCALENDAR_IMAGE_JPEG_PROGRESSIVE", False)


@dataclass(frozen=True)
class PreprocessedImage:
    """Result of preprocessing an image for upload."""

    path: str
    mime_type: Optional[str]
    cleanup_paths: Tuple[str, ...] = ()

    def cleanup(self) -> None:
        for cleanup_path in self.cleanup_paths:
            try:
                Path(cleanup_path).unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("Failed to delete temp image %s: %s", cleanup_path, exc)


def _choose_resample(
    requested: str,
    original_max_edge: int,
    max_edge_px: int,
    resampling,
):
    """Choose resize filter with adaptive fast path for very large downscales."""
    options = {
        "lanczos": resampling.LANCZOS,
        "bicubic": resampling.BICUBIC,
        "bilinear": resampling.BILINEAR,
    }
    name = str(requested).strip().lower()
    if name in options:
        return options[name]

    # "auto": for large downscales use BILINEAR for speed, else BICUBIC.
    if max_edge_px <= 0:
        return resampling.BICUBIC
    ratio = original_max_edge / float(max_edge_px)
    if original_max_edge >= 3000 and ratio >= 1.4:
        return resampling.BILINEAR
    return resampling.BICUBIC


def preprocess_image_for_upload(
    source_path: str,
    mime_type: Optional[str] = None,
    *,
    max_edge_px: int = DEFAULT_MAX_EDGE_PX,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
    resample: str = DEFAULT_RESAMPLE,
    jpeg_optimize: bool = DEFAULT_JPEG_OPTIMIZE,
    jpeg_progressive: bool = DEFAULT_JPEG_PROGRESSIVE,
) -> PreprocessedImage:
    """Preprocess an image to reduce upload time and model latency.

    Strategy:
    - Fix orientation via EXIF transpose.
    - Downscale only if the largest edge exceeds max_edge_px.
    - Preserve PNG for PNG inputs/alpha; otherwise write JPEG.
    - If no downscale happened and the result isn't smaller, keep original.

    Args:
        source_path: Path to the source image file.
        mime_type: Original mime type (best-effort hint).
        max_edge_px: Maximum width/height of the output image.
        jpeg_quality: JPEG quality for lossy output.
        resample: Resize filter ("auto", "bicubic", "bilinear", "lanczos").
        jpeg_optimize: Whether to run JPEG entropy optimization.
        jpeg_progressive: Whether to emit progressive JPEGs.

    Returns:
        PreprocessedImage pointing to the path to upload, and cleanup paths.
    """
    if os.environ.get("EVENTCALENDAR_DISABLE_IMAGE_PREPROCESSING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return PreprocessedImage(source_path, mime_type)

    source = Path(source_path)
    if not source.exists():
        return PreprocessedImage(source_path, mime_type)

    try:
        from PIL import Image, ImageOps
    except ImportError:
        return PreprocessedImage(source_path, mime_type)

    src_mime = (mime_type or "").lower()
    src_ext = source.suffix.lower()

    try:
        try:
            source_size = source.stat().st_size
        except Exception:
            source_size = 0

        with Image.open(source) as image:
            if getattr(image, "is_animated", False):
                return PreprocessedImage(source_path, mime_type)

            image = ImageOps.exif_transpose(image)

            original_w, original_h = image.size
            original_max_edge = max(original_w, original_h)
            resized = original_max_edge > max_edge_px

            # If the image is already within our size bounds and not huge on disk,
            # don't touch it (avoids unnecessary recompression/quality loss).
            if not resized and source_size and source_size <= DEFAULT_MAX_BYTES:
                return PreprocessedImage(source_path, mime_type)

            if resized:
                resampling = getattr(Image, "Resampling", Image)
                selected_resample = _choose_resample(
                    requested=resample,
                    original_max_edge=original_max_edge,
                    max_edge_px=max_edge_px,
                    resampling=resampling,
                )
                image.thumbnail((max_edge_px, max_edge_px), resample=selected_resample)

            has_alpha = image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            )
            preserve_png = has_alpha or src_mime == "image/png" or src_ext == ".png" or image.format == "PNG"

            if preserve_png:
                out_format = "PNG"
                out_suffix = ".png"
                out_mime = "image/png"
                save_kwargs = {}
            else:
                out_format = "JPEG"
                out_suffix = ".jpg"
                out_mime = "image/jpeg"
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                save_kwargs = {
                    "quality": jpeg_quality,
                    "optimize": bool(jpeg_optimize),
                }
                if jpeg_progressive:
                    save_kwargs["progressive"] = True

            fd, out_path = tempfile.mkstemp(prefix="eventcalendar_", suffix=out_suffix)
            os.close(fd)

            try:
                image.save(out_path, format=out_format, **save_kwargs)
            except Exception:
                Path(out_path).unlink(missing_ok=True)
                raise

    except Exception as exc:
        logger.warning("Image preprocessing failed for %s: %s", source_path, exc)
        return PreprocessedImage(source_path, mime_type)

    try:
        output_size = Path(out_path).stat().st_size
    except Exception:
        Path(out_path).unlink(missing_ok=True)
        return PreprocessedImage(source_path, mime_type)

    if not resized and output_size >= source_size:
        Path(out_path).unlink(missing_ok=True)
        return PreprocessedImage(source_path, mime_type)

    return PreprocessedImage(out_path, out_mime, cleanup_paths=(out_path,))
