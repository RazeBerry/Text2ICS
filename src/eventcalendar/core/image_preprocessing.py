"""Image preprocessing for faster uploads and more reliable extraction.

This module is intentionally dependency-light at import time; Pillow is imported
only inside preprocessing functions.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from eventcalendar.config.constants import (
    IMAGE_FORMAT_MIME_TYPES,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    SUPPORTED_PIL_FORMATS,
)
from eventcalendar.exceptions.errors import ImageProcessingError

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
DEFAULT_MAX_BYTES = max(256_000, min(_get_int_env("EVENTCALENDAR_IMAGE_MAX_BYTES", 1_400_000), 25_000_000))
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


@dataclass(frozen=True)
class ValidatedImage:
    """Verified metadata for an accepted image file."""

    format: str
    mime_type: str
    width: int
    height: int
    size_bytes: int


def validate_image_file(
    source_path: str,
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> ValidatedImage:
    """Verify file size, decoder format, dimensions, and image integrity."""
    source = Path(source_path)
    try:
        if not source.is_file():
            raise ValueError("file does not exist or is not a regular file")
        size_bytes = source.stat().st_size
        if size_bytes <= 0:
            raise ValueError("file is empty")
        if size_bytes > max_bytes:
            raise ValueError(f"file exceeds the {max_bytes // (1024 * 1024)} MB limit")

        from PIL import Image

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source, formats=sorted(SUPPORTED_PIL_FORMATS)) as image:
                image_format = str(image.format or "").upper()
                if image_format not in SUPPORTED_PIL_FORMATS:
                    raise ValueError(f"unsupported image format {image_format or 'unknown'}")
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    raise ValueError(f"image exceeds the {max_pixels:,}-pixel limit")
                image.verify()
    except ImageProcessingError:
        raise
    except Exception as exc:
        raise ImageProcessingError(str(source), str(exc)) from exc

    return ValidatedImage(
        format=image_format,
        mime_type=IMAGE_FORMAT_MIME_TYPES[image_format],
        width=width,
        height=height,
        size_bytes=size_bytes,
    )


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


def _save_with_byte_budget(
    image,
    out_path: str,
    out_format: str,
    save_kwargs: dict,
    max_output_bytes: int,
) -> int:
    """Encode, then reduce dimensions/quality until the output is truly bounded."""
    current = image
    kwargs = dict(save_kwargs)
    try:
        for _attempt in range(6):
            current.save(out_path, format=out_format, **kwargs)
            output_size = Path(out_path).stat().st_size
            if output_size <= max_output_bytes:
                return output_size

            width, height = current.size
            if min(width, height) <= 128:
                break
            scale = min(
                0.90,
                max(0.50, math.sqrt(max_output_bytes / output_size) * 0.92),
            )
            resized = current.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                resample=2,
            )
            # Integer 2 is Pillow's stable BILINEAR value and avoids importing
            # Pillow at module import time solely for this private helper.
            if current is not image:
                current.close()
            current = resized
            if out_format == "JPEG" and "quality" in kwargs:
                kwargs["quality"] = max(65, int(kwargs["quality"]) - 6)
    finally:
        if current is not image:
            current.close()

    raise ValueError(f"processed image could not be reduced below {max_output_bytes} bytes")


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
    validated = validate_image_file(source_path)

    if os.environ.get("EVENTCALENDAR_DISABLE_IMAGE_PREPROCESSING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return PreprocessedImage(source_path, validated.mime_type)

    source = Path(source_path)
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise ImageProcessingError(source_path, "Pillow is not installed") from exc

    src_mime = validated.mime_type

    try:
        source_size = validated.size_bytes

        with Image.open(source, formats=sorted(SUPPORTED_PIL_FORMATS)) as image:
            if getattr(image, "is_animated", False):
                image.seek(0)

            original_w, original_h = image.size
            original_max_edge = max(original_w, original_h)
            resized = original_max_edge > max_edge_px

            # If the image is already within our size bounds and not huge on disk,
            # don't decode or touch it (avoids unnecessary work and quality loss).
            if not resized and source_size and source_size <= DEFAULT_MAX_BYTES:
                return PreprocessedImage(source_path, validated.mime_type)

            # Pillow's non-in-place exif_transpose() returns a full image copy even
            # when no orientation transform is required.  An additional .copy()
            # here previously kept multiple source-sized pixel buffers alive until
            # after thumbnailing.  The supported Pillow version can normalize EXIF
            # orientation in place, so resize the opened image directly and only
            # allocate a converted image later when the output codec requires it.
            ImageOps.exif_transpose(image, in_place=True)

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
            preserve_png = has_alpha or src_mime == "image/png" or validated.format == "PNG"

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
                _save_with_byte_budget(
                    image,
                    out_path,
                    out_format,
                    save_kwargs,
                    DEFAULT_MAX_BYTES,
                )
            except Exception:
                Path(out_path).unlink(missing_ok=True)
                raise

    except Exception as exc:
        logger.warning("Image preprocessing failed for %s: %s", Path(source_path).name, exc)
        raise ImageProcessingError(source_path, str(exc)) from exc

    try:
        output_size = Path(out_path).stat().st_size
        if output_size > DEFAULT_MAX_BYTES:
            raise ValueError(f"processed image exceeds {DEFAULT_MAX_BYTES} bytes")
        validate_image_file(out_path)
    except Exception as exc:
        Path(out_path).unlink(missing_ok=True)
        raise ImageProcessingError(source_path, f"processed image failed validation: {exc}") from exc

    if not resized and output_size >= source_size:
        Path(out_path).unlink(missing_ok=True)
        return PreprocessedImage(source_path, validated.mime_type)

    return PreprocessedImage(out_path, out_mime, cleanup_paths=(out_path,))
