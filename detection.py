from __future__ import annotations

import asyncio
import math
import re
import threading
import unicodedata

import cv2
import numpy as np
from PIL import Image, ImageOps
from overlay_ocr import recognize_overlay
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import (
    BitmapAlphaMode,
    BitmapPixelFormat,
    SoftwareBitmap,
)
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import Buffer


OCR_LANGUAGE = "zh-Hant-TW"
_ocr_thread_local = threading.local()


def find_template(screen: Image.Image, template: Image.Image) -> tuple[float, tuple[int, int]]:
    source = cv2.cvtColor(np.asarray(screen), cv2.COLOR_RGB2BGR)
    needle = cv2.cvtColor(np.asarray(template), cv2.COLOR_RGB2BGR)
    if needle.shape[0] > source.shape[0] or needle.shape[1] > source.shape[1]:
        return 0.0, (0, 0)
    if float(np.max(np.std(needle, axis=(0, 1)))) < 1e-6:
        result = cv2.matchTemplate(source, needle, cv2.TM_SQDIFF_NORMED)
        min_value, _max_value, min_location, _max_location = cv2.minMaxLoc(result)
        return max(0.0, 1.0 - float(min_value)), min_location
    result = cv2.matchTemplate(source, needle, cv2.TM_CCOEFF_NORMED)
    _min_value, max_value, _min_location, max_location = cv2.minMaxLoc(result)
    if np.isnan(max_value):
        result = cv2.matchTemplate(source, needle, cv2.TM_SQDIFF_NORMED)
        min_value, _max_value, min_location, _max_location = cv2.minMaxLoc(result)
        return max(0.0, 1.0 - float(min_value)), min_location
    return max(0.0, min(1.0, float(max_value))), max_location


def count_color(image: Image.Image, rgb: tuple[int, int, int], tolerance: int) -> int:
    pixels = np.asarray(image, dtype=np.int16)
    target = np.asarray(rgb, dtype=np.int16)
    return int(np.all(np.abs(pixels - target) <= tolerance, axis=2).sum())


