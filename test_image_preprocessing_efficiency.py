"""Focused regressions for image preprocessing data movement and parity."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, ImageOps

from eventcalendar.core.image_preprocessing import DEFAULT_MAX_BYTES, preprocess_image_for_upload


def _pattern_image(width: int = 12, height: int = 8) -> Image.Image:
    """Create an asymmetric image so every EXIF orientation is observable."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = ((x * 19) % 256, (y * 31) % 256, ((x + y) * 17) % 256)
    return image


@pytest.mark.parametrize("orientation", range(1, 9))
def test_preprocessing_preserves_exif_orientation_output(
    tmp_path: Path,
    orientation: int,
) -> None:
    """In-place orientation must match Pillow's canonical transformed pixels."""
    source = tmp_path / f"orientation-{orientation}.png"
    image = _pattern_image()
    exif = Image.Exif()
    exif[274] = orientation
    image.save(source, format="PNG", exif=exif)

    with Image.open(source) as opened:
        expected = ImageOps.exif_transpose(opened)
        expected.thumbnail((6, 6), resample=Image.Resampling.BICUBIC)
        expected_size = expected.size
        expected_pixels = expected.tobytes()

    result = preprocess_image_for_upload(
        str(source),
        "image/png",
        max_edge_px=6,
        resample="bicubic",
    )
    try:
        assert result.mime_type == "image/png"
        assert result.path != str(source)
        with Image.open(result.path) as processed:
            assert processed.size == expected_size
            assert processed.convert("RGB").tobytes() == expected_pixels
            assert processed.getexif().get(274) is None
    finally:
        result.cleanup()


def test_preprocessing_uses_first_animated_frame(tmp_path: Path) -> None:
    """Animated inputs retain the established first-frame-only behavior."""
    source = tmp_path / "animated.gif"
    first = Image.new("RGB", (20, 12), "red")
    second = Image.new("RGB", (20, 12), "blue")
    first.save(source, save_all=True, append_images=[second], duration=100, loop=0)

    result = preprocess_image_for_upload(str(source), "image/gif", max_edge_px=10)
    try:
        assert result.mime_type == "image/jpeg"
        with Image.open(result.path) as processed:
            assert processed.size == (10, 6)
            red, green, blue = processed.convert("RGB").getpixel((5, 3))
            assert red > 200
            assert green < 40
            assert blue < 40
    finally:
        result.cleanup()


def test_preprocessing_preserves_png_alpha(tmp_path: Path) -> None:
    """Avoiding source copies must not change alpha/PNG output policy."""
    source = tmp_path / "alpha.png"
    Image.new("RGBA", (20, 10), (10, 20, 30, 77)).save(source)

    result = preprocess_image_for_upload(str(source), "image/png", max_edge_px=10)
    try:
        assert result.mime_type == "image/png"
        with Image.open(result.path) as processed:
            assert processed.size == (10, 5)
            assert processed.mode == "RGBA"
            assert processed.getpixel((5, 2))[3] == 77
    finally:
        result.cleanup()


def test_resize_does_not_copy_full_resolution_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard the memory shape without a machine-dependent RSS/timing limit."""
    source = tmp_path / "large.jpg"
    source_size = (1200, 800)
    Image.new("RGB", source_size, (80, 120, 160)).save(source, quality=95)

    copied_sizes: list[tuple[int, int]] = []
    original_copy = Image.Image.copy

    def tracking_copy(image: Image.Image) -> Image.Image:
        copied_sizes.append(image.size)
        return original_copy(image)

    monkeypatch.setattr(Image.Image, "copy", tracking_copy)

    result = preprocess_image_for_upload(str(source), "image/jpeg", max_edge_px=256)
    try:
        assert source_size not in copied_sizes
        with Image.open(result.path) as processed:
            assert processed.size == (256, 171)
    finally:
        result.cleanup()


def test_high_entropy_png_is_actually_bounded_for_inline_submission(tmp_path: Path) -> None:
    """The tuning threshold is an output contract, not merely a fast-path hint."""
    source = tmp_path / "high-entropy.png"
    Image.frombytes("RGB", (1024, 1024), os.urandom(3 * 1024 * 1024)).save(source)
    assert source.stat().st_size > DEFAULT_MAX_BYTES

    result = preprocess_image_for_upload(str(source), "image/png")
    try:
        assert Path(result.path).stat().st_size <= DEFAULT_MAX_BYTES
    finally:
        result.cleanup()
