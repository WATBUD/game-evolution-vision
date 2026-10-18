from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
from datetime import datetime
from difflib import SequenceMatcher
import json
import math
import os
import queue
import random
import struct
import sys
import threading
import time
import traceback
import tkinter as tk
import unicodedata
import wave
import winsound
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageOps, ImageTk
from pynput import keyboard, mouse
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import (
    BitmapAlphaMode,
    BitmapPixelFormat,
    SoftwareBitmap,
)
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import Buffer


APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
CAPTURE_DIR = APP_DIR / "captures"
SOUND_DIR = APP_DIR / "sounds"
PROJECT_DIR = APP_DIR / "project_data"
PROJECT_TEMPLATE_DIR = PROJECT_DIR / "templates"
PROJECT_FILE = PROJECT_DIR / "gkey_project.json"
ALERT_PLAYBACK_SPEED = 2.0
ALERT_BASE_DURATION = 0.90
OCR_LANGUAGE = "zh-Hant-TW"
_ocr_thread_local = threading.local()

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
SW_RESTORE = 9
SC_RESTORE = 0xF120
WM_SYSCOMMAND = 0x0112
PW_RENDERFULLCONTENT = 0x00000002
HOTKEY_CHOICES = tuple(f"F{i}" for i in range(1, 13))
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0xA3, 0xA5}

# Declare pointer-sized Win32 return values explicitly; HWND/HDC/HBITMAP are
# 64-bit values in a 64-bit Python process.
user32.GetWindowDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.restype = wintypes.HGDIOBJ
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.OpenIcon.argtypes = [wintypes.HWND]
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.GetPixel.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", wintypes.DWORD), ("value", INPUT_UNION)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
]


@dataclass
class KeyEvent:
    time: float
    action: str
    key: str


def enum_windows() -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            if title.value.strip():
                result.append((int(hwnd), title.value.strip()))
        return True

    user32.EnumWindows(callback, 0)
    return sorted(result, key=lambda item: item[1].lower())


def window_process_name(hwnd: int) -> str:
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    if not process_id.value:
        return "未知程式"
    process = kernel32.OpenProcess(0x1000, False, process_id.value)
    if not process:
        return "無法讀取程式"
    try:
        size = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
            return Path(path.value).name
        return "無法讀取程式"
    finally:
        kernel32.CloseHandle(process)


def activate_window(hwnd: int) -> bool:
    if not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        restore_window(hwnd)
    user32.SetForegroundWindow(hwnd)
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        if int(user32.GetForegroundWindow()) == hwnd:
            return True
        time.sleep(0.05)
    return False


def restore_window(hwnd: int) -> bool:
    """Restore windows (including Tk wrappers that ignore ShowWindow alone)."""
    user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.IsIconic(hwnd):
        user32.OpenIcon(hwnd)
        user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_RESTORE, 0)
    return not bool(user32.IsIconic(hwnd))


def capture_window(hwnd: int) -> Image.Image:
    """Capture a top-level window with PrintWindow, including when it is covered."""
    if not user32.IsWindow(hwnd):
        raise RuntimeError("目標視窗已關閉，請重新整理視窗清單。")
    if user32.IsIconic(hwnd):
        # A minimized window is still open, but Windows may report a zero-sized
        # or stale backing surface. Restore it automatically before capturing.
        restore_window(hwnd)
        deadline = time.monotonic() + 1.5
        while user32.IsIconic(hwnd) and time.monotonic() < deadline:
            time.sleep(0.05)
        if user32.IsIconic(hwnd):
            raise RuntimeError("目標視窗仍在執行，但 Windows 無法將它從最小化狀態還原。")
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError()
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError("目標視窗沒有可擷取的畫面尺寸，請重新整理後再試一次。")

    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc) if window_dc else None
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height) if memory_dc else None
    old_object = gdi32.SelectObject(memory_dc, bitmap) if bitmap else None
    try:
        if window_dc and memory_dc and bitmap:
            # Some programs intermittently reject PW_RENDERFULLCONTENT but accept
            # the classic PrintWindow mode, so try both before falling back.
            for attempt, flags in enumerate((PW_RENDERFULLCONTENT, 0)):
                if attempt:
                    time.sleep(0.05)
                if not user32.PrintWindow(hwnd, memory_dc, flags):
                    continue
                info = BITMAPINFO()
                info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                info.bmiHeader.biWidth = width
                info.bmiHeader.biHeight = -height
                info.bmiHeader.biPlanes = 1
                info.bmiHeader.biBitCount = 32
                buffer = ctypes.create_string_buffer(width * height * 4)
                if not gdi32.GetDIBits(
                    memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0
                ):
                    continue
                image = Image.frombuffer(
                    "RGB", (width, height), buffer, "raw", "BGRX", 0, 1
                ).copy()
                if image.getbbox():
                    return image
    finally:
        if old_object:
            gdi32.SelectObject(memory_dc, old_object)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        if window_dc:
            user32.ReleaseDC(hwnd, window_dc)

    # Last resort for applications that block PrintWindow: capture the visible
    # desktop rectangle. This works reliably while the target is unobscured.
    try:
        image = ImageGrab.grab(
            bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True
        ).convert("RGB")
        if image.size == (width, height) and image.getbbox():
            return image
    except Exception:
        pass
    raise RuntimeError(
        "目標視窗拒絕背景擷取，且目前螢幕區域也無法取得。"
        "請將目標視窗還原並保持可見後再試一次。"
    )


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
        # Guard against malformed values returned by unusual image inputs.
        result = cv2.matchTemplate(source, needle, cv2.TM_SQDIFF_NORMED)
        min_value, _max_value, min_location, _max_location = cv2.minMaxLoc(result)
        return max(0.0, 1.0 - float(min_value)), min_location
    return max(0.0, min(1.0, float(max_value))), max_location


def count_color(image: Image.Image, rgb: tuple[int, int, int], tolerance: int) -> int:
    pixels = np.asarray(image, dtype=np.int16)
    target = np.asarray(rgb, dtype=np.int16)
    return int(np.all(np.abs(pixels - target) <= tolerance, axis=2).sum())


def screen_pixel_color(x: int, y: int) -> tuple[int, int, int]:
    """Read one physical screen pixel using virtual-desktop coordinates."""
    screen_dc = user32.GetDC(0)
    if not screen_dc:
        raise ctypes.WinError()
    try:
        color_ref = int(gdi32.GetPixel(screen_dc, int(x), int(y)))
        if color_ref == 0xFFFFFFFF:
            raise ctypes.WinError()
        return color_ref & 0xFF, (color_ref >> 8) & 0xFF, (color_ref >> 16) & 0xFF
    finally:
        user32.ReleaseDC(0, screen_dc)


def create_alert_sound(
    path: Path, volume_db: float, playback_speed: float = ALERT_PLAYBACK_SPEED
) -> None:
    """Create one clear bell chord rendered at the selected playback speed."""
    sample_rate = 44100
    duration = ALERT_BASE_DURATION / playback_speed
    gain = 10.0 ** (volume_db / 20.0)
    notes = (
        (0.00, 659.25, 0.50),   # E5
        (0.00, 830.61, 0.38),   # G#5
        (0.00, 987.77, 0.30),   # B5
    )
    frames = bytearray()
    for index in range(round(sample_rate * duration)):
        moment = index * playback_speed / sample_rate
        sample = 0.0
        for start, frequency, strength in notes:
            local_time = moment - start
            if local_time < 0:
                continue
            attack = min(1.0, local_time / 0.008)
            decay = math.exp(-4.3 * local_time)
            phase = 2.0 * math.pi * frequency * local_time
            bell = (
                math.sin(phase)
                + 0.30 * math.sin(phase * 2.01)
                + 0.12 * math.sin(phase * 3.98)
            )
            sample += strength * attack * decay * bell
        # Gentle saturation keeps the chime audible without harsh clipping.
        sample = math.tanh(sample * 0.82) * 0.88 * gain
        pcm = max(-32767, min(32767, round(sample * 32767)))
        frames.extend(struct.pack("<h", pcm))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)


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
            raise RuntimeError(
                "Windows 尚未安裝繁體中文 OCR 語言（zh-Hant-TW）。"
            )
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


def serialize_key(key: keyboard.Key | keyboard.KeyCode) -> str | None:
    if isinstance(key, keyboard.KeyCode):
        if key.vk is not None:
            return f"vk:{key.vk}"
        if key.char is not None:
            return f"char:{key.char}"
        return None
    return f"key:{key.name}"


def deserialize_key(value: str) -> keyboard.Key | keyboard.KeyCode:
    kind, data = value.split(":", 1)
    if kind == "vk":
        return keyboard.KeyCode.from_vk(int(data))
    if kind == "char":
        return keyboard.KeyCode.from_char(data)
    if kind == "key":
        return getattr(keyboard.Key, data)
    raise ValueError(f"未知按鍵格式：{value}")


def display_key(value: str) -> str:
    kind, data = value.split(":", 1)
    if kind == "char":
        return data.upper() if len(data) == 1 else data
    if kind == "vk":
        return f"VK {data}"
    friendly = {
        "space": "Space", "enter": "Enter", "tab": "Tab", "backspace": "Backspace",
        "esc": "Esc", "delete": "Delete", "shift": "Shift", "shift_l": "左 Shift",
        "shift_r": "右 Shift", "ctrl": "Ctrl", "ctrl_l": "左 Ctrl",
        "ctrl_r": "右 Ctrl", "alt": "Alt", "alt_l": "左 Alt", "alt_r": "右 Alt",
        "cmd": "Win", "cmd_l": "左 Win", "cmd_r": "右 Win",
    }
    return friendly.get(data, data.replace("_", " ").title())


def is_modifier_key(value: str) -> bool:
    return value in {
        "key:alt", "key:alt_l", "key:alt_r", "key:alt_gr",
        "key:ctrl", "key:ctrl_l", "key:ctrl_r",
        "key:shift", "key:shift_l", "key:shift_r",
        "key:cmd", "key:cmd_l", "key:cmd_r",
    }


def reverse_horizontal_key(value: str) -> str:
    return {"key:left": "key:right", "key:right": "key:left"}.get(value, value)


def virtual_key(value: str) -> int:
    key = deserialize_key(value)
    if isinstance(key, keyboard.Key):
        vk = key.value.vk
    else:
        vk = key.vk
        if vk is None and key.char:
            mapped = int(user32.VkKeyScanW(key.char))
            vk = mapped & 0xFF if mapped != -1 else None
    if vk is None:
        raise ValueError(f"無法取得虛擬鍵碼：{value}")
    return int(vk)


def send_windows_key(value: str, pressed: bool) -> None:
    vk = virtual_key(value)
    scan = int(user32.MapVirtualKeyW(vk, 0))
    flags = KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0
    if not pressed:
        flags |= KEYEVENTF_KEYUP
    packet = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, scan, flags, 0, 0))
    if user32.SendInput(1, ctypes.byref(packet), ctypes.sizeof(INPUT)) != 1:
        raise ctypes.WinError()


def precise_wait_until(deadline: float, stop_event: threading.Event) -> bool:
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return stop_event.is_set()
        if remaining > 0.003:
            if stop_event.wait(remaining - 0.002):
                return True
        elif stop_event.is_set():
            return True
        else:
            time.sleep(0)


class RecorderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Game Evolution")
        self.root.geometry("980x760")
        self.root.minsize(820, 650)

        self.windows: list[tuple[int, str]] = []
        self.events: list[KeyEvent] = []
        self.listener: keyboard.Listener | None = None
        self.recording = False
        self.record_started = 0.0
        self.playing = False
        self.stop_event = threading.Event()
        self.detecting = False
        self.continuous_detection = False
        self.pending_detection_restart = False
        self.detection_stop_event = threading.Event()
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.alert_sound_lock = threading.Lock()

        self.window_var = tk.StringVar()
        self.repeat_var = tk.IntVar(value=40)
        self.speed_min_var = tk.DoubleVar(value=0.8)
        self.speed_max_var = tk.DoubleVar(value=1.2)
        self.press_jitter_var = tk.DoubleVar(value=0.010)
        self.release_jitter_var = tk.DoubleVar(value=0.010)
        self.seed_var = tk.IntVar(value=12345)
        self.reverse_even_var = tk.BooleanVar(value=False)
        self.detection_lock_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="就緒")
        self.current_state_var = tk.StringVar(value="目前狀態：就緒")
        self.script_name_var = tk.StringVar(value="目前腳本：尚未載入")
        self.count_var = tk.StringVar(value="尚未錄製事件")
        self.start_hotkey_var = tk.StringVar(value="F8")
        self.stop_hotkey_var = tk.StringVar(value="F9")
        self.play_hotkey_var = tk.StringVar(value="F10")
        self.start_hotkey = "F8"
        self.stop_hotkey = "F9"
        self.play_hotkey = "F10"
        self.start_button_text = tk.StringVar(value="開始錄製 (F8)")
        self.stop_button_text = tk.StringVar(value="停止 (F9)")
        self.play_button_text = tk.StringVar(value="在指定視窗播放 (F10)")
        self.hotkeys_down: set[str] = set()
        self.main_hwnd: int | None = None
        self.detect_mode_var = tk.StringVar(value="ALL")
        self.template_path_var = tk.StringVar(value="尚未選擇圖片")
        self.template_image: Image.Image | None = None
        self.template_images: list[tuple[str, Image.Image]] = []
        self.template_stats: dict[str, dict[str, object]] = {}
        self.template_repeat_vars: dict[str, tk.IntVar] = {}
        self.template_similarity_vars: dict[str, tk.DoubleVar] = {}
        self.image_card_frames: dict[str, tk.Frame] = {}
        self.text_card_frames: dict[str, tk.Frame] = {}
        self.card_flash_last: dict[str, float] = {}
        self.template_preview_photos: list[ImageTk.PhotoImage] = []
        self.color_pick_listener: mouse.Listener | None = None
        self.color_var = tk.StringVar(value="#FF0000")
        self.color_tolerance_var = tk.IntVar(value=10)
        self.ocr_text_var = tk.StringVar(value="")
        self.ocr_similarity_var = tk.DoubleVar(value=0.70)
        self.text_targets: list[dict[str, object]] = []
        self.text_target_setting_vars: list[tuple[tk.DoubleVar, tk.IntVar]] = []
        self.similarity_var = tk.DoubleVar(value=0.85)
        self.image_scan_interval_var = tk.DoubleVar(value=0.5)
        self.text_scan_interval_var = tk.DoubleVar(value=0.5)
        self.detect_result_var = tk.StringVar(value="尚未偵測")
        self.alert_volume_db_var = tk.IntVar(value=-6)
        self.alert_repeat_var = tk.IntVar(value=1)
        self.alert_interval_var = tk.DoubleVar(value=0.0)
        self.alert_speed_var = tk.DoubleVar(value=ALERT_PLAYBACK_SPEED)
        self.alert_cooldown_var = tk.DoubleVar(value=40.0)
        self.project_save_after_id: str | None = None
        self.last_script_path = ""
        self.last_target_hwnd = 0
        self.capture_pending = False
        self.window_watchdog_last = time.time()
        self.window_iconic_since: float | None = None

        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        SOUND_DIR.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self._refresh_text_targets()
        self.load_project()
        self._setup_project_autosave()
        self.refresh_windows()
        self.root.after(250, self._show_main_window)
        self.root.after(600, self._start_locked_detection_on_launch)
        self.root.after(100, self._poll_queue)
        self.root.after(1000, self._window_health_watchdog)
        self.root.bind("<Map>", self._on_root_map, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.safety_listener = keyboard.Listener(
            on_press=self._global_hotkey_press, on_release=self._global_hotkey_release
        )
        self.safety_listener.daemon = True
        self.safety_listener.start()

    def _show_main_window(self) -> None:
        self.root.deiconify()
        self.root.state("normal")
        self.root.update_idletasks()
        root_hwnd = int(user32.GetAncestor(int(self.root.winfo_id()), 2))
        if root_hwnd:
            self.main_hwnd = root_hwnd
            restore_window(root_hwnd)
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.attributes("-topmost", False)
        self.root.focus_force()

    def _on_root_map(self, event: tk.Event) -> None:
        """Repair taskbar restores using Tk events, without subclassing WNDPROC."""
        if event.widget is self.root:
            self.root.after_idle(self._finish_root_restore)

    def _finish_root_restore(self) -> None:
        if not self.root.winfo_exists() or self.root.state() != "normal":
            return
        self.root.update_idletasks()
        root_hwnd = int(user32.GetAncestor(int(self.root.winfo_id()), 2))
        if root_hwnd:
            self.main_hwnd = root_hwnd
            user32.ShowWindow(root_hwnd, SW_RESTORE)
        self.root.lift()

    def _window_health_watchdog(self) -> None:
        """Keep Windows from permanently stranding the Tk window as iconic."""
        now = time.time()
        callback_gap = now - self.window_watchdog_last
        self.window_watchdog_last = now
        try:
            if self.root.state() == "iconic":
                if self.window_iconic_since is None:
                    self.window_iconic_since = now
                if callback_gap >= 5.0:
                    self._force_root_restore(background=False)
                elif now - self.window_iconic_since >= 3.0:
                    self._force_root_restore(background=True)
            else:
                self.window_iconic_since = None
        finally:
            if self.root.winfo_exists():
                self.root.after(1000, self._window_health_watchdog)

    def _force_root_restore(self, background: bool) -> None:
        self.root.deiconify()
        self.root.state("normal")
        self.root.update_idletasks()
        root_hwnd = int(user32.GetAncestor(int(self.root.winfo_id()), 2))
        if root_hwnd:
            self.main_hwnd = root_hwnd
            restore_window(root_hwnd)
        self.window_iconic_since = None
        if background:
            self.root.lower()
            self.status_var.set(
                "已在背景解除 Windows 最小化鎖定；點擊工具列即可正常顯示。"
            )
        else:
            self.root.lift()
            self.status_var.set("系統喚醒後，Game Evolution 視窗已自動還原。")

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        app_bg = "#EEF3F8"
        surface = "#FFFFFF"
        text_color = "#24384B"
        primary = "#1688C5"
        primary_hover = "#0F74AA"
        self.root.configure(background=app_bg)
        style.configure(".", font=("Microsoft JhengHei UI", 9))
        style.configure("TFrame", background=surface)
        style.configure("TLabel", background=surface, foreground=text_color)
        style.configure(
            "TLabelframe", background=surface, bordercolor="#C9D8E5",
            relief="solid", borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label", background=surface, foreground="#17324D",
            font=("Microsoft JhengHei UI", 9, "bold"),
        )
        style.configure(
            "TButton", background="#E2ECF4", foreground="#28445D",
            bordercolor="#B8CBD9", lightcolor="#E2ECF4", darkcolor="#E2ECF4",
            padding=(10, 6), relief="flat",
        )
        style.map(
            "TButton", background=[("active", "#D3E4F0"), ("pressed", "#C3D9E8")],
            foreground=[("disabled", "#8A9AAA")],
        )
        style.configure(
            "Accent.TButton", font=("Microsoft JhengHei UI", 9, "bold"),
            padding=(12, 7), foreground="#FFFFFF", background=primary,
            bordercolor=primary, lightcolor=primary, darkcolor=primary,
        )
        style.map(
            "Accent.TButton",
            background=[("active", primary_hover), ("pressed", "#0B628F")],
            foreground=[("disabled", "#D4E7F2")],
        )
        style.configure("Toolbar.TButton", padding=(9, 5))
        style.configure(
            "Danger.TButton", padding=(9, 5), foreground="#A33A32",
            background="#FBE9E7", bordercolor="#EDC5C0",
        )
        style.map("Danger.TButton", background=[("active", "#F6D7D3")])
        style.configure(
            "TEntry", fieldbackground=surface, foreground=text_color,
            bordercolor="#B8CBD9", padding=5,
        )
        style.configure(
            "TCombobox", fieldbackground=surface, background=surface,
            foreground=text_color, arrowcolor="#47657D", bordercolor="#B8CBD9",
            padding=4,
        )
        style.map("TCombobox", fieldbackground=[("readonly", surface)])
        style.configure(
            "TSpinbox", fieldbackground=surface, foreground=text_color,
            arrowcolor="#47657D", bordercolor="#B8CBD9", padding=3,
        )
        style.configure("TCheckbutton", background=surface, foreground=text_color)
        style.configure(
            "Info.TLabel", background="#E7F3FA", foreground="#31566F",
            padding=(12, 9), font=("Microsoft JhengHei UI", 9),
        )
        style.configure(
            "TNotebook", background=app_bg, borderwidth=0,
            tabmargins=(0, 4, 0, 0), relief="flat",
        )
        # Clam inserts a focus element around the selected tab label, which looks
        # like a shrinking dotted button.  Keep every tab the same size and use
        # color alone to communicate selection.
        style.layout(
            "TNotebook.Tab",
            [
                ("Notebook.tab", {
                    "sticky": "nswe",
                    "children": [
                        ("Notebook.padding", {
                            "side": "top", "sticky": "nswe",
                            "children": [("Notebook.label", {"side": "top", "sticky": ""})],
                        }),
                    ],
                }),
            ],
        )
        style.configure(
            "TNotebook.Tab", font=("Microsoft JhengHei UI", 9, "bold"),
            padding=(13, 6), background="#DCE7F0", foreground="#4B6478",
            borderwidth=0, relief="flat", focuscolor="#DCE7F0",
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", primary), ("active", "#CFE2EF")],
            foreground=[("selected", "#FFFFFF"), ("active", "#17324D")],
            padding=[("selected", (13, 6)), ("active", (13, 6))],
            relief=[("selected", "flat"), ("active", "flat")],
        )
        style.configure(
            "Treeview", background=surface, fieldbackground=surface,
            foreground=text_color, rowheight=28, bordercolor="#CAD8E3",
        )
        style.configure(
            "Treeview.Heading", background="#DCEAF4", foreground="#17324D",
            font=("Microsoft JhengHei UI", 9, "bold"), padding=(6, 6), relief="flat",
        )
        style.map("Treeview", background=[("selected", "#BDE3F5")], foreground=[("selected", "#17324D")])
        style.configure(
            "Vertical.TScrollbar", background="#C8D8E5", troughcolor="#E7EEF4",
            bordercolor="#E7EEF4", arrowcolor="#47657D",
        )
        style.configure(
            "Horizontal.TScrollbar", background="#C8D8E5", troughcolor="#E7EEF4",
            bordercolor="#E7EEF4", arrowcolor="#47657D",
        )
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        target = ttk.LabelFrame(outer, text="目標視窗", padding=12)
        target.pack(fill="x")
        self.window_combo = ttk.Combobox(target, textvariable=self.window_var, state="readonly")
        self.window_combo.pack(side="left", fill="x", expand=True)
        self.window_combo.bind("<<ComboboxSelected>>", self._on_target_window_selected)
        ttk.Button(
            target, text="重新整理", command=self.refresh_windows,
            style="Toolbar.TButton",
        ).pack(side="left", padx=(8, 0))

        status_banner = tk.Frame(
            outer, background="#17324D", highlightbackground="#45B7E5",
            highlightcolor="#45B7E5", highlightthickness=2, padx=14, pady=10,
        )
        status_banner.pack(fill="x", pady=(10, 0))
        status_top = tk.Frame(status_banner, background="#17324D")
        status_top.pack(fill="x")
        status_top.grid_columnconfigure(1, weight=1)
        status_top.grid_rowconfigure(0, weight=1, uniform="status_rows", minsize=32)
        status_top.grid_rowconfigure(1, weight=1, uniform="status_rows", minsize=32)
        tk.Button(
            status_top, text="載入腳本", command=self.load_script,
            background="#2D9CDB", foreground="#FFFFFF",
            activebackground="#56CCF2", activeforeground="#102A43",
            font=("Segoe UI", 10, "bold"), relief="flat", borderwidth=0,
            cursor="hand2", width=12, pady=4,
        ).grid(row=0, column=0, sticky="nsew", padx=(0, 14), pady=(0, 3))
        tk.Button(
            status_top, text="儲存腳本", command=self.save_script,
            background="#0E7490", foreground="#FFFFFF",
            activebackground="#22A6B3", activeforeground="#FFFFFF",
            font=("Segoe UI", 10, "bold"), relief="flat", borderwidth=0,
            cursor="hand2", width=12, pady=4,
        ).grid(row=1, column=0, sticky="nsew", padx=(0, 14), pady=(3, 0))
        tk.Label(
            status_top, textvariable=self.script_name_var,
            background="#17324D", foreground="#7FDBFF",
            font=("Microsoft JhengHei UI", 11, "bold"), anchor="w",
        ).grid(row=0, column=1, sticky="nsew", pady=(0, 3))
        tk.Label(
            status_top, textvariable=self.current_state_var,
            background="#17324D", foreground="#FFFFFF",
            font=("Microsoft JhengHei UI", 11, "bold"), anchor="e",
        ).grid(row=0, column=2, sticky="nsew", pady=(0, 3))
        tk.Label(
            status_top, textvariable=self.status_var,
            background="#17324D", foreground="#D9EAF3",
            font=("Microsoft JhengHei UI", 11), anchor="w", justify="left", pady=0,
            wraplength=740,
        ).grid(row=1, column=1, columnspan=2, sticky="nsew", pady=(3, 0))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True, pady=(12, 0))
        detection_tab = ttk.Frame(notebook, padding=8)
        recording_tab = ttk.Frame(notebook, padding=8)
        playback_tab = ttk.Frame(notebook, padding=8)
        notebook.add(recording_tab, text="錄製腳本")
        notebook.add(detection_tab, text="畫面偵測")
        notebook.add(playback_tab, text="播放設定")

        detection_scrollbar = ttk.Scrollbar(detection_tab, orient="vertical")
        detection_scrollbar.pack(side="right", fill="y")
        self.detection_scroll_canvas = tk.Canvas(
            detection_tab, highlightthickness=0, background=surface,
            yscrollcommand=detection_scrollbar.set,
        )
        self.detection_scroll_canvas.pack(side="left", fill="both", expand=True)
        detection_scrollbar.configure(command=self.detection_scroll_canvas.yview)
        detection_scroll_inner = ttk.Frame(self.detection_scroll_canvas)
        self.detection_scroll_window_id = self.detection_scroll_canvas.create_window(
            (0, 0), window=detection_scroll_inner, anchor="nw"
        )
        detection_scroll_inner.bind(
            "<Configure>",
            lambda _event: self.detection_scroll_canvas.configure(
                scrollregion=self.detection_scroll_canvas.bbox("all")
            ),
        )
        self.detection_scroll_canvas.bind(
            "<Configure>",
            lambda event: self.detection_scroll_canvas.itemconfigure(
                self.detection_scroll_window_id, width=event.width
            ),
        )
        self.root.bind_all("<MouseWheel>", self._scroll_detection_page, add="+")

        detection_border = tk.Frame(
            detection_scroll_inner,
            background="#28A9E0",
            highlightbackground="#28A9E0",
            highlightcolor="#28A9E0",
            highlightthickness=2,
            borderwidth=0,
        )
        detection_border.pack(fill="both", expand=True)
        detection = ttk.Frame(detection_border, padding=12)
        detection.pack(fill="both", expand=True, padx=2, pady=2)
        ttk.Label(
            detection, text="偵測類型", foreground="#0879B5",
            font=("Microsoft JhengHei UI", 9, "bold"),
        ).grid(
            row=0, column=0, sticky="w"
        )
        mode_combo = ttk.Combobox(
            detection, textvariable=self.detect_mode_var,
            values=("ALL", "圖片", "文字"),
            width=10, state="readonly",
        )
        mode_combo.grid(row=0, column=1, padx=(8, 20), sticky="w")
        image_actions = ttk.Frame(detection)
        image_actions.grid(row=0, column=2)
        ttk.Button(
            image_actions, text="匯入圖片…", command=self.import_template,
            style="Toolbar.TButton",
        ).pack(side="left")
        ttk.Button(
            image_actions, text="擷取畫面…", command=self.start_screen_capture,
            style="Toolbar.TButton",
        ).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(
            image_actions, text="開啟資料夾", command=self.open_capture_folder,
            style="Toolbar.TButton",
        ).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(
            image_actions, text="清除圖片", command=self.clear_templates,
            style="Danger.TButton",
        ).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(
            image_actions, text="儲存專案", command=self.save_project,
            style="Toolbar.TButton",
        ).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(
            detection, textvariable=self.template_path_var, width=28, anchor="w",
            foreground="#16714A",
        ).grid(row=0, column=3, padx=8, sticky="ew")
        text_add_panel = tk.Frame(
            detection, background="#F3EFFA", highlightbackground="#C8B5E6",
            highlightthickness=1, padx=10, pady=7,
        )
        text_add_panel.grid(
            row=4, column=0, columnspan=7, sticky="w", pady=(12, 0)
        )
        tk.Label(
            text_add_panel, text="新增文字目標", background="#F3EFFA",
            foreground="#5F3D8C", font=("Microsoft JhengHei UI", 9, "bold"),
        ).pack(side="left")
        self.new_text_entry = ttk.Entry(
            text_add_panel, textvariable=self.ocr_text_var, width=30
        )
        self.new_text_entry.pack(side="left", padx=(10, 8))
        self.new_text_entry.bind("<Return>", self._add_text_target_from_enter)
        self.new_text_entry.bind("<KP_Enter>", self._add_text_target_from_enter)
        ttk.Button(
            text_add_panel, text="＋ 加入列表", command=self.add_text_target,
            style="Accent.TButton",
        ).pack(side="left")
        tk.Label(
            text_add_panel, text="輸入後按 Enter", background="#F3EFFA",
            foreground="#7A6A8D", font=("Microsoft JhengHei UI", 8),
        ).pack(side="left", padx=(10, 0))

        text_list_frame = ttk.LabelFrame(detection, padding=6)
        text_list_frame.grid(row=5, column=0, columnspan=7, sticky="ew", pady=(10, 0))
        text_header = ttk.Frame(text_list_frame)
        ttk.Label(
            text_header, text="文字列表", foreground="#7352A3",
            font=("Microsoft JhengHei UI", 9, "bold"),
        ).pack(side="left")
        ttk.Label(
            text_header, text="文字掃描間隔（秒）", foreground="#7352A3"
        ).pack(side="left", padx=(18, 6))
        ttk.Spinbox(
            text_header, from_=0.1, to=60.0, increment=0.1,
            format="%.1f", textvariable=self.text_scan_interval_var, width=6,
        ).pack(side="left")
        text_list_frame.configure(labelwidget=text_header)
        self.text_list_inner = ttk.Frame(text_list_frame)
        self.text_list_inner.pack(fill="x")

        preview_frame = ttk.LabelFrame(detection, padding=6)
        preview_frame.grid(row=6, column=0, columnspan=7, sticky="nsew", pady=(10, 0))
        preview_header = ttk.Frame(preview_frame)
        ttk.Label(
            preview_header, text="圖片列表", foreground="#0879B5",
            font=("Microsoft JhengHei UI", 9, "bold"),
        ).pack(side="left")
        ttk.Label(
            preview_header, text="圖片掃描間隔（秒）", foreground="#0879B5"
        ).pack(side="left", padx=(18, 6))
        ttk.Spinbox(
            preview_header, from_=0.1, to=60.0, increment=0.1,
            format="%.1f", textvariable=self.image_scan_interval_var, width=6,
        ).pack(side="left")
        preview_frame.configure(labelwidget=preview_header)
        self.preview_inner = ttk.Frame(preview_frame)
        self.preview_inner.pack(fill="x")
        self.preview_empty_label = ttk.Label(self.preview_inner, text="尚未設定圖片")
        self.preview_empty_label.pack(anchor="w", padx=8, pady=10)

        actions = ttk.Frame(detection)
        actions.grid(row=1, column=0, columnspan=7, sticky="ew", pady=(10, 0))
        self.detect_once_button = ttk.Button(
            actions, text="偵測一次", command=self.detect_once,
            style="Accent.TButton",
        )
        self.detect_once_button.pack(side="left")
        self.monitor_button = ttk.Button(
            actions, text="開始持續偵測", command=self.toggle_detection,
            style="Accent.TButton",
        )
        self.monitor_button.pack(side="left", padx=8)
        self.detection_lock_check = ttk.Checkbutton(
            actions, text="鎖定偵測", variable=self.detection_lock_var,
            command=self._update_detection_lock_state,
        )
        self.detection_lock_check.pack(side="left")
        self.detect_result_label = ttk.Label(
            actions, textvariable=self.detect_result_var, foreground="#0879B5",
            font=("Microsoft JhengHei UI", 9, "bold"), anchor="w", justify="left",
            wraplength=600,
        )
        self.detect_result_label.pack(
            side="left", fill="x", expand=True, padx=(8, 0)
        )
        actions.bind("<Configure>", self._resize_detection_result)
        alert_settings = ttk.Frame(detection)
        alert_settings.grid(row=2, column=0, columnspan=7, sticky="w", pady=(8, 0))
        ttk.Label(
            alert_settings, text="提示音音量", foreground="#B35A00"
        ).pack(side="left")
        ttk.Spinbox(
            alert_settings, from_=-40, to=0, increment=1,
            textvariable=self.alert_volume_db_var, width=6,
        ).pack(side="left", padx=(8, 3))
        ttk.Label(alert_settings, text="dB").pack(side="left")
        ttk.Label(alert_settings, text="倍速", foreground="#B35A00").pack(
            side="left", padx=(12, 0)
        )
        ttk.Spinbox(
            alert_settings, from_=0.25, to=4.0, increment=0.25,
            format="%.2f", textvariable=self.alert_speed_var, width=5,
        ).pack(side="left", padx=(8, 0))
        ttk.Label(alert_settings, text="間隔", foreground="#B35A00").pack(
            side="left", padx=(12, 0)
        )
        ttk.Spinbox(
            alert_settings, from_=0.0, to=60.0, increment=0.05, format="%.2f",
            textvariable=self.alert_interval_var, width=6,
        ).pack(side="left", padx=(8, 3))
        ttk.Label(alert_settings, text="秒").pack(side="left")
        ttk.Label(alert_settings, text="命中冷卻", foreground="#B35A00").pack(
            side="left", padx=(12, 0)
        )
        ttk.Spinbox(
            alert_settings, from_=0.0, to=3600.0, increment=1.0, format="%.0f",
            textvariable=self.alert_cooldown_var, width=6,
        ).pack(side="left", padx=(8, 3))
        ttk.Label(alert_settings, text="秒").pack(side="left")
        ttk.Button(
            alert_settings, text="試聽", command=self.preview_alert_sound
        ).pack(
            side="left", padx=(10, 0)
        )
        ttk.Label(
            detection,
            text="每張圖片與每項文字皆可獨立設定；圖片可試聽提示音，預設命中冷卻 40 秒",
            foreground="#526575",
        ).grid(row=3, column=0, columnspan=7, sticky="w", pady=(6, 0))
        detection.columnconfigure(3, weight=1)
        detection.rowconfigure(6, weight=1)

        recording = ttk.LabelFrame(recording_tab, text="腳本錄製", padding=12)
        recording.pack(fill="both", expand=True)
        row = ttk.Frame(recording)
        row.pack(fill="x")
        self.record_button = ttk.Button(
            row, textvariable=self.start_button_text, command=self.start_recording,
            style="Accent.TButton",
        )
        self.record_button.pack(side="left")
        ttk.Button(
            row, textvariable=self.stop_button_text, command=self.stop_all,
            style="Danger.TButton",
        ).pack(side="left", padx=8)
        ttk.Button(
            row, text="清除事件", command=self.clear_events, style="Toolbar.TButton"
        ).pack(side="left")
        ttk.Label(recording, textvariable=self.count_var).pack(anchor="w", pady=(10, 0))

        event_frame = ttk.Frame(recording)
        event_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.event_table = ttk.Treeview(
            event_frame, columns=("time", "action", "key"), show="headings", height=5
        )
        self.event_table.heading("time", text="時間（秒）")
        self.event_table.heading("action", text="動作")
        self.event_table.heading("key", text="按鍵")
        self.event_table.column("time", width=110, anchor="e", stretch=False)
        self.event_table.column("action", width=100, anchor="center", stretch=False)
        self.event_table.column("key", width=350, anchor="w")
        event_scroll = ttk.Scrollbar(event_frame, orient="vertical", command=self.event_table.yview)
        self.event_table.configure(yscrollcommand=event_scroll.set)
        self.event_table.pack(side="left", fill="both", expand=True)
        event_scroll.pack(side="right", fill="y")

        hotkeys = ttk.LabelFrame(playback_tab, text="全域快捷鍵", padding=12)
        hotkeys.pack(fill="x", pady=(0, 12))
        ttk.Label(hotkeys, text="開始錄製").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            hotkeys, textvariable=self.start_hotkey_var, values=HOTKEY_CHOICES,
            width=7, state="readonly"
        ).grid(row=0, column=1, padx=(8, 24))
        ttk.Label(hotkeys, text="停止錄製／播放").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            hotkeys, textvariable=self.stop_hotkey_var, values=HOTKEY_CHOICES,
            width=7, state="readonly"
        ).grid(row=0, column=3, padx=8)
        ttk.Button(
            hotkeys, text="套用快捷鍵", command=self.apply_hotkeys,
            style="Accent.TButton",
        ).grid(row=0, column=4, padx=(16, 0))
        ttk.Label(hotkeys, text="播放腳本").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Combobox(
            hotkeys, textvariable=self.play_hotkey_var, values=HOTKEY_CHOICES,
            width=7, state="readonly"
        ).grid(row=1, column=1, padx=(8, 24), pady=(10, 0))

        playback = ttk.LabelFrame(playback_tab, text="播放", padding=12)
        playback.pack(fill="x")
        ttk.Label(playback, text="播放次數").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(playback, from_=1, to=9999, textvariable=self.repeat_var, width=8).grid(row=0, column=1, padx=(8, 24))
        ttk.Label(playback, text="速度範圍").grid(row=0, column=2, sticky="w")
        speed_range = ttk.Frame(playback)
        speed_range.grid(row=0, column=3, padx=8)
        ttk.Spinbox(
            speed_range, from_=0.10, to=10.0, increment=0.05,
            format="%.2f", textvariable=self.speed_min_var, width=6
        ).pack(side="left")
        ttk.Label(speed_range, text=" ～ ").pack(side="left")
        ttk.Spinbox(
            speed_range, from_=0.10, to=10.0, increment=0.05,
            format="%.2f", textvariable=self.speed_max_var, width=6
        ).pack(side="left")
        self.play_button = ttk.Button(
            playback, textvariable=self.play_button_text, command=self.start_playback,
            style="Accent.TButton",
        )
        self.play_button.grid(row=0, column=4, padx=(20, 0))
        ttk.Label(playback, text="按下抖動 ±").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Spinbox(
            playback, from_=0.000, to=0.050, increment=0.001,
            format="%.3f", textvariable=self.press_jitter_var, width=8
        ).grid(row=1, column=1, padx=(8, 24), pady=(10, 0))
        ttk.Label(playback, text="秒（0 表示關閉）").grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Label(playback, text="放開抖動 ±").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(
            playback, from_=0.000, to=0.050, increment=0.001,
            format="%.3f", textvariable=self.release_jitter_var, width=8
        ).grid(row=2, column=1, padx=(8, 24), pady=(8, 0))
        ttk.Label(playback, text="秒（0 表示關閉）").grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Label(playback, text="亂數種子").grid(row=1, column=3, sticky="e", pady=(10, 0))
        ttk.Spinbox(
            playback, from_=0, to=2147483647, textvariable=self.seed_var, width=10
        ).grid(row=1, column=4, sticky="w", padx=(8, 0), pady=(10, 0))
        ttk.Checkbutton(
            playback,
            text="雙數輪左右相反",
            variable=self.reverse_even_var,
        ).grid(row=2, column=3, columnspan=2, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(
            playback_tab,
            text="安全機制：播放時若焦點離開指定視窗，腳本會停止。\n開始、停止與播放快捷鍵不會被寫入腳本。",
            style="Info.TLabel",
            wraplength=680,
            justify="left",
        ).pack(anchor="nw", pady=(12, 0))

    def _scroll_detection_page(self, event: tk.Event) -> str | None:
        canvas = self.detection_scroll_canvas
        if not canvas.winfo_viewable() or event.state & 0x0001:
            return None
        pointer_x = self.root.winfo_pointerx()
        pointer_y = self.root.winfo_pointery()
        left = canvas.winfo_rootx()
        top = canvas.winfo_rooty()
        if not (
            left <= pointer_x < left + canvas.winfo_width()
            and top <= pointer_y < top + canvas.winfo_height()
        ):
            return None
        direction = -1 if event.delta > 0 else 1
        canvas.yview_scroll(direction * 3, "units")
        return "break"

    def _resize_detection_result(self, event: tk.Event) -> None:
        controls_width = (
            self.detect_once_button.winfo_reqwidth()
            + self.monitor_button.winfo_reqwidth()
            + self.detection_lock_check.winfo_reqwidth()
            + 40
        )
        available = max(180, event.width - controls_width)
        self.detect_result_label.configure(wraplength=available)

    def refresh_windows(self) -> None:
        current_hwnd = self._selected_hwnd()
        own_hwnd = int(self.root.winfo_id())
        self.windows = [(h, t) for h, t in enum_windows() if h != own_hwnd]
        labels = [
            f"{title}  [{window_process_name(hwnd)}｜0x{hwnd:X}]"
            for hwnd, title in self.windows
        ]
        self.window_combo["values"] = labels
        preferred_hwnd = current_hwnd or self.last_target_hwnd
        if preferred_hwnd:
            for i, (hwnd, _) in enumerate(self.windows):
                if hwnd == preferred_hwnd:
                    self.window_combo.current(i)
                    self.last_target_hwnd = hwnd
                    break
            else:
                if labels:
                    self.window_combo.current(0)
                    self.last_target_hwnd = self.windows[0][0]
        elif labels:
            self.window_combo.current(0)
            self.last_target_hwnd = self.windows[0][0]
        self.status_var.set(f"找到 {len(labels)} 個可見視窗")

    def _on_target_window_selected(self, _event: tk.Event | None = None) -> None:
        selected = self._selected_hwnd()
        if selected is not None:
            self.last_target_hwnd = selected
            self._schedule_project_save()
            self._on_detection_setting_changed()

    def _selected_hwnd(self) -> int | None:
        index = self.window_combo.current()
        return self.windows[index][0] if 0 <= index < len(self.windows) else None

    def import_template(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="匯入一張或多張要尋找的圖片",
            initialdir=str(CAPTURE_DIR),
            filetypes=[("圖片", "*.png *.jpg *.jpeg *.bmp *.webp"), ("所有檔案", "*.*")],
        )
        if not paths:
            return
        errors: list[str] = []
        loaded = 0
        for path in paths:
            try:
                with Image.open(path) as source:
                    image = source.convert("RGB")
                self._set_template_image(image, Path(path).name, "已載入")
                loaded += 1
            except (OSError, ValueError) as exc:
                errors.append(f"{Path(path).name}: {exc}")
        if loaded:
            self.detect_result_var.set(
                f"已載入 {loaded} 張圖片，目前共 {len(self.template_images)} 張"
                f"{'；持續偵測將於下一輪套用' if self.detecting else ''}"
            )
        if errors:
            self._show_copyable_error("部分圖片載入失敗", "\n".join(errors))

    def open_capture_folder(self) -> None:
        try:
            CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(CAPTURE_DIR))
        except OSError:
            self._show_copyable_error("無法開啟圖片資料夾", traceback.format_exc().strip())

    def _setup_project_autosave(self) -> None:
        variables = (
            self.detect_mode_var, self.similarity_var, self.image_scan_interval_var,
            self.text_scan_interval_var,
            self.color_var, self.color_tolerance_var,
            self.alert_volume_db_var,
            self.alert_repeat_var, self.alert_interval_var, self.alert_speed_var,
            self.alert_cooldown_var,
        )
        for variable in variables:
            variable.trace_add("write", self._schedule_project_save)
        detection_variables = (
            self.detect_mode_var, self.similarity_var, self.image_scan_interval_var,
            self.text_scan_interval_var,
            self.color_var, self.color_tolerance_var,
            self.alert_repeat_var, self.alert_interval_var, self.alert_speed_var,
            self.alert_cooldown_var,
        )
        for variable in detection_variables:
            variable.trace_add("write", self._on_detection_setting_changed)

    def _on_ocr_text_changed(self, *_args: object) -> None:
        self._on_detection_setting_changed()

    def _on_detection_setting_changed(self, *_args: object) -> None:
        if self.detecting and self.continuous_detection:
            self.pending_detection_restart = True
            self.detection_stop_event.set()

    def _schedule_project_save(self, *_args: object) -> None:
        if self.project_save_after_id is not None:
            self.root.after_cancel(self.project_save_after_id)
        self.project_save_after_id = self.root.after(350, self._autosave_project)

    def _autosave_project(self) -> None:
        self.project_save_after_id = None
        self.save_project(notify=False)

    def save_project(self, notify: bool = True) -> None:
        try:
            PROJECT_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
            templates: list[dict[str, object]] = []
            for index, (name, image) in enumerate(self.template_images):
                filename = f"template_{index + 1:03d}.png"
                image.save(PROJECT_TEMPLATE_DIR / filename, format="PNG")
                stat = self.template_stats.get(self._template_stat_key(name, image), {})
                templates.append({
                    "name": name,
                    "file": f"templates/{filename}",
                    "last_detected": str(stat.get("last_detected", "")),
                    "count": int(stat.get("count", 0)),
                    "alert_repeat": int(stat.get("alert_repeat", 1)),
                    "similarity": float(stat.get("similarity", 0.85)),
                })
            payload = {
                "version": 9,
                "script": {"last_path": self.last_script_path},
                "target_window": {
                    "hwnd": self._selected_hwnd() or self.last_target_hwnd,
                },
                "templates": templates,
                "detection": {
                    "mode": self.detect_mode_var.get(),
                    "similarity": float(self.similarity_var.get()),
                    "image_scan_interval": float(self.image_scan_interval_var.get()),
                    "text_scan_interval": float(self.text_scan_interval_var.get()),
                    "text_targets": self.text_targets,
                    "color": self.color_var.get(),
                    "color_tolerance": int(self.color_tolerance_var.get()),
                    "ocr_text": self.ocr_text_var.get(),
                    "ocr_similarity": float(self.ocr_similarity_var.get()),
                },
                "alert": {
                    "volume_db": int(self.alert_volume_db_var.get()),
                    "repeat": int(self.alert_repeat_var.get()),
                    "interval": float(self.alert_interval_var.get()),
                    "speed": float(self.alert_speed_var.get()),
                    "cooldown": float(self.alert_cooldown_var.get()),
                },
            }
            temporary = PROJECT_FILE.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(PROJECT_FILE)
            if notify:
                self.detect_result_var.set(
                    f"專案已儲存：{len(self.template_images)} 張圖片"
                )
        except Exception:
            if notify:
                self._show_copyable_error("專案儲存失敗", traceback.format_exc().strip())

    def load_project(self) -> None:
        if not PROJECT_FILE.exists():
            migrated: list[tuple[str, Image.Image]] = []
            for image_path in sorted(CAPTURE_DIR.glob("capture_*.png")):
                try:
                    with Image.open(image_path) as source:
                        migrated.append((image_path.name, source.convert("RGB")))
                except OSError:
                    continue
            if migrated:
                self.template_images = migrated
                self.template_image = migrated[-1][1]
                self.template_path_var.set(f"已選擇 {len(migrated)} 張圖片")
                self._refresh_template_previews()
                self.detect_result_var.set(
                    f"已將 captures 中的 {len(migrated)} 張圖片建立為初始專案"
                )
                self.save_project(notify=False)
            return
        try:
            data = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
            project_version = int(data.get("version", 1))
            loaded: list[tuple[str, Image.Image]] = []
            loaded_stats: dict[str, dict[str, object]] = {}
            alert = data.get("alert", {})
            legacy_repeat = max(1, min(20, int(alert.get("repeat", 1))))
            for item in data.get("templates", []):
                image_path = PROJECT_DIR / str(item["file"])
                with Image.open(image_path) as source:
                    image = source.convert("RGB")
                name = str(item["name"])
                loaded.append((name, image))
                loaded_stats[self._template_stat_key(name, image)] = {
                    "last_detected": str(item.get("last_detected", "")),
                    "count": int(item.get("count", 0)),
                    "alert_repeat": max(
                        1, min(20, int(item.get("alert_repeat", legacy_repeat)))
                    ),
                    "similarity": float(item.get(
                        "similarity", data.get("detection", {}).get("similarity", 0.85)
                    )),
                }
            self.template_images = loaded
            self.template_stats = loaded_stats
            self.template_repeat_vars = {}
            self.template_similarity_vars = {}
            self.template_image = loaded[-1][1] if loaded else None
            script = data.get("script", {})
            self.last_script_path = str(script.get("last_path", ""))
            target_window = data.get("target_window", {})
            self.last_target_hwnd = int(target_window.get("hwnd", 0))
            detection = data.get("detection", {})
            stored_mode = str(detection.get("mode", "ALL"))
            if stored_mode == "圖片＋文字":
                stored_mode = "ALL"
            if stored_mode not in ("ALL", "圖片", "文字"):
                stored_mode = "ALL"
            self.detect_mode_var.set(stored_mode)
            self.similarity_var.set(float(detection.get("similarity", 0.85)))
            legacy_interval = float(detection.get("interval", 0.5))
            self.image_scan_interval_var.set(
                float(detection.get("image_scan_interval", legacy_interval))
            )
            self.text_scan_interval_var.set(
                float(detection.get("text_scan_interval", legacy_interval))
            )
            saved_text_targets = detection.get("text_targets")
            if isinstance(saved_text_targets, list):
                self.text_targets = [
                    {
                        "text": str(item.get("text", "")).strip(),
                        "similarity": float(item.get("similarity", 0.70)),
                        "alert_repeat": max(1, min(20, int(item.get("alert_repeat", 1)))),
                    }
                    for item in saved_text_targets
                    if isinstance(item, dict) and str(item.get("text", "")).strip()
                ]
            else:
                legacy_text = str(detection.get("ocr_text", "")).strip()
                self.text_targets = ([{
                    "text": legacy_text,
                    "similarity": float(detection.get("ocr_similarity", 0.70)),
                    "alert_repeat": legacy_repeat,
                }] if legacy_text else [])
            self._refresh_text_targets()
            self.color_var.set(str(detection.get("color", "#FF0000")))
            self.color_tolerance_var.set(int(detection.get("color_tolerance", 10)))
            self.ocr_text_var.set("")
            self.ocr_similarity_var.set(
                float(detection.get("ocr_similarity", 0.70))
            )
            self.alert_volume_db_var.set(int(alert.get("volume_db", -6)))
            self.alert_repeat_var.set(int(alert.get("repeat", 1)))
            self.alert_interval_var.set(float(alert.get("interval", 0.0)))
            self.alert_speed_var.set(float(alert.get("speed", ALERT_PLAYBACK_SPEED)))
            self.alert_cooldown_var.set(
                40.0 if project_version < 2 else float(alert.get("cooldown", 40.0))
            )
            self.template_path_var.set(
                f"已選擇 {len(loaded)} 張圖片" if loaded else "尚未選擇圖片"
            )
            self._refresh_template_previews()
            self.detect_result_var.set(f"已還原上次專案：{len(loaded)} 張圖片")
            if project_version < 9:
                self.save_project(notify=False)
        except Exception:
            self.detect_result_var.set("上次專案載入失敗，可按儲存專案重新建立。")

    def _set_template_image(self, image: Image.Image, name: str, action: str) -> None:
        converted = image.convert("RGB")
        self.template_image = converted
        self.template_images = [*self.template_images, (name, converted)]
        self.template_stats.setdefault(
            self._template_stat_key(name, converted),
            {
                "last_detected": "", "count": 0, "alert_repeat": 1,
                "similarity": 0.85,
            },
        )
        self.template_path_var.set(f"已選擇 {len(self.template_images)} 張圖片")
        self._refresh_template_previews()
        self.detect_result_var.set(
            f"{action} {name}（{converted.width}×{converted.height}），"
            f"目前共 {len(self.template_images)} 張"
            f"{'；持續偵測將於下一輪套用' if self.detecting else ''}"
        )
        self.save_project(notify=False)

    def _flash_detection_card(
        self, target_type: str, key: str, repeat_count: int,
        playback_speed: float, alert_interval: float,
    ) -> None:
        flash_id = f"{target_type}:{key}"
        now = time.monotonic()
        if now < self.card_flash_last.get(flash_id, 0.0):
            return
        frames = self.image_card_frames if target_type == "image" else self.text_card_frames
        frame = frames.get(key)
        if frame is None or not frame.winfo_exists():
            return
        repeat_count = max(1, min(20, int(repeat_count)))
        playback_speed = max(0.25, min(4.0, float(playback_speed)))
        cycle_ms = max(
            140,
            round((ALERT_BASE_DURATION + max(0.0, alert_interval)) * 1000 / playback_speed),
        )
        bright_ms = min(180, max(80, cycle_ms // 2))
        self.card_flash_last[flash_id] = now + (repeat_count * cycle_ms / 1000) + 0.4

        def pulse(index: int = 0) -> None:
            current = frames.get(key)
            if current is None or not current.winfo_exists():
                return
            color = "#FFB000" if index % 2 == 0 else "#35C9FF"
            current.configure(background=color, highlightbackground=color)
            self.root.after(bright_ms, restore, index)

        def restore(index: int) -> None:
            current = frames.get(key)
            if current is None or not current.winfo_exists():
                return
            current.configure(background="#C9D8E5", highlightbackground="#C9D8E5")
            if index + 1 < repeat_count:
                self.root.after(max(20, cycle_ms - bright_ms), pulse, index + 1)

        pulse()

    def add_text_target(self) -> None:
        text = self.ocr_text_var.get().strip()
        if not text:
            messagebox.showwarning("無法加入文字", "請先輸入要偵測的文字。", parent=self.root)
            return
        if any(str(item["text"]).casefold() == text.casefold() for item in self.text_targets):
            messagebox.showinfo("文字已存在", f"文字「{text}」已在列表中。", parent=self.root)
            return
        self.text_targets.append({"text": text, "similarity": 0.70, "alert_repeat": 1})
        self.ocr_text_var.set("")
        self._refresh_text_targets()
        self._on_detection_setting_changed()
        self.save_project(notify=False)

    def _add_text_target_from_enter(self, _event: tk.Event) -> str:
        self.add_text_target()
        self.new_text_entry.focus_set()
        return "break"

    def remove_text_target(self, index: int) -> None:
        if not 0 <= index < len(self.text_targets):
            return
        removed = str(self.text_targets.pop(index)["text"])
        self._refresh_text_targets()
        self.detect_result_var.set(f"已移除文字「{removed}」")
        self._on_detection_setting_changed()
        self.save_project(notify=False)

    def _update_text_target_setting(
        self, index: int, similarity_var: tk.DoubleVar, repeat_var: tk.IntVar,
    ) -> None:
        if not 0 <= index < len(self.text_targets):
            return
        try:
            similarity = float(similarity_var.get())
            repeat = int(repeat_var.get())
        except tk.TclError:
            return
        self.text_targets[index]["similarity"] = similarity
        self.text_targets[index]["alert_repeat"] = repeat
        self._on_detection_setting_changed()
        self._schedule_project_save()

    def _refresh_text_targets(self) -> None:
        for child in self.text_list_inner.winfo_children():
            child.destroy()
        self.text_target_setting_vars = []
        self.text_card_frames = {}
        if not self.text_targets:
            ttk.Label(self.text_list_inner, text="尚未加入文字", foreground="#6B7280").pack(
                anchor="w", padx=6, pady=6
            )
            return
        for index, item in enumerate(self.text_targets):
            target_key = f"__ocr_text_{index}__"
            wrapper = tk.Frame(
                self.text_list_inner, background="#C9D8E5",
                highlightbackground="#C9D8E5", highlightthickness=2,
                borderwidth=0,
            )
            wrapper.pack(fill="x", padx=4, pady=3)
            self.text_card_frames[target_key] = wrapper
            row = ttk.LabelFrame(
                wrapper, text=f"{index + 1}. {item['text']}", padding=(9, 5)
            )
            row.pack(fill="x", padx=1, pady=1)
            ttk.Label(row, text="相似度", foreground="#7352A3").pack(side="left")
            similarity_var = tk.DoubleVar(value=float(item.get("similarity", 0.70)))
            ttk.Spinbox(
                row, from_=0.10, to=1.00, increment=0.01, format="%.2f",
                textvariable=similarity_var, width=6,
            ).pack(side="left", padx=(6, 14))
            ttk.Label(row, text="音效次數", foreground="#B35A00").pack(side="left")
            repeat_var = tk.IntVar(value=int(item.get("alert_repeat", 1)))
            ttk.Spinbox(
                row, from_=1, to=20, increment=1, textvariable=repeat_var, width=5,
            ).pack(side="left", padx=(6, 10))
            ttk.Button(
                row, text="移除", style="Danger.TButton",
                command=lambda item_index=index: self.remove_text_target(item_index)
            ).pack(side="left")
            similarity_var.trace_add(
                "write", lambda *_args, item_index=index, s=similarity_var, r=repeat_var:
                self._update_text_target_setting(item_index, s, r)
            )
            repeat_var.trace_add(
                "write", lambda *_args, item_index=index, s=similarity_var, r=repeat_var:
                self._update_text_target_setting(item_index, s, r)
            )
            self.text_target_setting_vars.append((similarity_var, repeat_var))

    def _refresh_template_previews(self) -> None:
        for child in self.preview_inner.winfo_children():
            child.destroy()
        self.template_preview_photos = []
        self.image_card_frames = {}
        if not self.template_images:
            self.preview_empty_label = ttk.Label(self.preview_inner, text="尚未設定圖片")
            self.preview_empty_label.pack(anchor="w", padx=8, pady=10)
            return
        for index, (name, image) in enumerate(self.template_images):
            key = self._template_stat_key(name, image)
            wrapper = tk.Frame(
                self.preview_inner, background="#C9D8E5",
                highlightbackground="#C9D8E5", highlightthickness=2,
                borderwidth=0,
            )
            wrapper.pack(fill="x", padx=4, pady=3)
            self.image_card_frames[key] = wrapper
            card = ttk.LabelFrame(
                wrapper, text=f"{index + 1}. {name}", padding=(9, 6)
            )
            card.pack(fill="x", padx=1, pady=1)
            card.columnconfigure(1, weight=1)
            preview_width, preview_height = 96, 64
            scaled = ImageOps.contain(
                image.convert("RGB"),
                (preview_width - 8, preview_height - 8),
                method=Image.Resampling.LANCZOS,
            )
            preview = Image.new(
                "RGB", (preview_width, preview_height), color=(238, 243, 248)
            )
            offset = (
                (preview_width - scaled.width) // 2,
                (preview_height - scaled.height) // 2,
            )
            preview.paste(scaled, offset)
            photo = ImageTk.PhotoImage(preview)
            self.template_preview_photos.append(photo)
            ttk.Label(card, image=photo, anchor="center").grid(
                row=0, column=0, rowspan=2, padx=(0, 12), sticky="w"
            )
            stat = self.template_stats.get(
                self._template_stat_key(name, image),
                {"last_detected": "", "count": 0},
            )
            last_detected = str(stat.get("last_detected", "")) or "尚未偵測到"
            ttk.Label(card, text=f"上次偵測：{last_detected}").grid(
                row=0, column=1, sticky="sw", padx=(0, 16)
            )
            ttk.Label(
                card, text=f"命中總次數：{int(stat.get('count', 0))}",
                foreground="#16714A",
            ).grid(row=1, column=1, sticky="nw", padx=(0, 16), pady=(4, 0))
            repeat_var = self.template_repeat_vars.get(key)
            if repeat_var is None:
                repeat_var = tk.IntVar(
                    value=max(1, min(20, int(stat.get("alert_repeat", 1))))
                )
                repeat_var.trace_add(
                    "write",
                    lambda *_args, item_key=key, variable=repeat_var:
                    self._on_template_repeat_changed(item_key, variable),
                )
                self.template_repeat_vars[key] = repeat_var
            similarity_var = self.template_similarity_vars.get(key)
            if similarity_var is None:
                similarity_var = tk.DoubleVar(
                    value=float(stat.get("similarity", 0.85))
                )
                similarity_var.trace_add(
                    "write",
                    lambda *_args, item_key=key, variable=similarity_var:
                    self._on_template_similarity_changed(item_key, variable),
                )
                self.template_similarity_vars[key] = similarity_var
            repeat_row = ttk.Frame(card)
            repeat_row.grid(row=0, column=2, rowspan=2, padx=(0, 14), sticky="e")
            ttk.Label(repeat_row, text="相似度", foreground="#0879B5").pack(side="left")
            ttk.Spinbox(
                repeat_row, from_=0.10, to=1.00, increment=0.01, format="%.2f",
                textvariable=similarity_var, width=6,
            ).pack(side="left", padx=(6, 14))
            ttk.Label(repeat_row, text="音效次數", foreground="#B35A00").pack(side="left")
            ttk.Spinbox(
                repeat_row, from_=1, to=20, increment=1,
                textvariable=repeat_var, width=4,
            ).pack(side="left", padx=(6, 0))
            card_actions = ttk.Frame(card)
            card_actions.grid(row=0, column=3, rowspan=2, sticky="e")
            ttk.Button(
                card_actions, text="移除", style="Danger.TButton",
                command=lambda item=index: self.remove_template(item)
            ).pack(side="left")

    def remove_template(self, index: int) -> None:
        if not 0 <= index < len(self.template_images):
            return
        removed_name, removed_image = self.template_images[index]
        removed_key = self._template_stat_key(removed_name, removed_image)
        self.template_images = [
            item for item_index, item in enumerate(self.template_images) if item_index != index
        ]
        self.template_image = self.template_images[-1][1] if self.template_images else None
        if not any(
            self._template_stat_key(name, image) == removed_key
            for name, image in self.template_images
        ):
            self.template_stats.pop(removed_key, None)
            self.template_repeat_vars.pop(removed_key, None)
            self.template_similarity_vars.pop(removed_key, None)
        self.template_path_var.set(
            f"已選擇 {len(self.template_images)} 張圖片"
            if self.template_images else "尚未選擇圖片"
        )
        self._refresh_template_previews()
        self.detect_result_var.set(f"已移除 {removed_name}，剩餘 {len(self.template_images)} 張")
        self.save_project(notify=False)

    def clear_templates(self) -> None:
        self.template_images = []
        self.template_stats = {}
        self.template_repeat_vars = {}
        self.template_similarity_vars = {}
        self.template_image = None
        self.template_path_var.set("尚未選擇圖片")
        self._refresh_template_previews()
        self.detect_result_var.set("已清除所有搜尋圖片。")
        self.save_project(notify=False)

    @staticmethod
    def _template_stat_key(name: str, image: Image.Image) -> str:
        return f"{name}\0{image.width}x{image.height}"

    def _on_template_repeat_changed(self, key: str, variable: tk.IntVar) -> None:
        try:
            repeat_count = int(variable.get())
        except (ValueError, tk.TclError):
            return
        if not 1 <= repeat_count <= 20:
            return
        stat = self.template_stats.setdefault(
            key, {
                "last_detected": "", "count": 0, "alert_repeat": 1,
                "similarity": 0.85,
            }
        )
        stat["alert_repeat"] = repeat_count
        self._schedule_project_save()

    def _on_template_similarity_changed(
        self, key: str, variable: tk.DoubleVar,
    ) -> None:
        try:
            similarity = float(variable.get())
        except (ValueError, tk.TclError):
            return
        if not 0.1 <= similarity <= 1.0:
            return
        stat = self.template_stats.setdefault(
            key, {
                "last_detected": "", "count": 0, "alert_repeat": 1,
                "similarity": 0.85,
            },
        )
        stat["similarity"] = similarity
        self._on_detection_setting_changed()
        self._schedule_project_save()

    def _template_repeat_count(self, key: str) -> int:
        stat = self.template_stats.get(key, {})
        return max(1, min(20, int(stat.get("alert_repeat", 1))))

    def _template_similarity(self, key: str) -> float:
        stat = self.template_stats.get(key, {})
        return max(0.1, min(1.0, float(stat.get("similarity", 0.85))))

    def start_screen_capture(self) -> None:
        if self.detecting:
            if self.capture_pending:
                return
            self.capture_pending = True
            self.detection_stop_event.set()
            self.detect_result_var.set("正在停止持續偵測，接著開啟畫面擷取…")
            self.root.after(50, self._capture_after_detection_stops)
            return
        self._begin_screen_capture()

    def _capture_after_detection_stops(self) -> None:
        if self.detecting:
            self.root.after(50, self._capture_after_detection_stops)
            return
        self.capture_pending = False
        self._begin_screen_capture()

    def _begin_screen_capture(self) -> None:
        self.root.withdraw()
        self.root.after(250, self._open_capture_overlay)

    def _open_capture_overlay(self) -> None:
        try:
            screenshot = ImageGrab.grab(all_screens=True).convert("RGB")
            virtual_x = int(user32.GetSystemMetrics(76))
            virtual_y = int(user32.GetSystemMetrics(77))
            virtual_width = int(user32.GetSystemMetrics(78))
            virtual_height = int(user32.GetSystemMetrics(79))
            if virtual_width <= 0 or virtual_height <= 0:
                raise RuntimeError("無法取得桌面畫面尺寸。")
        except Exception:
            self.root.deiconify()
            self._show_copyable_error("畫面擷取失敗", traceback.format_exc().strip())
            return

        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.geometry(
            f"{virtual_width}x{virtual_height}{virtual_x:+d}{virtual_y:+d}"
        )
        overlay.configure(cursor="crosshair")
        canvas = tk.Canvas(overlay, highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)

        display_image = screenshot
        if screenshot.size != (virtual_width, virtual_height):
            display_image = screenshot.resize(
                (virtual_width, virtual_height), Image.Resampling.LANCZOS
            )
        background_photo = ImageTk.PhotoImage(display_image)
        canvas.create_image(0, 0, image=background_photo, anchor="nw")
        canvas.background_photo = background_photo
        instruction_bg = canvas.create_rectangle(
            virtual_width // 2 - 240, 18, virtual_width // 2 + 240, 64,
            fill="#111111", outline="#FFFFFF",
        )
        instruction = canvas.create_text(
            virtual_width // 2, 41,
            text="拖曳框選要尋找的畫面｜Esc 或右鍵取消",
            fill="white", font=("Segoe UI", 13, "bold"),
        )
        selection_id: int | None = None
        start_x = start_y = 0

        def restore_app() -> None:
            if overlay.winfo_exists():
                overlay.destroy()
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

        def cancel(_event: object = None) -> None:
            restore_app()
            self.detect_result_var.set("已取消畫面擷取。")

        def begin(event: tk.Event) -> None:
            nonlocal start_x, start_y, selection_id
            start_x, start_y = event.x, event.y
            canvas.itemconfigure(instruction_bg, state="hidden")
            canvas.itemconfigure(instruction, state="hidden")
            selection_id = canvas.create_rectangle(
                start_x, start_y, start_x, start_y, outline="#00E5FF", width=3
            )

        def drag(event: tk.Event) -> None:
            if selection_id is not None:
                canvas.coords(selection_id, start_x, start_y, event.x, event.y)

        def finish(event: tk.Event) -> None:
            current_x = max(0, min(virtual_width, event.x))
            current_y = max(0, min(virtual_height, event.y))
            origin_x = max(0, min(virtual_width, start_x))
            origin_y = max(0, min(virtual_height, start_y))
            left, right = sorted((origin_x, current_x))
            top, bottom = sorted((origin_y, current_y))
            if right - left < 3 or bottom - top < 3:
                cancel()
                return
            scale_x = screenshot.width / virtual_width
            scale_y = screenshot.height / virtual_height
            crop_box = (
                round(left * scale_x), round(top * scale_y),
                round(right * scale_x), round(bottom * scale_y),
            )
            captured = screenshot.crop(crop_box)
            restore_app()
            try:
                CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                capture_path = CAPTURE_DIR / f"capture_{timestamp}.png"
                captured.save(capture_path, format="PNG")
                self._set_template_image(
                    captured, capture_path.name, f"已擷取並儲存至 {capture_path.name}："
                )
            except OSError:
                self._set_template_image(captured, "尚未儲存的螢幕擷取", "已擷取")
                self._show_copyable_error("擷取圖片儲存失敗", traceback.format_exc().strip())

        canvas.bind("<ButtonPress-1>", begin)
        canvas.bind("<B1-Motion>", drag)
        canvas.bind("<ButtonRelease-1>", finish)
        canvas.bind("<ButtonPress-3>", cancel)
        overlay.bind("<Escape>", cancel)
        overlay.focus_force()

    def choose_detection_color(self) -> None:
        _rgb, color = colorchooser.askcolor(
            color=self.color_var.get(), title="選擇要偵測的顏色", parent=self.root
        )
        if color:
            self.color_var.set(color.upper())
            self.detect_mode_var.set("顏色")

    def start_color_picker(self) -> None:
        self.detect_mode_var.set("顏色")
        self.detect_result_var.set("正在開啟吸色畫面…")
        self.root.withdraw()
        self.root.after(250, self._open_color_picker_overlay)

    def _open_color_picker_overlay(self) -> None:
        try:
            screenshot = ImageGrab.grab(all_screens=True).convert("RGB")
            virtual_x = int(user32.GetSystemMetrics(76))
            virtual_y = int(user32.GetSystemMetrics(77))
            virtual_width = int(user32.GetSystemMetrics(78))
            virtual_height = int(user32.GetSystemMetrics(79))
            if virtual_width <= 0 or virtual_height <= 0:
                raise RuntimeError("無法取得桌面畫面尺寸。")
        except Exception:
            self.root.deiconify()
            self._show_copyable_error("吸色失敗", traceback.format_exc().strip())
            return

        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.geometry(f"{virtual_width}x{virtual_height}{virtual_x:+d}{virtual_y:+d}")
        canvas = tk.Canvas(overlay, highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)

        display_image = screenshot
        if screenshot.size != (virtual_width, virtual_height):
            display_image = screenshot.resize(
                (virtual_width, virtual_height), Image.Resampling.LANCZOS
            )
        background_photo = ImageTk.PhotoImage(display_image)
        canvas.create_image(0, 0, image=background_photo, anchor="nw")
        canvas.background_photo = background_photo
        canvas.create_rectangle(
            virtual_width // 2 - 240, 18, virtual_width // 2 + 240, 64,
            fill="#111111", outline="#FFFFFF",
        )
        canvas.create_text(
            virtual_width // 2, 41,
            text="移動滑鼠查看顏色｜左鍵確認｜Esc 或右鍵取消",
            fill="white", font=("Segoe UI", 13, "bold"),
        )
        horizontal = canvas.create_line(0, 0, 0, 0, fill="#00E5FF", width=1)
        vertical = canvas.create_line(0, 0, 0, 0, fill="#00E5FF", width=1)
        panel = canvas.create_rectangle(0, 0, 150, 54, fill="#111111", outline="white")
        swatch = canvas.create_rectangle(8, 8, 46, 46, fill="#000000", outline="white")
        color_text = canvas.create_text(
            56, 27, text="#000000", fill="white", anchor="w",
            font=("Consolas", 12, "bold"),
        )
        current_hex = "#000000"

        def sampled_hex(x: int, y: int) -> str:
            image_x = max(0, min(screenshot.width - 1, round(x * screenshot.width / virtual_width)))
            image_y = max(0, min(screenshot.height - 1, round(y * screenshot.height / virtual_height)))
            red, green, blue = screenshot.getpixel((image_x, image_y))
            return f"#{red:02X}{green:02X}{blue:02X}"

        def move(event: tk.Event) -> None:
            nonlocal current_hex
            current_hex = sampled_hex(event.x, event.y)
            canvas.coords(horizontal, event.x - 12, event.y, event.x + 12, event.y)
            canvas.coords(vertical, event.x, event.y - 12, event.x, event.y + 12)
            panel_x = event.x + 20 if event.x + 180 < virtual_width else event.x - 170
            panel_y = event.y + 20 if event.y + 84 < virtual_height else event.y - 74
            canvas.coords(panel, panel_x, panel_y, panel_x + 150, panel_y + 54)
            canvas.coords(swatch, panel_x + 8, panel_y + 8, panel_x + 46, panel_y + 46)
            canvas.coords(color_text, panel_x + 56, panel_y + 27)
            canvas.itemconfigure(swatch, fill=current_hex)
            canvas.itemconfigure(color_text, text=current_hex)

        def restore_app() -> None:
            if overlay.winfo_exists():
                overlay.destroy()
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

        def cancel(_event: object = None) -> None:
            restore_app()
            self.detect_result_var.set("已取消吸色。")

        def select(event: tk.Event) -> None:
            selected = sampled_hex(event.x, event.y)
            restore_app()
            self.color_var.set(selected)
            self.detect_result_var.set(f"已從畫面吸取顏色 {selected}")

        canvas.bind("<Motion>", move)
        canvas.bind("<ButtonPress-1>", select)
        canvas.bind("<ButtonPress-3>", cancel)
        overlay.bind("<Escape>", cancel)
        overlay.focus_force()

    def _detection_settings(
        self,
    ) -> tuple[int, str, object, tuple[float, float], str, float, float, float]:
        hwnd = self._selected_hwnd()
        if hwnd is None:
            raise ValueError("請先選擇目標視窗。")
        target_title = next((title for handle, title in self.windows if handle == hwnd), "未知視窗")
        mode = self.detect_mode_var.get()
        try:
            image_interval = float(self.image_scan_interval_var.get())
            text_interval = float(self.text_scan_interval_var.get())
            cooldown = float(self.alert_cooldown_var.get())
            alert_interval = float(self.alert_interval_var.get())
            alert_speed = float(self.alert_speed_var.get())
            if image_interval < 0.1 or text_interval < 0.1:
                raise ValueError
            if (
                cooldown < 0 or alert_interval < 0
                or not 0.25 <= alert_speed <= 4.0
            ):
                raise ValueError
            image_target: object | None = None
            text_target: object | None = None
            if mode in ("圖片", "ALL"):
                if not self.template_images:
                    raise ValueError("請先匯入要尋找的圖片。")
                image_target = [
                    (
                        name, image.copy(),
                        self._template_similarity(self._template_stat_key(name, image)),
                    )
                    for name, image in self.template_images
                ]
            if mode in ("文字", "ALL"):
                if not self.text_targets:
                    raise ValueError("請先將要尋找的文字加入文字列表。")
                text_target = []
                for index, item in enumerate(self.text_targets):
                    raw_text = str(item["text"]).strip()
                    normalized_text = normalize_ocr_text(raw_text)
                    text_threshold = float(item.get("similarity", 0.70))
                    repeat_count = int(item.get("alert_repeat", 1))
                    if (
                        not normalized_text or not 0.1 <= text_threshold <= 1.0
                        or not 1 <= repeat_count <= 20
                    ):
                        raise ValueError("請確認文字列表中的相似度與音效次數。")
                    text_target.append((
                        raw_text, normalized_text, repeat_count, text_threshold,
                        f"__ocr_text_{index}__",
                    ))
            if mode == "ALL":
                target: object = (image_target, text_target)
            elif mode == "圖片":
                target = image_target
            elif mode == "文字":
                target = text_target
            else:
                value = self.color_var.get().strip().lstrip("#")
                if len(value) != 6:
                    raise ValueError
                rgb = tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
                tolerance = int(self.color_tolerance_var.get())
                if not 0 <= tolerance <= 255:
                    raise ValueError
                target = (rgb, tolerance)
        except (ValueError, tk.TclError):
            raise ValueError(
                "請確認圖片、文字、顏色、相似度及偵測間隔的設定。"
            ) from None
        return (
            hwnd, mode, target, (image_interval, text_interval), target_title, cooldown,
            alert_interval, alert_speed,
        )

    def detect_once(self) -> None:
        if self.detecting:
            return
        self._start_detection(continuous=False)

    def _start_locked_detection_on_launch(self) -> None:
        if self.detection_lock_var.get() and not self.detecting:
            self._start_detection(continuous=True)

    def toggle_detection(self) -> None:
        if self.detecting:
            if self.continuous_detection and self.detection_lock_var.get():
                return
            self.pending_detection_restart = False
            self.detection_stop_event.set()
            return
        self._start_detection(continuous=True)

    def _update_detection_lock_state(self) -> None:
        locked_while_monitoring = (
            self.detecting
            and self.continuous_detection
            and self.detection_lock_var.get()
        )
        self.monitor_button.configure(
            state="disabled" if locked_while_monitoring else "normal"
        )

    def _start_detection(self, continuous: bool) -> None:
        try:
            settings = self._detection_settings()
        except ValueError as exc:
            messagebox.showwarning("無法開始偵測", str(exc), parent=self.root)
            return
        self.detecting = True
        self.continuous_detection = continuous
        self.detection_stop_event.clear()
        self.monitor_button.configure(text="停止持續偵測" if continuous else "偵測中…")
        self._update_detection_lock_state()
        self.detect_result_var.set("正在擷取目標視窗…")
        threading.Thread(
            target=self._detection_worker, args=(*settings, continuous), daemon=True
        ).start()

    def _detect_text_target_list(
        self, image: Image.Image, targets: list[tuple[str, str, int, float, str]],
        target_title: str, next_alert_at: dict[str, float], cooldown: float,
        alert_interval: float, alert_speed: float,
    ) -> str:
        results: list[tuple[str, float, float, str]] = []
        visual_hits: list[tuple[str, str, int, float, float]] = []
        now = time.monotonic()
        for raw_text, normalized_text, repeat_count, threshold, key in targets:
            recognized = recognize_text_for_target(image, normalized_text)
            score = ocr_text_similarity(normalized_text, recognized)
            results.append((raw_text, score, threshold, recognized))
            if score < threshold or now < next_alert_at.get(key, 0.0):
                continue
            visual_hits.append((
                "text", key, repeat_count, alert_speed, alert_interval,
            ))
            hit_text = f"[{target_title}] 文字命中「{raw_text}」{score:.1%}"
            self.ui_queue.put((
                "detection_hit",
                {
                    "text": hit_text,
                    "template": f"文字「{raw_text}」",
                    "repeat_count": repeat_count,
                    "playback_speed": alert_speed,
                },
            ))
            sequence_duration = (
                repeat_count * ALERT_BASE_DURATION
                + max(0, repeat_count - 1) * alert_interval
            ) / alert_speed
            next_alert_at[key] = now + sequence_duration + cooldown
        if visual_hits:
            self.ui_queue.put(("visual_hits", visual_hits))
        matched = [item for item in results if item[1] >= item[2]]
        best = max(results, key=lambda item: item[1])
        compact_ocr = " ".join(best[3].split())
        if len(compact_ocr) > 45:
            compact_ocr = compact_ocr[:42] + "…"
        if matched:
            names = "、".join(f"「{item[0]}」{item[1]:.1%}" for item in matched[:3])
            return f"命中 {len(matched)} 項：{names}"
        return (
            f"未命中，最高「{best[0]}」{best[1]:.1%}"
            f"（門檻 {best[2]:.0%}；OCR：{compact_ocr or '無'}）"
        )

    def _detect_combined_frame(
        self, image: Image.Image, target: object, target_title: str,
        continuous: bool, previous_matches: set[str],
        next_alert_at: dict[str, float], cooldown: float,
        alert_interval: float, alert_speed: float,
        detect_image: bool, detect_text: bool,
        image_summary: str, text_summary: str,
    ) -> tuple[str, set[str], str, str]:
        image_target, text_target = target
        matched_keys = previous_matches
        now = time.monotonic()
        if detect_image:
            original_templates = image_target
            templates = (
                [
                    (
                        name, item.copy(),
                        self._template_similarity(self._template_stat_key(name, item)),
                    )
                    for name, item in self.template_images
                ]
                if continuous else original_templates
            )
            image_results = [
                (
                    name, *find_template(image, item),
                    self._template_stat_key(name, item),
                    self._template_repeat_count(self._template_stat_key(name, item)),
                    threshold,
                )
                for name, item, threshold in templates
            ]
            image_matches = [
                result for result in image_results if result[1] >= result[5]
            ]
            matched_keys = {result[3] for result in image_matches}
            new_matches = matched_keys - previous_matches
            if new_matches:
                self.ui_queue.put(("template_hits", list(new_matches)))

            if image_results:
                best_name, best_score, best_location, _key, _repeat, best_threshold = max(
                    image_results, key=lambda result: result[1]
                )
                if image_matches:
                    image_summary = (
                        f"命中 {len(image_matches)} 張，最高 {best_score:.1%}"
                        f"（{best_name}，{best_location[0]}, {best_location[1]}）"
                    )
                else:
                    image_summary = (
                        f"未命中，最高 {best_score:.1%}"
                        f"（{best_name}；門檻 {best_threshold:.0%}）"
                    )
            else:
                image_summary = "尚未設定搜尋圖片"

            for matched_name, _score, _location, key, repeat_count, _threshold in image_matches:
                if now < next_alert_at.get(key, 0.0):
                    continue
                self.ui_queue.put((
                    "visual_hits",
                    [("image", key, repeat_count, alert_speed, alert_interval)],
                ))
                hit_text = f"[{target_title}] 圖片 {image_summary}"
                self.ui_queue.put((
                    "detection_hit",
                    {
                        "text": hit_text,
                        "template": matched_name,
                        "repeat_count": repeat_count,
                        "playback_speed": alert_speed,
                    },
                ))
                sequence_duration = (
                    repeat_count * ALERT_BASE_DURATION
                    + max(0, repeat_count - 1) * alert_interval
                ) / alert_speed
                next_alert_at[key] = now + sequence_duration + cooldown

        if detect_text:
            text_summary = self._detect_text_target_list(
                image, text_target, target_title, next_alert_at, cooldown,
                alert_interval, alert_speed,
            )

        combined = f"[{target_title}] 圖片：{image_summary}｜文字：{text_summary}"
        return combined, matched_keys, image_summary, text_summary

    def _detection_worker(
        self, hwnd: int, mode: str, target: object, intervals: tuple[float, float],
        target_title: str, cooldown: float, alert_interval: float,
        alert_speed: float,
        continuous: bool,
    ) -> None:
        next_alert_at: dict[str, float] = {}
        previous_matches: set[str] = set()
        image_interval, text_interval = intervals
        interval = image_interval if mode == "圖片" else text_interval
        next_image_scan = 0.0
        next_text_scan = 0.0
        image_summary = "等待圖片掃描"
        text_summary = "等待文字掃描"
        try:
            while not self.detection_stop_event.is_set():
                started = time.monotonic()
                image: Image.Image | None = None
                last_capture_error: Exception | None = None
                for attempt in range(3):
                    try:
                        image = capture_window(hwnd)
                        break
                    except RuntimeError as exc:
                        last_capture_error = exc
                        if attempt < 2 and self.detection_stop_event.wait(0.12):
                            return
                if image is None:
                    raise last_capture_error or RuntimeError("無法擷取目標視窗。")
                if mode == "ALL":
                    now = time.monotonic()
                    detect_image = now >= next_image_scan
                    detect_text = now >= next_text_scan
                    text, previous_matches, image_summary, text_summary = self._detect_combined_frame(
                        image, target, target_title, continuous, previous_matches,
                        next_alert_at, cooldown, alert_interval, alert_speed,
                        detect_image, detect_text, image_summary, text_summary,
                    )
                    if detect_image:
                        next_image_scan = now + image_interval
                    if detect_text:
                        next_text_scan = now + text_interval
                elif mode == "圖片":
                    original_templates = target
                    # Continuous monitoring must not keep the startup snapshot:
                    # importing/capturing/removing templates takes effect next cycle.
                    templates = (
                        [
                            (
                                name, item.copy(),
                                self._template_similarity(
                                    self._template_stat_key(name, item)
                                ),
                            )
                            for name, item in self.template_images
                        ]
                        if continuous
                        else original_templates
                    )
                    results = [
                        (
                            name,
                            *find_template(image, item),
                            self._template_stat_key(name, item),
                            self._template_repeat_count(
                                self._template_stat_key(name, item)
                            ),
                            threshold,
                        )
                        for name, item, threshold in templates
                    ]
                    if not results:
                        previous_matches.clear()
                        text = f"[{target_title}] 尚未設定搜尋圖片"
                        self.ui_queue.put(("detect_result", text))
                        if not continuous:
                            break
                        if self.detection_stop_event.wait(interval):
                            break
                        continue
                    matched = [result for result in results if result[1] >= result[5]]
                    best_name, best_score, best_location, _best_key, _best_repeat, best_threshold = max(
                        results, key=lambda result: result[1]
                    )
                    matched_keys = {result[3] for result in matched}
                    new_matches = matched_keys - previous_matches
                    if new_matches:
                        self.ui_queue.put(("template_hits", list(new_matches)))
                    previous_matches = matched_keys
                    hit = bool(matched)
                    if hit:
                        matched_names = "、".join(result[0] for result in matched[:3])
                        extra = f" 等 {len(matched)} 張" if len(matched) > 3 else ""
                        text = (
                            f"[{target_title}] 命中 {matched_names}{extra}｜"
                            f"最高 {best_score:.1%}（{best_name}，座標 "
                            f"{best_location[0]}, {best_location[1]}）"
                        )
                    else:
                        text = (
                            f"[{target_title}] {len(results)} 張皆未出現｜最高 {best_score:.1%}"
                            f"（{best_name}；門檻 {best_threshold:.0%}）"
                        )
                    if hit:
                        now = time.monotonic()
                        for matched_name, _score, _location, key, repeat_count, _threshold in matched:
                            if now < next_alert_at.get(key, 0.0):
                                continue
                            self.ui_queue.put((
                                "visual_hits",
                                [("image", key, repeat_count, alert_speed, alert_interval)],
                            ))
                            self.ui_queue.put((
                                "detection_hit",
                                {
                                    "text": text,
                                    "template": matched_name,
                                    "repeat_count": repeat_count,
                                    "playback_speed": alert_speed,
                                },
                            ))
                            sequence_duration = (
                                repeat_count * ALERT_BASE_DURATION
                                + max(0, repeat_count - 1) * alert_interval
                            ) / alert_speed
                            next_alert_at[key] = now + sequence_duration + cooldown
                elif mode == "文字":
                    summary = self._detect_text_target_list(
                        image, target, target_title, next_alert_at, cooldown,
                        alert_interval, alert_speed,
                    )
                    text = f"[{target_title}] 文字：{summary}"
                else:
                    rgb, tolerance = target
                    count = count_color(image, rgb, tolerance)
                    ratio = count / (image.width * image.height)
                    text = (
                        f"[{target_title}] {'有出現' if count else '未出現'}｜"
                        f"符合 {count:,} 像素（{ratio:.4%}）"
                    )
                self.ui_queue.put(("detect_result", text))
                if not continuous:
                    break
                if mode == "ALL":
                    remaining = max(
                        0.0, min(next_image_scan, next_text_scan) - time.monotonic()
                    )
                else:
                    remaining = max(0.0, interval - (time.monotonic() - started))
                if self.detection_stop_event.wait(remaining):
                    break
        except Exception as exc:
            self.ui_queue.put(("detect_error", traceback.format_exc().strip()))
        finally:
            self.detecting = False
            self.ui_queue.put(("detect_done", ""))

    def _hotkey_name(self, key: keyboard.Key | keyboard.KeyCode) -> str | None:
        if isinstance(key, keyboard.Key) and key.name and key.name.startswith("f"):
            return key.name.upper()
        return None

    def _global_hotkey_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        name = self._hotkey_name(key)
        if name is None or name in self.hotkeys_down:
            return
        self.hotkeys_down.add(name)
        if name == self.stop_hotkey:
            self.root.after(0, self.stop_all)
        elif name == self.start_hotkey:
            self.root.after(0, self.start_recording)
        elif name == self.play_hotkey:
            self.root.after(0, self.start_playback)

    def _global_hotkey_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        name = self._hotkey_name(key)
        if name:
            self.hotkeys_down.discard(name)

    def apply_hotkeys(self) -> None:
        start_key = self.start_hotkey_var.get()
        stop_key = self.stop_hotkey_var.get()
        play_key = self.play_hotkey_var.get()
        if len({start_key, stop_key, play_key}) != 3:
            messagebox.showwarning("快捷鍵重複", "開始、停止與播放快捷鍵不能相同。")
            return
        self.start_hotkey = start_key
        self.stop_hotkey = stop_key
        self.play_hotkey = play_key
        self.start_button_text.set(f"開始錄製 ({start_key})")
        self.stop_button_text.set(f"停止 ({stop_key})")
        self.play_button_text.set(f"在指定視窗播放 ({play_key})")
        self.status_var.set(
            f"快捷鍵已套用：{start_key} 開始、{stop_key} 停止、{play_key} 播放。"
        )

    def _set_state(self, state: str, detail: str) -> None:
        self.current_state_var.set(f"目前狀態：{state}")
        self.status_var.set(detail)

    def _show_copyable_error(self, title: str, message: str) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.minsize(480, 230)

        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="發生錯誤", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        text_box = tk.Text(body, wrap="word", height=8, relief="solid", borderwidth=1)
        text_box.pack(fill="both", expand=True, pady=(10, 12))
        text_box.insert("1.0", message)
        text_box.configure(state="disabled")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x")

        def copy_message() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(f"{title}\n{message}")
            self.root.update()
            copy_button.configure(text="已複製")

        copy_button = ttk.Button(buttons, text="複製訊息", command=copy_message)
        copy_button.pack(side="left")
        ttk.Button(buttons, text="關閉", command=dialog.destroy).pack(side="right")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        dialog.focus_force()

    def preview_alert_sound(self) -> None:
        self.play_alert_sound(int(self.alert_repeat_var.get()))

    def preview_template_sound(self, variable: tk.IntVar) -> None:
        try:
            repeat_count = int(variable.get())
        except (ValueError, tk.TclError):
            repeat_count = 0
        self.play_alert_sound(repeat_count)

    def play_alert_sound(
        self, repeat_count: int | None = None,
        playback_speed: float | None = None,
    ) -> None:
        try:
            volume_db = int(self.alert_volume_db_var.get())
            if repeat_count is None:
                repeat_count = int(self.alert_repeat_var.get())
            interval = float(self.alert_interval_var.get())
            if playback_speed is None:
                playback_speed = float(self.alert_speed_var.get())
            if (
                not -40 <= volume_db <= 0
                or not 1 <= repeat_count <= 20
                or not 0.0 <= interval <= 60.0
                or not 0.25 <= playback_speed <= 4.0
            ):
                raise ValueError
            suffix = f"m{abs(volume_db):02d}" if volume_db < 0 else "0"
            speed_suffix = f"{round(playback_speed * 100):03d}pct"
            sound_path = SOUND_DIR / f"gkey_alert_{suffix}db_single_{speed_suffix}.wav"
            if not sound_path.exists():
                create_alert_sound(sound_path, float(volume_db), playback_speed)
            threading.Thread(
                target=self._play_alert_sequence,
                args=(sound_path, repeat_count, interval, playback_speed),
                daemon=True,
            ).start()
        except (ValueError, tk.TclError):
            messagebox.showwarning(
                "提示音設定錯誤",
                "音量須介於 -40 到 0 dB，次數介於 1 到 20，"
                "間隔介於 0 到 60 秒，倍速介於 0.25 到 4.00。",
                parent=self.root,
            )
        except Exception:
            self._show_copyable_error("提示音播放失敗", traceback.format_exc().strip())

    def _play_alert_sequence(
        self, sound_path: Path, repeat_count: int, interval: float,
        playback_speed: float,
    ) -> None:
        with self.alert_sound_lock:
            for index in range(repeat_count):
                winsound.PlaySound(
                    str(sound_path),
                    winsound.SND_FILENAME | winsound.SND_NODEFAULT,
                )
                if index + 1 < repeat_count and interval > 0:
                    time.sleep(interval / playback_speed)

    def start_recording(self) -> None:
        if self.playing or self.recording:
            return
        if self._selected_hwnd() is None:
            messagebox.showwarning("未選擇視窗", "請先選擇要錄製操作的目標視窗。")
            return
        self.events = []
        self.script_name_var.set("目前腳本：新錄製（尚未儲存）")
        self._refresh_event_table()
        self.recording = True
        self.record_started = time.perf_counter()

        def capture(action: str, key: keyboard.Key | keyboard.KeyCode) -> None:
            if not self.recording or self._hotkey_name(key) in {
                self.start_hotkey, self.stop_hotkey, self.play_hotkey
            }:
                return
            encoded = serialize_key(key)
            if encoded:
                event = KeyEvent(time.perf_counter() - self.record_started, action, encoded)
                self.events.append(event)
                self.root.after(0, self._append_event_row, event)

        self.listener = keyboard.Listener(
            on_press=lambda key: capture("down", key),
            on_release=lambda key: capture("up", key),
        )
        self.listener.start()
        self.record_button.configure(state="disabled")
        self.play_button.configure(state="disabled")
        self._set_state(
            "錄製中",
            f"正在錄製…請切換至目標視窗操作，完成後按 {self.stop_hotkey}。",
        )

    def stop_all(self) -> None:
        was_recording = self.recording
        was_playing = self.playing
        self.recording = False
        self.stop_event.set()
        if self.listener:
            self.listener.stop()
            self.listener = None
        if was_recording:
            self._normalize_events()
            self._refresh_event_table()
            self._set_state("就緒", f"錄製完成，共 {len(self.events)} 個事件。")
        elif was_playing:
            self._set_state("就緒", "播放停止。")
        self.record_button.configure(state="normal")
        if not was_playing:
            self.play_button.configure(state="normal")
        self._update_count()

    def _normalize_events(self) -> None:
        if self.events:
            first = self.events[0].time
            for event in self.events:
                event.time = round(max(0.0, event.time - first), 6)

    def _update_count(self) -> None:
        if not self.events:
            self.count_var.set("尚未錄製事件")
            return
        duration = self.events[-1].time
        self.count_var.set(f"{len(self.events)} 個事件，長度 {duration:.2f} 秒")

    def _append_event_row(self, event: KeyEvent) -> None:
        action = "按下" if event.action == "down" else "放開"
        item = self.event_table.insert(
            "", "end", values=(f"{event.time:.3f}", action, display_key(event.key))
        )
        self.event_table.see(item)
        self._update_count()

    def _refresh_event_table(self) -> None:
        self.event_table.delete(*self.event_table.get_children())
        for event in self.events:
            action = "按下" if event.action == "down" else "放開"
            self.event_table.insert(
                "", "end", values=(f"{event.time:.3f}", action, display_key(event.key))
            )
        children = self.event_table.get_children()
        if children:
            self.event_table.see(children[-1])
        self._update_count()

    def clear_events(self) -> None:
        if self.recording or self.playing:
            return
        self.events = []
        self.script_name_var.set("目前腳本：尚未載入")
        self._refresh_event_table()
        self.status_var.set("腳本已清除。")

    def save_script(self) -> None:
        if not self.events:
            messagebox.showinfo("沒有腳本", "請先錄製或載入腳本。")
            return
        remembered_path = Path(self.last_script_path) if self.last_script_path else None
        initial_dir = (
            remembered_path.parent
            if remembered_path and remembered_path.parent.exists()
            else Path.cwd()
        )
        path = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".json",
            initialdir=str(initial_dir),
            initialfile=(remembered_path.name if remembered_path else ""),
            filetypes=[("Game Evolution 腳本", "*.json")],
        )
        if not path:
            return
        payload = {"version": 1, "events": [asdict(event) for event in self.events]}
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.last_script_path = str(Path(path).resolve())
        self.save_project(notify=False)
        self.script_name_var.set(f"目前腳本：{Path(path).name}")
        self.status_var.set(f"已儲存：{path}")

    def load_script(self) -> None:
        if self.recording or self.playing:
            active = "錄製" if self.recording else "播放"
            messagebox.showwarning(
                "目前無法載入",
                f"Game Evolution 正在{active}中，請先停止後再載入腳本。",
                parent=self.root,
            )
            return
        self._set_state("選擇檔案", "正在開啟腳本選擇視窗…")
        self.root.lift()
        self.root.focus_force()
        self.root.attributes("-topmost", True)
        self.root.update_idletasks()
        path = ""
        remembered_path = Path(self.last_script_path) if self.last_script_path else None
        initial_dir = (
            remembered_path.parent
            if remembered_path and remembered_path.parent.exists()
            else Path.cwd()
        )
        try:
            path = filedialog.askopenfilename(
                parent=self.root,
                title="載入 Game Evolution 腳本",
                initialdir=str(initial_dir),
                initialfile=(remembered_path.name if remembered_path else ""),
                filetypes=[("Game Evolution 腳本", "*.json"), ("所有檔案", "*.*")],
            )
        except tk.TclError as exc:
            self._set_state("錯誤", f"無法開啟檔案選擇視窗：{exc}")
            messagebox.showerror(
                "無法開啟檔案選擇視窗", str(exc), parent=self.root
            )
            return
        finally:
            self.root.attributes("-topmost", False)
            self.root.lift()
            self.root.focus_force()
        if not path:
            self._set_state("就緒", "已取消載入腳本。")
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            raw_events = data["events"]
            events = [KeyEvent(float(e["time"]), str(e["action"]), str(e["key"])) for e in raw_events]
            if any(e.action not in ("down", "up") or e.time < 0 for e in events):
                raise ValueError("事件內容不合法")
            for event in events:
                deserialize_key(event.key)
            self.events = events
            self.last_script_path = str(Path(path).resolve())
            self.save_project(notify=False)
            self.script_name_var.set(f"目前腳本：{Path(path).name}")
            self._refresh_event_table()
            self.status_var.set(f"已載入：{path}")
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("載入失敗", f"腳本格式不正確：\n{exc}")

    def start_playback(self) -> None:
        if self.recording or self.playing:
            return
        hwnd = self._selected_hwnd()
        if hwnd is None:
            messagebox.showwarning("未選擇視窗", "請先選擇目標視窗。")
            return
        if not self.events:
            messagebox.showinfo("沒有腳本", "請先錄製或載入腳本。")
            return
        try:
            repeats = max(1, int(self.repeat_var.get()))
            speed_min = float(self.speed_min_var.get())
            speed_max = float(self.speed_max_var.get())
            press_jitter_sec = float(self.press_jitter_var.get())
            release_jitter_sec = float(self.release_jitter_var.get())
            seed = int(self.seed_var.get())
            reverse_even = bool(self.reverse_even_var.get())
            if (
                speed_min <= 0
                or speed_max <= 0
                or speed_min > speed_max
                or not 0.0 <= press_jitter_sec <= 0.050
                or not 0.0 <= release_jitter_sec <= 0.050
                or seed < 0
            ):
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showerror(
                "設定錯誤",
                "速度必須為正數且下限不可大於上限；按下與放開抖動必須介於 0.000～0.050 秒。",
            )
            return

        self.playing = True
        self.stop_event.clear()
        self.record_button.configure(state="disabled")
        self.play_button.configure(state="disabled")
        self._set_state("準備播放", "正在切換至指定視窗…")
        threading.Thread(
            target=self._play_worker,
            args=(
                hwnd, repeats, speed_min, speed_max,
                press_jitter_sec, release_jitter_sec, seed, reverse_even,
            ),
            daemon=True,
        ).start()

    def _play_worker(
        self, hwnd: int, repeats: int, speed_min: float, speed_max: float,
        press_jitter_sec: float, release_jitter_sec: float, seed: int,
        reverse_even: bool,
    ) -> None:
        held: set[str] = set()
        rng = random.Random(seed)
        largest_error_ms = 0.0
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
            if not activate_window(hwnd):
                raise RuntimeError("無法將目標視窗切換至前景。請確認視窗仍存在，或以相同權限執行本工具。")
            self.ui_queue.put(("playing", f"目標視窗已啟用，1 秒後開始播放；按 {self.stop_hotkey} 可停止。"))
            if self.stop_event.wait(1.0):
                return
            for cycle in range(repeats):
                reverse_this_cycle = reverse_even and (cycle + 1) % 2 == 0
                speed = (
                    speed_min if speed_min == speed_max
                    else rng.uniform(speed_min, speed_max)
                )
                jitter_text = (
                    f"，按下 ±{press_jitter_sec:.3f} 秒、放開 ±{release_jitter_sec:.3f} 秒"
                    if press_jitter_sec or release_jitter_sec else "，未啟用抖動"
                )
                self.ui_queue.put((
                    "status",
                    f"正在播放第 {cycle + 1}/{repeats} 次，速度 {speed:.3f}×"
                    f"{jitter_text}（種子 {seed}）"
                    f"{'，左右相反' if reverse_this_cycle else ''}…",
                ))
                scheduled_time = 0.0
                cycle_started = time.perf_counter()
                for event in self.events:
                    playback_key = (
                        reverse_horizontal_key(event.key) if reverse_this_cycle else event.key
                    )
                    jitter_limit = (
                        press_jitter_sec if event.action == "down" else release_jitter_sec
                    )
                    jitter = (
                        rng.uniform(-jitter_limit, jitter_limit)
                        if jitter_limit else 0.0
                    )
                    event_time = max(0.0, event.time / speed + jitter)
                    scheduled_time = max(scheduled_time, event_time)
                    deadline = cycle_started + scheduled_time
                    if precise_wait_until(deadline, self.stop_event):
                        return
                    if int(user32.GetForegroundWindow()) != hwnd:
                        raise RuntimeError("焦點已離開指定視窗，為避免誤輸入，播放已停止。")
                    largest_error_ms = max(
                        largest_error_ms, abs(time.perf_counter() - deadline) * 1000.0
                    )
                    if event.action == "down":
                        send_windows_key(playback_key, True)
                        held.add(playback_key)
                    else:
                        send_windows_key(playback_key, False)
                        held.discard(playback_key)
        except Exception as exc:
            self.ui_queue.put(("error", str(exc)))
        finally:
            for key in held:
                try:
                    send_windows_key(key, False)
                except Exception:
                    pass
            ctypes.windll.winmm.timeEndPeriod(1)
            self.playing = False
            result = "播放完成。" if not self.stop_event.is_set() else "播放停止。"
            self.ui_queue.put(("done", f"{result} 最大排程誤差 {largest_error_ms:.3f} ms。"))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, text = self.ui_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(str(text))
                elif kind == "playing":
                    self._set_state("播放中", text)
                elif kind == "error":
                    self._set_state("錯誤", text)
                    self._show_copyable_error("播放停止", text)
                elif kind == "done":
                    self._set_state("就緒", text)
                    self.record_button.configure(state="normal")
                    self.play_button.configure(state="normal")
                elif kind == "detect_result":
                    self.detect_result_var.set(str(text))
                elif kind == "detect_error":
                    message = str(text)
                    summary = message.splitlines()[-1] if message else "未知錯誤"
                    self.detect_result_var.set(f"偵測失敗：{summary}")
                    self._show_copyable_error("偵測失敗", message)
                elif kind == "detect_done":
                    if self.pending_detection_restart:
                        self.pending_detection_restart = False
                        self.monitor_button.configure(
                            text="正在套用新偵測設定…", state="disabled"
                        )
                        self.root.after(50, lambda: self._start_detection(True))
                    else:
                        self.continuous_detection = False
                        self.monitor_button.configure(
                            text="開始持續偵測", state="normal"
                        )
                elif kind == "visual_hits":
                    hits = text if isinstance(text, list) else []
                    for target_type, key, repeat_count, playback_speed, interval in hits:
                        self._flash_detection_card(
                            str(target_type), str(key), int(repeat_count),
                            float(playback_speed), float(interval),
                        )
                elif kind == "template_hits":
                    detected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    keys = text if isinstance(text, list) else []
                    for key in keys:
                        stat = self.template_stats.setdefault(
                            str(key), {
                                "last_detected": "", "count": 0, "alert_repeat": 1,
                            }
                        )
                        stat["last_detected"] = detected_at
                        stat["count"] = int(stat.get("count", 0)) + 1
                    if keys:
                        self._refresh_template_previews()
                        self.save_project(notify=False)
                elif kind == "detection_hit":
                    hit = text if isinstance(text, dict) else {"text": str(text)}
                    hit_text = str(hit.get("text", "偵測命中"))
                    template_name = str(hit.get("template", "圖片"))
                    repeat_count = max(1, min(20, int(hit.get("repeat_count", 1))))
                    playback_speed = max(
                        0.25, min(4.0, float(hit.get("playback_speed", 2.0)))
                    )
                    self.play_alert_sound(repeat_count, playback_speed)
                    if self.playing:
                        self.status_var.set(
                            f"{hit_text}；{template_name} 播放 {repeat_count} 次提示音，"
                            "偵測與腳本繼續執行。"
                        )
                    elif self.recording:
                        self.status_var.set(
                            f"{hit_text}；{template_name} 播放 {repeat_count} 次提示音，"
                            "偵測與錄製繼續進行。"
                        )
                    else:
                        self._set_state(
                            "偵測命中",
                            f"{hit_text}；{template_name} 播放 {repeat_count} 次提示音，"
                            "持續偵測保持運行。",
                        )
                elif kind == "picked_color":
                    self.color_pick_listener = None
                    self.color_var.set(text)
                    self.detect_result_var.set(f"已從螢幕吸取顏色 {text}")
                    self.root.lift()
                    self.root.focus_force()
                elif kind == "pick_cancel":
                    self.color_pick_listener = None
                    self.detect_result_var.set(text)
                    self.root.lift()
                    self.root.focus_force()
                elif kind == "pick_error":
                    self.color_pick_listener = None
                    self.detect_result_var.set("吸色失敗")
                    self.root.lift()
                    self._show_copyable_error("吸色失敗", text)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _on_close(self) -> None:
        self.detection_stop_event.set()
        self.save_project(notify=False)
        if self.color_pick_listener:
            self.color_pick_listener.stop()
        self.stop_all()
        self.safety_listener.stop()
        self.root.destroy()


if __name__ == "__main__":
    if not hasattr(ctypes, "windll"):
        raise SystemExit("此工具僅支援 Windows。")
    main_root = tk.Tk()
    RecorderApp(main_root)
    main_root.mainloop()
