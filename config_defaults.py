"""Validated defaults; user project settings take precedence."""
import json
import math
from pathlib import Path


BUILTIN = {
    "playback": {"repeat": 40, "speed_min": 0.8, "speed_max": 1.2,
                 "press_jitter": 0.01, "release_jitter": 0.01, "seed": 12345,
                 "reverse_even": False},
    "detection": {"mode": "ALL", "similarity": 0.85, "ocr_similarity": 0.7,
                  "image_scan_interval": 0.5, "text_scan_interval": 0.5,
                  "color": "#FF0000", "color_tolerance": 10},
    "alert": {"volume_db": -6, "repeat": 1, "interval": 0.0,
              "speed": 2.0, "cooldown": 50.0, "text_cooldown": 10.0},
}


def load_defaults(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    result = {section: values.copy() for section, values in BUILTIN.items()}
    if not isinstance(raw, dict):
        return result
    for section, values in result.items():
        supplied = raw.get(section, {})
        if not isinstance(supplied, dict):
            continue
        for key, fallback in values.items():
            value = supplied.get(key, fallback)
            if isinstance(fallback, bool):
                valid = isinstance(value, bool)
            elif isinstance(fallback, (int, float)):
                valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                         and math.isfinite(value))
                if valid:
                    lower, upper = 0, 1000000
                    if "similarity" in key: lower, upper = 0, 1
                    elif "scan_interval" in key: lower, upper = 0.1, 60
                    elif "cooldown" in key: lower, upper = 0, 3600
                    elif key == "repeat": lower, upper = 1, 40
                    elif "speed" in key: lower, upper = 0.25, 4
                    elif key == "volume_db": lower, upper = -60, 0
                    elif key == "interval": lower, upper = 0, 60
                    valid = lower <= value <= upper
                if valid and isinstance(fallback, int):
                    valid = value == int(value)
                    value = int(value)
            else:
                valid = isinstance(value, str)
                if key == "mode": valid = value in ("ALL", "文字", "圖片")
                if key == "color":
                    try: valid = len(value) == 7 and value.startswith("#") and int(value[1:], 16) >= 0
                    except (TypeError, ValueError): valid = False
            if valid:
                values[key] = value
    if result["playback"]["speed_min"] > result["playback"]["speed_max"]:
        for key in ("speed_min", "speed_max"):
            result["playback"][key] = BUILTIN["playback"][key]
    return result
