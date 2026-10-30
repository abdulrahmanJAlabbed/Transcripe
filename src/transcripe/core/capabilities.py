"""Environment capability detection.

Transcripe adapts to whatever a machine has installed. This module probes the
available external binaries (FFmpeg, LibreOffice, Poppler, Pandoc), Python
libraries (RapidOCR, EasyOCR, Whisper, pandas…) and GPU support, then exposes
simple feature gates the rest of the app uses to enable/disable actions and
show actionable install hints.
"""
from __future__ import annotations

import shutil
import functools
import subprocess
from dataclasses import dataclass


@dataclass
class Capability:
    key: str
    label: str
    ok: bool
    detail: str = ""
    hint: str = ""
    used_for: str = ""


# ── low-level probes ────────────────────────────────────────────────────────

def _which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _bin_version(path: str | None, args: list[str]) -> str:
    if not path:
        return ""
    try:
        out = subprocess.run([path, *args], capture_output=True, text=True, timeout=10)
        txt = (out.stdout or out.stderr).strip()
        return txt.splitlines()[0] if txt else ""
    except Exception:
        return ""


def _probe_pandoc() -> tuple[bool, str]:
    try:
        import pypandoc
    except Exception:
        return False, "pypandoc not installed"
    try:
        return True, f"pandoc {pypandoc.get_pandoc_version()}"
    except Exception:
        return False, "pandoc binary missing (run pypandoc.download_pandoc())"


def _probe_import(mod: str) -> tuple[bool, str]:
    try:
        m = __import__(mod)
        return True, str(getattr(m, "__version__", "") or "")
    except Exception:
        return False, ""


def _probe_msoffice() -> tuple[bool, str]:
    """MS Office automation (Word/PowerPoint) — Windows/macOS only, needs Office installed."""
    import sys
    if not (sys.platform.startswith("win") or sys.platform == "darwin"):
        return False, "only on Windows/macOS with MS Office"
    try:
        import docx2pdf  # noqa: F401
    except Exception:
        return False, "pip install docx2pdf (requires MS Office)"
    extra = "PowerPoint via COM" if sys.platform.startswith("win") else "PowerPoint via AppleScript"
    return True, f"Word via docx2pdf, {extra}"


def _probe_gpu() -> tuple[bool, str]:
    cuda = False
    detail: list[str] = []
    try:
        import ctranslate2
        n = ctranslate2.get_cuda_device_count()
        if n > 0:
            cuda = True
            detail.append(f"CTranslate2 CUDA×{n}")
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            cuda = True
            detail.append(f"torch CUDA ({torch.cuda.get_device_name(0)})")
        else:
            detail.append("torch CPU-only")
    except Exception:
        pass
    return cuda, "; ".join(detail) or "no GPU detected"


# ── full probe (cached) ─────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def probe() -> dict[str, Capability]:
    caps: dict[str, Capability] = {}

    ff = _which("ffmpeg")
    caps["ffmpeg"] = Capability(
        "ffmpeg", "FFmpeg", bool(ff),
        _bin_version(ff, ["-version"]).replace("ffmpeg version ", "") if ff else "",
        "Install FFmpeg (apt/brew install ffmpeg)", "audio & video")

    so = _which("soffice", "libreoffice")
    caps["libreoffice"] = Capability(
        "libreoffice", "LibreOffice", bool(so), so or "",
        "apt/brew install libreoffice", "documents → PDF (default backend)")

    ms_ok, ms_det = _probe_msoffice()
    caps["msoffice"] = Capability(
        "msoffice", "MS Office", ms_ok, ms_det,
        "Install MS Office + pip install docx2pdf (Windows/macOS)",
        "documents → PDF (high-fidelity, .docx/.pptx)")

    pp = _which("pdftoppm")
    caps["poppler"] = Capability(
        "poppler", "Poppler", bool(pp), pp or "",
        "apt install poppler-utils / brew install poppler", "PDF → images / PDF OCR")

    node = _which("node")
    caps["node"] = Capability(
        "node", "Node.js", bool(node),
        _bin_version(node, ["--version"]) if node else "",
        "Install Node.js (https://nodejs.org)", "3D model conversion (assimp + glTF-Transform)")

    chrome = _which("chromium", "chromium-browser", "google-chrome",
                    "google-chrome-stable", "chrome", "brave-browser", "msedge")
    caps["chromium"] = Capability(
        "chromium", "Chromium/Chrome", bool(chrome), chrome or "",
        "Install Chromium or Chrome (or use WeasyPrint fallback)",
        "HTML → PDF (pixel-perfect print, editable-HTML round-trip)")

    ok, det = _probe_pandoc()
    caps["pandoc"] = Capability(
        "pandoc", "Pandoc", ok, det,
        'python -c "import pypandoc; pypandoc.download_pandoc()"', "document format conversion")

    lib_specs = [
        ("rapidocr", "RapidOCR", "OCR (primary engine)"),
        ("easyocr", "EasyOCR", "OCR (fallback / extra scripts)"),
        ("faster_whisper", "faster-whisper", "speech transcription"),
        ("pypdf", "pypdf", "PDF text / split / merge"),
        ("pdf2image", "pdf2image", "PDF → images / PDF OCR"),
        ("pandas", "pandas", "data (csv/excel/json)"),
        ("openpyxl", "openpyxl", "Excel read/write"),
        ("yaml", "PyYAML", "YAML conversion"),
        ("PIL", "Pillow", "image operations"),
        ("charset_normalizer", "charset-normalizer", "encoding detection / repair"),
        ("py7zr", "py7zr", "7-Zip archives"),
        ("rarfile", "rarfile", "RAR archives (needs 'unar' or 'unrar' binary)"),
        ("trimesh", "trimesh", "3D mesh export (obj/stl/ply)"),
        ("fitz", "PyMuPDF", "PDF editing (edit-in-browser, find/replace, images)"),
        ("pdf2docx", "pdf2docx", "PDF → Word (layout-preserving)"),
        ("ocrmypdf", "OCRmyPDF", "scanned PDF → searchable PDF"),
        ("pyarrow", "PyArrow", "Parquet read/write"),
        ("weasyprint", "WeasyPrint", "Markdown/HTML → styled PDF"),
    ]
    for mod, label, used in lib_specs:
        ok, ver = _probe_import(mod)
        caps[mod] = Capability(mod, label, ok, ver, f"pip install {label}", used)

    # RAR also needs an external extraction binary (unar/unrar/bsdtar).
    if caps["rarfile"].ok and not _which("unar", "unrar", "bsdtar"):
        caps["rarfile"].ok = False
        caps["rarfile"].detail = "installed, but no unar/unrar binary found"
        caps["rarfile"].hint = "apt/brew install unar (or install unrar)"

    # OCRmyPDF also needs the tesseract binary.
    if caps["ocrmypdf"].ok and not _which("tesseract"):
        caps["ocrmypdf"].ok = False
        caps["ocrmypdf"].detail = "installed, but tesseract binary missing"
        caps["ocrmypdf"].hint = "apt install tesseract-ocr / brew install tesseract"

    gpu_ok, gpu_det = _probe_gpu()
    caps["gpu"] = Capability(
        "gpu", "GPU acceleration", gpu_ok, gpu_det,
        "Install a CUDA build of ctranslate2 (and torch for EasyOCR)",
        "faster transcription & OCR")

    return caps


