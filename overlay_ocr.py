"""Local color-aware OCR for animated game overlays."""
import threading

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR


_local = threading.local()


def recognize_overlay(image: Image.Image) -> list[str]:
    engine = getattr(_local, "engine", None)
    if engine is None:
        engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        _local.engine = engine
    # RapidOCR expects BGR. Keep color information lost by grayscale OCR.
    pixels = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
    results, _timings = engine(pixels)
    return [str(text) for _box, text, confidence in (results or []) if confidence >= 0.6]
