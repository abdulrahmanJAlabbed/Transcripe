"""Unified OCR engine.

Primary engine: RapidOCR (PaddleOCR models via ONNXRuntime) — fast, accurate,
lightweight, good multilingual (Latin + Turkish + numbers + Chinese) out of the box.
Fallback engine: EasyOCR — broader script coverage (Arabic, Cyrillic, CJK, Indic…)
via explicit language packs.

Both are imported lazily so CLI startup stays instant.
"""
from __future__ import annotations
from pathlib import Path
from itertools import groupby

# Cached engine instances
_rapid = None
_easy_readers: dict[tuple, object] = {}

# Languages RapidOCR's default model handles well (Latin scripts + numbers).
_RAPID_OK = {
    None, "en", "tr", "latin", "fr", "de", "es", "it", "pt", "nl",
    "sv", "no", "da", "fi", "pl", "cs", "ro", "hu", "id", "ms", "vi",
}


def _get_rapid():
    global _rapid
    if _rapid is None:
        # `rapidocr` 3.x. Its predecessor `rapidocr-onnxruntime` stopped at
        # 1.2.3 and has no build for current Pythons, so the requirement on it
        # could never be met and took every other dependency down with it.
        from rapidocr import RapidOCR
        _rapid = RapidOCR()
    return _rapid


def _rapid_read(source) -> list[tuple]:
    """[(box, text, score)], box being four [x, y] corners, as RapidOCR 1.x
    returned them; 3.x answers with an object of parallel arrays instead."""
    out = _get_rapid()(source)
    if out.boxes is None or not out.txts:
        return []
    return list(zip(out.boxes.tolist(), out.txts, out.scores))


def _get_easy(langs: tuple):
    if langs not in _easy_readers:
        import easyocr
        gpu = False
        try:
            import torch
            gpu = torch.cuda.is_available()
        except Exception:
            gpu = False
        _easy_readers[langs] = easyocr.Reader(list(langs), gpu=gpu)
    return _easy_readers[langs]


def _rapid_to_text(result) -> str:
    """Reconstruct reading order from RapidOCR boxes: group by line (y), sort by x."""
    if not result:
        return ""
    rows = []
    for box, text, _score in result:
        top = min(p[1] for p in box)
        left = min(p[0] for p in box)
        rows.append((round(top / 12), left, text))  # coarse y-bucket → line
    rows.sort()
    lines = []
    for _, grp in groupby(rows, key=lambda r: r[0]):
        parts = sorted(grp, key=lambda r: r[1])
        lines.append(" ".join(p[2] for p in parts))
    return "\n".join(lines)


def _use_rapid(langs) -> bool:
    """Pick RapidOCR when languages are covered and it's installed."""
    if langs and any(l not in _RAPID_OK for l in langs):
        return False
    try:
        import rapidocr  # noqa: F401
        return True
    except Exception:
        return False


def available_engine(langs=None) -> str:
    """Return which engine would be used ('rapidocr' or 'easyocr')."""
    return "rapidocr" if _use_rapid(langs) else "easyocr"


def ocr_boxes(image, langs: list[str] | None = None) -> list[tuple]:
    """OCR with positions: returns [(x0, y0, x1, y1, text), ...].

    `image` is a PIL Image or a path. Used by the PDF editor to place
    editable overlays exactly where the original text sits.
    """
    import numpy as np
    arr = np.array(image) if not isinstance(image, (str, Path)) else str(image)

    lang_tuple = tuple(langs) if langs else None
    out = []
    if _use_rapid(langs):
        for box, text, score in _rapid_read(arr):
            if not text.strip():
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out.append((min(xs), min(ys), max(xs), max(ys), text))
    else:
        reader = _get_easy(lang_tuple or ("en",))
        # paragraph=False → tight per-line boxes
        for box, text, conf in reader.readtext(arr, detail=1, paragraph=False):
            if conf < 0.15 or not text.strip():
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out.append((min(xs), min(ys), max(xs), max(ys), text))
    return out


def ocr_image(image_path: Path, langs: list[str] | None = None) -> str:
    """Extract text from an image. `langs` is a list of language codes (e.g. ['en','tr'])."""
    lang_tuple = tuple(langs) if langs else None

    # Preferred engine, with graceful fallback to the other.
    order = ["rapid", "easy"] if _use_rapid(langs) else ["easy", "rapid"]
    last_err = None
    for eng in order:
        try:
            if eng == "rapid":
                return _rapid_to_text(_rapid_read(str(image_path)))
            else:
                reader = _get_easy(lang_tuple or ("en",))
                return "\n".join(reader.readtext(str(image_path), detail=0))
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"OCR failed (no engine available): {last_err}")