# ── feature gates ───────────────────────────────────────────────────────────

# feature -> required capability keys (ocr/pdf_ocr handled specially)
FEATURES: dict[str, list[str]] = {
    "transcribe":    ["faster_whisper", "ffmpeg"],
    "media_convert": ["ffmpeg"],
    "doc_to_pdf":    ["libreoffice"],
    "pandoc":        ["pandoc"],
    "pdf_text":      ["pypdf"],
    "pdf_images":    ["poppler", "pdf2image"],
    "image_ops":     ["PIL"],
    "data_basic":    ["pandas"],
    "data_excel":    ["pandas", "openpyxl"],
    "data_yaml":     ["yaml"],
    "data_xml":      [],  # stdlib only
    "archive":       [],  # zip/tar/gz via stdlib — always available
    "archive_7z":    ["py7zr"],
    "archive_rar":   ["rarfile"],
    "fix_encoding":  [],  # charset-normalizer optional, has a pure-python fallback
    "model3d":       ["node"],       # web GLB via bundled Node toolchain
    "model3d_mesh":  ["node", "trimesh"],  # obj/stl/ply export
    "pdf_edit":      ["fitz"],       # edit-in-browser, find/replace, image extract
    "pdf_docx":      ["pdf2docx"],   # layout-preserving PDF → Word
    "pdf_searchable": ["ocrmypdf"],  # scanned → searchable PDF (tesseract-gated in probe)
    "data_parquet":  ["pandas", "pyarrow"],
    "subtitles":     [],             # SRT/VTT/ASS — pure python, always available
    "md_pdf":        ["weasyprint"],  # styled Markdown/HTML → PDF (LibreOffice fallback)
}


def has(*keys: str) -> bool:
    caps = probe()
    return all(caps.get(k) is not None and caps[k].ok for k in keys)


def ocr_backend() -> str | None:
    caps = probe()
    if caps["rapidocr"].ok:
        return "rapidocr"
    if caps["easyocr"].ok:
        return "easyocr"
    return None


def can(feature: str) -> bool:
    if feature == "ocr":
        return ocr_backend() is not None
    if feature == "pdf_ocr":
        return has("poppler", "pdf2image") and ocr_backend() is not None
    if feature == "doc_to_pdf":
        return has("libreoffice") or has("msoffice")
    return has(*FEATURES.get(feature, []))


def doc_pdf_backend(ext: str | None = None) -> str | None:
    """Pick the best available document→PDF backend for a file extension."""
    caps = probe()
    office_exts = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"}
    if ext and ext.lower() in office_exts and caps["msoffice"].ok:
        return "msoffice"
    if caps["libreoffice"].ok:
        return "libreoffice"
    if caps["msoffice"].ok:
        return "msoffice"
    return None


def missing_for(feature: str) -> list[Capability]:
    """Which capabilities are missing for a feature (for friendly error hints)."""
    caps = probe()
    if feature == "ocr":
        return [] if ocr_backend() else [caps["rapidocr"]]
    if feature == "pdf_ocr":
        need = ["poppler", "pdf2image"]
        miss = [caps[k] for k in need if not caps[k].ok]
        if not ocr_backend():
            miss.append(caps["rapidocr"])
        return miss
    if feature == "doc_to_pdf":
        return [] if (caps["libreoffice"].ok or caps["msoffice"].ok) else [caps["libreoffice"]]
    return [caps[k] for k in FEATURES.get(feature, []) if not caps[k].ok]


def require(feature: str) -> None:
    """Raise a helpful error if a feature's dependencies are missing."""
    if can(feature):
        return
    miss = missing_for(feature)
    names = ", ".join(m.label for m in miss) or feature
    hints = "; ".join(dict.fromkeys(m.hint for m in miss if m.hint))
    raise RuntimeError(f"Missing dependency for this action: {names}. Fix: {hints}")