def normalize_ocr_text(value: str) -> str:
    """Normalize OCR output for stable, color-independent keyword matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if not character.isspace())


def _ocr_candidate_score(needle: str, candidate: str) -> float:
    """Penalize each insertion, deletion and substitution, not scattered matches."""
    previous = list(range(len(candidate) + 1))
    for row, character in enumerate(needle, 1):
        current = [row]
        for column, other in enumerate(candidate, 1):
            current.append(min(
                current[-1] + 1, previous[column] + 1,
                previous[column - 1] + (character != other),
            ))
        previous = current
    score = 1.0 - previous[-1] / max(len(needle), len(candidate))
    # A tile boundary can clip a genuine word. Preserve a substantial intact
    # prefix/suffix, while requiring more than a few coincidental letters.
    if (
        len(candidate) >= max(4, math.ceil(len(needle) * 0.6))
        and (needle.startswith(candidate) or needle.endswith(candidate))
    ):
        score = max(score, 2 * len(candidate) / (len(needle) + len(candidate)))
    return score


def ocr_text_similarity(target: str, recognized: str) -> float:
    """Return a token-aware fuzzy-match score for OCR text."""
    needle = normalize_ocr_text(target)
    haystack = normalize_ocr_text(recognized)
    if not needle or not haystack:
        return 0.0
    if needle in haystack:
        return 1.0

    # Do not slide across the whitespace-stripped full OCR result. That allowed
    # unrelated letters from several words to combine into a false 70% match.
    tokens = [
        normalize_ocr_text(token)
        for token in re.findall(r"[^\W_]+", recognized, flags=re.UNICODE)
    ]
    tokens = [token for token in tokens if token]
    if not tokens:
        return 0.0

    target_token_count = max(1, len(re.findall(r"[^\W_]+", target, flags=re.UNICODE)))
    candidates: set[str] = set(tokens)
    max_join = min(len(tokens), target_token_count)
    for count in range(2, max_join + 1):
        for start in range(len(tokens) - count + 1):
            candidates.add("".join(tokens[start:start + count]))

    best = 0.0
    for candidate in candidates:
        if needle in candidate:
            return 1.0
        if len(candidate) > len(needle) + 2:
            minimum = max(1, len(needle) - 1)
            maximum = min(len(candidate), len(needle) + 1)
            for length in range(minimum, maximum + 1):
                for start in range(len(candidate) - length + 1):
                    segment = candidate[start:start + length]
                    best = max(best, _ocr_candidate_score(needle, segment))
        else:
            best = max(best, _ocr_candidate_score(needle, candidate))
    return best


def recognize_text(image: Image.Image) -> str:
    """Read Traditional Chinese and Latin text with the Windows OCR engine."""
    engine = getattr(_ocr_thread_local, "engine", None)
    if engine is None:
        available = {
            language.language_tag for language in OcrEngine.available_recognizer_languages
        }
        if OCR_LANGUAGE not in available:
            raise RuntimeError("Windows 尚未安裝繁體中文 OCR 語言（zh-Hant-TW）。")
        engine = OcrEngine.try_create_from_language(Language(OCR_LANGUAGE))
        if engine is None:
            raise RuntimeError("無法啟動 Windows 繁體中文 OCR 引擎。")
        _ocr_thread_local.engine = engine

    grayscale = ImageOps.autocontrast(ImageOps.grayscale(image))
    max_dimension = int(OcrEngine.max_image_dimension)
    if max(grayscale.size) <= max_dimension // 2:
        grayscale = grayscale.resize(
            (grayscale.width * 2, grayscale.height * 2),
            Image.Resampling.LANCZOS,
        )
    elif max(grayscale.size) > max_dimension:
        scale = max_dimension / max(grayscale.size)
        grayscale = grayscale.resize(
            (
                max(1, round(grayscale.width * scale)),
                max(1, round(grayscale.height * scale)),
            ),
            Image.Resampling.LANCZOS,
        )
    pixels = grayscale.tobytes()
    buffer = Buffer(len(pixels))
    buffer.length = len(pixels)
    memoryview(buffer)[:] = pixels
    bitmap = SoftwareBitmap(
        BitmapPixelFormat.GRAY8,
        grayscale.width,
        grayscale.height,
        BitmapAlphaMode.IGNORE,
    )
    bitmap.copy_from_buffer(buffer)

    async def run_ocr() -> str:
        result = await engine.recognize_async(bitmap)
        return result.text

    try:
        return asyncio.run(run_ocr())
    finally:
        bitmap.close()


def recognize_text_for_target(image: Image.Image, target: str) -> str:
    """OCR the whole window, then overlapping enlarged tiles for one target."""
    candidates = recognize_text_candidates(image, [target])
    return max(candidates, key=lambda text: ocr_text_similarity(target, text))


def recognize_text_candidates(image: Image.Image, targets: list[str]) -> list[str]:
    """OCR one frame once and return text candidates shared by every target."""
    overlay_candidates = recognize_overlay(image)
    if targets and all(
        any(ocr_text_similarity(target, text) == 1.0 for text in overlay_candidates)
        for target in targets
    ):
        return overlay_candidates
    full_text = recognize_text(image)
    candidates = overlay_candidates + [full_text]
    unresolved = {
        target for target in targets
        if target and ocr_text_similarity(target, full_text) < 1.0
    }
    if not unresolved or image.width <= 320 or image.height <= 240:
        return candidates

    tile_width = min(320, image.width)
    tile_height = min(240, image.height)
    x_steps = min(6, max(1, math.ceil(image.width / tile_width) + 1))
    y_steps = min(4, max(1, math.ceil(image.height / tile_height)))
    x_positions = [
        round(index * (image.width - tile_width) / max(1, x_steps - 1))
        for index in range(x_steps)
    ]
    y_positions = [
        round(index * (image.height - tile_height) / max(1, y_steps - 1))
        for index in range(y_steps)
    ]
    positions = [(left, top) for top in y_positions for left in x_positions]
    cached = getattr(_ocr_thread_local, "last_hit_tile", None)
    if cached in positions:
        positions.remove(cached)
        positions.insert(0, cached)
    scored_tiles = []
    for left, top in positions:
            tile = image.crop((left, top, left + tile_width, top + tile_height))
            tile_text = recognize_text(tile)
            candidates.append(tile_text)
            score = max((ocr_text_similarity(target, tile_text) for target in targets), default=0.0)
            scored_tiles.append((score, left, top))
            unresolved = {
                target for target in unresolved
                if ocr_text_similarity(target, tile_text) < 1.0
            }
            if not unresolved:
                _ocr_thread_local.last_hit_tile = (left, top)
                return candidates
    # Animated overlays can tilt the text. Deskew only the strongest regions,
    # rather than multiplying OCR work for every tile in every frame.
    for _score, left, top in sorted(scored_tiles, reverse=True)[:2]:
        tile = image.crop((left, top, left + tile_width, top + tile_height))
        for angle in (20, -20):
            rotated = tile.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
            tile_text = recognize_text(rotated)
            candidates.append(tile_text)
            if any(ocr_text_similarity(target, tile_text) >= 0.85 for target in targets):
                _ocr_thread_local.last_hit_tile = (left, top)
            unresolved = {
                target for target in unresolved
                if ocr_text_similarity(target, tile_text) < 1.0
            }
            if not unresolved:
                return candidates
    return candidates
