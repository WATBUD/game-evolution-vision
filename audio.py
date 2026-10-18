from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


ALERT_PLAYBACK_SPEED = 2.0
ALERT_BASE_DURATION = 0.90


def create_alert_sound(
    path: Path, volume_db: float, playback_speed: float = ALERT_PLAYBACK_SPEED
) -> None:
    """Create one clear bell chord rendered at the selected playback speed."""
    sample_rate = 44100
    duration = ALERT_BASE_DURATION / playback_speed
    gain = 10.0 ** (volume_db / 20.0)
    notes = (
        (0.00, 659.25, 0.50),
        (0.00, 830.61, 0.38),
        (0.00, 987.77, 0.30),
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
        sample = math.tanh(sample * 0.82) * 0.88 * gain
        pcm = max(-32767, min(32767, round(sample * 32767)))
        frames.extend(struct.pack("<h", pcm))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)
