"""Environment capability detection tests."""
from transcripe.core import capabilities


def test_probe_returns_all_keys():
    caps = capabilities.probe()
    for key in ("ffmpeg", "libreoffice", "msoffice", "poppler", "pandoc",
                "rapidocr", "easyocr", "faster_whisper",
                "pypdf", "pdf2image", "pandas", "openpyxl", "yaml", "PIL", "gpu"):
        assert key in caps, f"missing capability key: {key}"
        assert isinstance(caps[key].ok, bool)


def test_feature_gates_are_boolean():
    for feature in ("transcribe", "media_convert", "doc_to_pdf", "pandoc",
                    "pdf_text", "pdf_images", "pdf_ocr", "ocr",
                    "image_ops", "data_basic", "data_excel", "data_yaml"):
        assert isinstance(capabilities.can(feature), bool)


def test_doc_backend_selection_is_consistent():
    backend = capabilities.doc_pdf_backend(".docx")
    if capabilities.can("doc_to_pdf"):
        assert backend in ("msoffice", "libreoffice")
    else:
        assert backend is None


def test_require_raises_when_missing(monkeypatch):
    monkeypatch.setattr(capabilities, "can", lambda f: False)
    import pytest
    with pytest.raises(RuntimeError):
        capabilities.require("ocr")
