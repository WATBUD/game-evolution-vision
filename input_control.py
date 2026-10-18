from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import threading
import time

from pynput import keyboard


INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
EXTENDED_VKS = {
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,
    0x2D, 0x2E, 0x5B, 0x5C, 0xA3, 0xA5,
}
user32 = ctypes.windll.user32


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


@dataclass
class KeyEvent:
    time: float
    action: str
    key: str


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
