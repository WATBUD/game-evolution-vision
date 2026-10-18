from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import math
import threading
import unicodedata

import cv2
import numpy as np
from PIL import Image, ImageOps
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


def ocr_text_similarity(target: str, recognized: str) -> float:
    """Return the best partial fuzzy-match score for OCR text."""
    needle = normalize_ocr_text(target)
    haystack = normalize_ocr_text(recognized)
    if not needle or not haystack:
        return 0.0
    if needle in haystack:
        return 1.0
    best = SequenceMatcher(None, needle, haystack).ratio()
    if len(needle) <= 4:
        minimum = maximum = min(len(needle), len(haystack))
    else:
        minimum = max(1, len(needle) - 2)
        maximum = min(len(haystack), len(needle) + 2)
    for length in range(minimum, maximum + 1):
        for start in range(0, len(haystack) - length + 1):
            candidate = haystack[start:start + length]
            best = max(best, SequenceMatcher(None, needle, candidate).ratio())
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
    """OCR the whole window, then overlapping enlarged tiles for small text."""
    full_text = recognize_text(image)
    best_text = full_text
    best_score = ocr_text_similarity(target, full_text)
    if best_score >= 1.0 or image.width <= 320 or image.height <= 240:
        return best_text

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
    for top in y_positions:
        for left in x_positions:
            tile = image.crop((left, top, left + tile_width, top + tile_height))
            tile_text = recognize_text(tile)
            score = ocr_text_similarity(target, tile_text)
            if score > best_score:
                best_score = score
                best_text = tile_text
            if best_score >= 1.0:
                return best_text
    return best_text
