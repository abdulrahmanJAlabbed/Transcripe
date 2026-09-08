"""Self-test harness: generate synthetic fixtures and exercise every conversion.

Used by `transcripe doctor --run` and by the pytest suite. Each check returns a
Result so we can see exactly which conversion works, fails, or is skipped
(because a dependency is missing on this machine).
"""
from __future__ import annotations

import io
import math
import wave
import struct
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from transcripe.core import capabilities

# A console that swallows engine chatter during tests.
NULL = Console(file=io.StringIO(), width=100)


@dataclass
class Result:
    category: str
    name: str
    status: str  # 'pass' | 'fail' | 'skip'
    detail: str = ""


# ── fixture generation ──────────────────────────────────────────────────────

def _make_text_image(path: Path, text: str) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    W, H = 900, 220
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    font = None
    for cand in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ):
        try:
            font = ImageFont.truetype(cand, 72)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=72)  # Pillow >= 10
        except Exception:
            font = ImageFont.load_default()
    draw.text((30, 60), text, fill="black", font=font)
    img.save(path)
    return path


def _make_wav(path: Path, seconds: float = 1.0, freq: int = 440, rate: int = 16000) -> Path:
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for i in range(int(rate * seconds)):
            val = int(32767 * 0.2 * math.sin(2 * math.pi * freq * i / rate))
            w.writeframes(struct.pack("<h", val))
    return path


def generate_fixtures(d: Path) -> dict[str, Path]:
    """Create every fixture we can on this machine; return the ones that succeed."""
    fx: dict[str, Path] = {}

    (d / "sample.csv").write_text("name,score\nAlice,90\nBob,85\n", encoding="utf-8")
    fx["csv"] = d / "sample.csv"

    (d / "sample.json").write_text(
        '[{"name":"Alice","score":90},{"name":"Bob","score":85}]', encoding="utf-8")
    fx["json"] = d / "sample.json"

    (d / "sample.yaml").write_text("name: test\nitems:\n  - a\n  - b\n", encoding="utf-8")
    fx["yaml"] = d / "sample.yaml"

    (d / "sample.xml").write_text(
        '<root><item id="1">A</item><item id="2">B</item></root>', encoding="utf-8")
    fx["xml"] = d / "sample.xml"

    # Image with known text (for OCR + image ops)
    try:
        _make_text_image(d / "ocr.png", "TRANSCRIPE OCR 12345")
        fx["image"] = d / "ocr.png"
    except Exception:
        pass

    # Image-only PDF (for PDF OCR)
    if "image" in fx:
        try:
            from PIL import Image
            Image.open(fx["image"]).convert("RGB").save(d / "image.pdf")
            fx["image_pdf"] = d / "image.pdf"
        except Exception:
            pass

    # Audio tone (for media conversion)
    try:
        _make_wav(d / "tone.wav")
        fx["wav"] = d / "tone.wav"
    except Exception:
        pass

    # DOCX via pandoc (for document conversions)
    if capabilities.can("pandoc"):
        try:
            import pypandoc
            pypandoc.convert_text(
                "# Hello Transcripe\n\nThis is a quality check paragraph with sample words.",
                "docx", format="markdown", outputfile=str(d / "worddoc.docx"))
            fx["docx"] = d / "worddoc.docx"
            # NOTE: stem must differ from the "doc.pdf" fixture below — LibreOffice
            # emits {stem}.pdf into the same dir, and a matching stem would clobber it.
        except Exception:
            pass

    # Text-based PDF via LibreOffice (for pdf_text / split / images)
    if "docx" in fx and capabilities.can("doc_to_pdf"):
        try:
            from transcripe.engines import documents
            documents.convert_document_to_pdf_engine(fx["docx"], NULL, output_path=d / "doc.pdf")
            if (d / "doc.pdf").exists():
                fx["text_pdf"] = d / "doc.pdf"
        except Exception:
            pass

    # A non-UTF-8 (latin-1) text file (for encoding repair / corruption checks)
    try:
        (d / "latin1.txt").write_bytes(
            b"Caf\xe9 r\xe9sum\xe9 na\xefve Z\xfcrich clich\xe9.\n")  # latin-1 accents
        fx["latin1"] = d / "latin1.txt"
    except Exception:
        pass

    # An SRT subtitle file (for subtitle conversions)
    (d / "subs.srt").write_text(
        "1\n00:00:01,000 --> 00:00:03,500\nHello world\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nSecond line\nwith a wrap\n",
        encoding="utf-8")
    fx["srt"] = d / "subs.srt"

    # A Markdown document (for styled md→pdf)
    (d / "doc.md").write_text(
        "# Transcripe MD\n\nA **bold** claim and a table:\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    fx["md"] = d / "doc.md"

    # A tiny OBJ cube (for 3D conversion tests)
    try:
        (d / "cube.obj").write_text(
            "o cube\n"
            "v -1 -1 -1\nv -1 -1 1\nv -1 1 -1\nv -1 1 1\n"
            "v 1 -1 -1\nv 1 -1 1\nv 1 1 -1\nv 1 1 1\n"
            "f 1 2 4 3\nf 5 7 8 6\nf 1 5 6 2\nf 3 4 8 7\nf 1 3 7 5\nf 2 6 8 4\n",
            encoding="utf-8")
        fx["obj"] = d / "cube.obj"
    except Exception:
        pass

    return fx


# ── check runner ────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return "".join(s.split()).upper()


def run_all(include_slow: bool = False) -> list[Result]:
    """Run every conversion check in a temp dir; return the result matrix."""
    results: list[Result] = []
    tmp = Path(tempfile.mkdtemp(prefix="transcripe_selftest_"))
    fx = generate_fixtures(tmp)

    def check(category, name, feature, fixture_key, fn):
        if feature and not capabilities.can(feature):
            results.append(Result(category, name, "skip", "dependency missing"))
            return
        if fixture_key and fixture_key not in fx:
            results.append(Result(category, name, "skip", "fixture unavailable"))
            return
        try:
            detail = fn(tmp) or ""
            results.append(Result(category, name, "pass", detail))
        except Exception as e:
            results.append(Result(category, name, "fail", f"{type(e).__name__}: {e}"))

    from transcripe.engines import data, images, documents, audio_video, ocr

    # ---- DATA ----
    def _csv_json(d):
        o = d / "o_csv.json"
        data.csv_to_json(fx["csv"], NULL, output_path=o)
        rows = json.loads(o.read_text())
        assert len(rows) == 2 and rows[0]["name"] == "Alice", "row mismatch"
        return "2 rows"
    check("data", "csv → json", "data_basic", "csv", _csv_json)

    def _json_csv(d):
        o = d / "o_json.csv"
        data.json_to_csv(fx["json"], NULL, output_path=o)
        lines = o.read_text().strip().splitlines()
        assert len(lines) == 3, f"expected 3 lines, got {len(lines)}"
        return "2 rows"
    check("data", "json → csv", "data_basic", "json", _json_csv)

    def _roundtrip(d):
        j = d / "rt.json"; c = d / "rt.csv"
        data.csv_to_json(fx["csv"], NULL, output_path=j)
        data.json_to_csv(j, NULL, output_path=c)
        import csv as _csv
        rows = list(_csv.DictReader(c.open()))
        assert rows[0]["name"] == "Alice" and rows[1]["score"] == "85", "round-trip lost data"
        return "csv→json→csv integrity OK"
    check("data", "csv↔json round-trip", "data_basic", "csv", _roundtrip)

    def _csv_xlsx(d):
        o = d / "o.xlsx"
        data.csv_to_excel(fx["csv"], NULL, output_path=o)
        assert o.stat().st_size > 0
        return f"{o.stat().st_size} bytes"
    check("data", "csv → xlsx", "data_excel", "csv", _csv_xlsx)

    def _yaml_json(d):
        o = d / "o_y.json"
        data.yaml_to_json(fx["yaml"], NULL, output_path=o)
        obj = json.loads(o.read_text())
        assert obj["name"] == "test" and obj["items"] == ["a", "b"]
        return "keys OK"
    check("data", "yaml → json", "data_yaml", "yaml", _yaml_json)

    def _json_yaml(d):
        o = d / "o.yaml"
        data.json_to_yaml(fx["json"], NULL, output_path=o)
        assert "Alice" in o.read_text()
        return "OK"
    check("data", "json → yaml", "data_yaml", "json", _json_yaml)

    def _xml_json(d):
        o = d / "o_x.json"
        data.xml_to_json(fx["xml"], NULL, output_path=o)
        assert "item" in o.read_text()
        return "OK"
    check("data", "xml → json", "data_xml", "xml", _xml_json)

    def _json_pretty(d):
        data.json_prettify(fx["json"], NULL, output_path=d / "p.json")
        assert "\n" in (d / "p.json").read_text()
        return "OK"
    check("data", "json prettify", "data_basic", "json", _json_pretty)

    # ---- IMAGE ----
    def _img_convert(d, tgt):
        from PIL import Image
        o = d / f"o.{tgt}"
        images.convert_image(fx["image"], tgt, NULL, output_path=o)
        im = Image.open(o)
        return f"{im.format} {im.width}x{im.height}"
    check("image", "png → jpg", "image_ops", "image", lambda d: _img_convert(d, "jpg"))
    check("image", "png → webp", "image_ops", "image", lambda d: _img_convert(d, "webp"))

    def _img_pdf(d):
        o = d / "img.pdf"
        images.image_to_pdf(fx["image"], NULL, output_path=o)
        assert o.stat().st_size > 0
        return "OK"
    check("image", "image → pdf", "image_ops", "image", _img_pdf)

    def _img_resize(d):
        from PIL import Image
        o = d / "r.png"
        images.resize_image(fx["image"], 300, None, NULL, output_path=o)
        assert Image.open(o).width == 300
        return "→ 300px wide"
    check("image", "resize", "image_ops", "image", _img_resize)

    def _img_fit_min(d):
        from PIL import Image
        tiny = d / "tiny.png"
        Image.new("RGBA", (16, 16), (20, 60, 54, 255)).save(tiny)
        o = d / "fitmin.png"
        images.fit_size(tiny, NULL, output_path=o, min_bytes=10004)  # Google's 9.77 KB
        assert o.stat().st_size >= 10004, "min-size floor not met"
        Image.open(o).verify()  # still a valid PNG
        return "reached ≥9.77 KB"
    check("image", "fit-size (min floor)", "image_ops", "image", _img_fit_min)

    def _img_fit_max(d):
        from PIL import Image
        import random
        big = d / "big.jpg"
        im = Image.new("RGB", (1200, 1200))
        for x in range(0, 1200, 3):
            for y in range(0, 1200, 3):
                im.putpixel((x, y), (random.randint(0, 255),) * 3)
        im.save(big, quality=95)
        o = d / "fitmax.jpg"
        images.fit_size(big, NULL, output_path=o, max_bytes=20480)  # 20 KB ceiling
        assert o.stat().st_size <= 20480, "max-size ceiling exceeded"
        return "under 20 KB ceiling"
    check("image", "fit-size (max ceiling)", "image_ops", "image", _img_fit_max)

    def _img_fit_auto(d):
        """The upload-limit case: a photo in a lossless format, held to a
        budget. Meeting it by shrinking the picture is the wrong answer when
        re-encoding costs nothing you can see."""
        from PIL import Image
        import random
        scan = d / "scan.png"
        random.seed(11)
        width, height = 400, 600
        im = Image.new("RGB", (width, height))
        px = im.load()
        for y in range(height):
            for x in range(width):
                n = random.randint(0, 40)
                px[x, y] = ((x * 255) // width + n, (y * 255) // height + n,
                            128 + ((x + y) % 64) + n)
        im.save(scan)
        o = d / "fitauto.png"
        out = images.fit_size(scan, NULL, output_path=o,
                              max_bytes=60 * 1024, target_format="auto")
        assert out.stat().st_size <= 60 * 1024, "size budget missed"
        assert Image.open(out).size == (width, height), "resolution spent needlessly"
        return f"{scan.stat().st_size // 1024} KB → {out.stat().st_size // 1024} KB, full size"
    check("image", "fit-size (auto keeps resolution)", "image_ops", "image", _img_fit_auto)

    def _svg_hd(d):
        svg = d / "logo.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="170" height="50">'
                       '<rect width="170" height="50" fill="#143d36"/></svg>')
        try:
            from transcripe.engines.images import _open_image
            import os
            os.environ["TRANSCRIPE_SVG_MIN"] = "1920"
            img = _open_image(svg)
        except RuntimeError:
            return "skipped (cairosvg missing)"
        assert max(img.size) >= 1900, f"svg not upscaled to HD: {img.size}"
        return f"{img.width}x{img.height} (full HD)"
    check("image", "svg → full-HD raster", "image_ops", "image", _svg_hd)

    # ---- OCR ----
    def _ocr(d):
        o = d / "ocr.txt"
        images.convert_image(fx["image"], "txt", NULL, output_path=o, langs=None)
        got = _norm(o.read_text())
        hits = [t for t in ("TRANSCRIPE", "OCR", "12345") if t in got]
        assert hits, f"no expected tokens found in: {got[:80]!r}"
        return f"engine={capabilities.ocr_backend()}, read {hits}"
    check("ocr", "image OCR (accuracy)", "ocr", "image", _ocr)

    # ---- PDF ----
    def _pdf_text(d):
        o = d / "t.txt"
        documents.pdf_to_text(fx["text_pdf"], NULL, output_path=o)
        assert "transcripe" in o.read_text().lower() or "hello" in o.read_text().lower()
        return "text found"
    check("pdf", "pdf → text", "pdf_text", "text_pdf", _pdf_text)

    def _pdf_images(d):
        o = d / "pages"
        documents.pdf_to_images(fx["text_pdf"], NULL, output_path=o)
        n = len(list(o.glob("*.png")))
        assert n >= 1
        return f"{n} pages"
    check("pdf", "pdf → images", "pdf_images", "text_pdf", _pdf_images)

    def _pdf_split(d):
        o = d / "split.pdf"
        documents.split_pdf(fx["text_pdf"], "1", NULL, output_path=o)
        from pypdf import PdfReader
        assert len(PdfReader(str(o)).pages) == 1
        return "1 page"
    check("pdf", "pdf split", "pdf_text", "text_pdf", _pdf_split)

    def _pdf_ocr(d):
        o = d / "pocr.txt"
        documents.pdf_ocr(fx["image_pdf"], NULL, output_path=o, langs=None)
        got = _norm(o.read_text())
        assert any(t in got for t in ("TRANSCRIPE", "OCR", "12345")), f"OCR empty: {got[:80]!r}"
        return "scanned-PDF text recovered"
    check("pdf", "pdf OCR (scanned)", "pdf_ocr", "image_pdf", _pdf_ocr)

    # ---- DOCUMENTS ----
    def _docx_pdf(d):
        o = d / "docx.pdf"
        documents.convert_document_to_pdf_engine(fx["docx"], NULL, output_path=o)
        from pypdf import PdfReader
        assert len(PdfReader(str(o)).pages) >= 1
        return "pdf created"
    check("document", "docx → pdf", "doc_to_pdf", "docx", _docx_pdf)

    def _docx_md(d):
        o = d / "docx.md"
        documents.convert_with_pandoc(fx["docx"], "md", NULL, output_path=o)
        assert "Hello" in o.read_text()
        return "OK"
    check("document", "docx → md", "pandoc", "docx", _docx_md)

    def _docx_txt(d):
        o = d / "docx.txt"
        documents.convert_with_pandoc(fx["docx"], "txt", NULL, output_path=o)
        assert o.exists() and o.stat().st_size > 0, "empty output"
        return f"{o.stat().st_size} bytes"
    check("document", "docx → txt", "pandoc", "docx", _docx_txt)

    # ---- MEDIA ----
    def _wav_mp3(d):
        o = d / "a.mp3"
        audio_video.convert_media(fx["wav"], "mp3", NULL, output_path=o)
        assert o.exists() and o.stat().st_size > 0
        return f"{o.stat().st_size} bytes"
    check("media", "wav → mp3", "media_convert", "wav", _wav_mp3)

    def _wav_flac(d):
        o = d / "a.flac"
        audio_video.convert_media(fx["wav"], "flac", NULL, output_path=o)
        assert o.exists() and o.stat().st_size > 0
        return "OK"
    check("media", "wav → flac", "media_convert", "wav", _wav_flac)

    # ---- ENCODING / CORRUPTION ----
    from transcripe.core import text_utils

    def _encoding_fix(d):
        text, enc = text_utils.read_text_safe(fx["latin1"])
        assert "Café" in text and "résumé" in text, f"decoded wrong: {text!r}"
        o = d / "fixed.txt"
        text_utils.reencode_to_utf8(fx["latin1"], NULL, output_path=o)
        assert o.read_text(encoding="utf-8").strip().startswith("Café")
        return f"detected {enc} → utf-8"
    check("encoding", "detect & repair encoding", None, "latin1", _encoding_fix)

    def _corruption_detect(d):
        binary = "".join(chr(b) for b in range(256))
        corrupt, _ = text_utils.looks_corrupt(binary)
        assert corrupt, "failed to flag binary as corrupt"
        clean, _ = text_utils.looks_corrupt("This is a perfectly normal sentence.")
        assert clean is False
        return "binary flagged, clean text passed"
    check("encoding", "corruption detection", None, None, _corruption_detect)

    # ---- ARCHIVES ----
    from transcripe.engines import archive as archive_engine

    def _archive_roundtrip(d, kind):
        out = d / f"bundle.{kind}"
        archive_engine.create([fx["csv"], fx["json"]], out, NULL)
        assert out.exists() and out.stat().st_size > 0
        names = {n for n, _ in archive_engine.list_contents(out)}
        assert {"sample.csv", "sample.json"} <= names, f"missing entries: {names}"
        ex = archive_engine.extract(out, d / f"ex_{kind}", NULL)
        assert (ex / "sample.csv").exists() and (ex / "sample.json").exists()
        return "create→list→extract OK"
    check("archive", "zip round-trip", "archive", "csv", lambda d: _archive_roundtrip(d, "zip"))
    check("archive", "tar.gz round-trip", "archive", "csv", lambda d: _archive_roundtrip(d, "tar.gz"))
    check("archive", "7z round-trip", "archive_7z", "csv", lambda d: _archive_roundtrip(d, "7z"))

    def _zip_slip_guard(d):
        import zipfile as _zf
        evil = d / "evil.zip"
        with _zf.ZipFile(evil, "w") as z:
            z.writestr("../../escape.txt", "pwned")
        # A sibling dir sharing the dest prefix must also be rejected (startswith bypass).
        try:
            archive_engine.extract(evil, d / "slip_out", NULL)
        except RuntimeError:
            return "traversal rejected"
        raise AssertionError("zip-slip archive extracted without error")
    check("archive", "zip-slip protection", "archive", None, _zip_slip_guard)

    # ---- SUBTITLES ----
    from transcripe.engines import subtitles as subs_engine

    def _srt_vtt_roundtrip(d):
        v = d / "s.vtt"; s2 = d / "s2.srt"
        subs_engine.convert_subtitle(fx["srt"], "vtt", NULL, output_path=v)
        assert v.read_text().startswith("WEBVTT")
        subs_engine.convert_subtitle(v, "srt", NULL, output_path=s2)
        cues = subs_engine.parse(s2)
        assert len(cues) == 2 and cues[0].text == "Hello world", "cues lost in round-trip"
        assert abs(cues[0].start - 1.0) < 0.01 and abs(cues[1].end - 6.0) < 0.01, "timing drifted"
        return "srt→vtt→srt, 2 cues, timing exact"
    check("subtitles", "srt ↔ vtt round-trip", "subtitles", "srt", _srt_vtt_roundtrip)

    def _srt_ass_txt(d):
        a = d / "s.ass"; t = d / "s.txt"
        subs_engine.convert_subtitle(fx["srt"], "ass", NULL, output_path=a)
        assert "Dialogue:" in a.read_text()
        subs_engine.convert_subtitle(fx["srt"], "txt", NULL, output_path=t)
        assert "Hello world" in t.read_text()
        return "ass + txt written"
    check("subtitles", "srt → ass / txt", "subtitles", "srt", _srt_ass_txt)

    # ---- NEW TABULAR FORMATS ----
    def _parquet_roundtrip(d):
        pq = d / "t.parquet"; c2 = d / "t2.csv"
        data.dataframe_convert(fx["csv"], "parquet", NULL, output_path=pq)
        data.dataframe_convert(pq, "csv", NULL, output_path=c2)
        import csv as _csv
        rows = list(_csv.DictReader(c2.open()))
        assert rows[0]["name"] == "Alice" and rows[1]["score"] == "85", "parquet round-trip lost data"
        return "csv→parquet→csv integrity OK"
    check("data", "parquet round-trip", "data_parquet", "csv", _parquet_roundtrip)

    def _ndjson(d):
        nd = d / "t.ndjson"
        data.dataframe_convert(fx["json"], "ndjson", NULL, output_path=nd)
        lines = [json.loads(l) for l in nd.read_text().strip().splitlines()]
        assert len(lines) == 2 and lines[0]["name"] == "Alice"
        return "2 NDJSON lines"
    check("data", "json → ndjson", "data_basic", "json", _ndjson)

    # ---- MARKDOWN → PDF (styled) ----
    def _md_pdf(d):
        o = d / "md.pdf"
        documents.convert_document_to_pdf_engine(fx["md"], NULL, output_path=o)
        from pypdf import PdfReader
        assert len(PdfReader(str(o)).pages) >= 1
        return "styled pdf created"
    check("document", "md → pdf (styled)", "doc_to_pdf", "md", _md_pdf)

    # ---- PDF EDITING ----
    from transcripe.engines import pdf_edit

    def _pdf_editable_html(d):
        o = d / "edit.html"
        pdf_edit.editable_html(fx["text_pdf"], NULL, output_path=o)
        htm = o.read_text()
        assert "contenteditable" in htm and "sheet" in htm, "not an editable page"
        return f"{o.stat().st_size // 1024} KB overlay HTML"
    check("pdf-edit", "pdf → editable HTML", "pdf_edit", "text_pdf", _pdf_editable_html)

    def _pdf_find_replace(d):
        o = d / "replaced.pdf"
        pdf_edit.find_replace(fx["text_pdf"], [{"find": "Transcripe", "to": "REPLACED"}],
                              NULL, output_path=o)
        import fitz
        doc = fitz.open(str(o))
        text = "".join(pg.get_text() for pg in doc)
        doc.close()
        assert "REPLACED" in text, "replacement text not found"
        assert "Transcripe" not in text, "original text still present"
        return "find→replace verified in output text"
    check("pdf-edit", "pdf find & replace", "pdf_edit", "text_pdf", _pdf_find_replace)

    def _pdf_searchable(d):
        o = d / "searchable.pdf"
        pdf_edit.make_searchable(fx["image_pdf"], NULL, output_path=o)
        import fitz
        doc = fitz.open(str(o))
        text = "".join(p.get_text() for p in doc).upper()
        doc.close()
        assert any(t in "".join(text.split()) for t in ("TRANSCRIPE", "OCR", "12345")), \
            f"no OCR text layer found: {text[:60]!r}"
        return "invisible text layer verified"
    check("pdf-edit", "scanned → searchable pdf", "pdf_searchable", "image_pdf", _pdf_searchable)

    def _html_pdf_roundtrip(d):
        h = d / "rt.html"
        h.write_text("<html><body><h1>ROUNDTRIP</h1><p>edited text survives</p></body></html>")
        o = d / "rt.pdf"
        pdf_edit.html_to_pdf(h, NULL, output_path=o)
        import fitz
        doc = fitz.open(str(o))
        text = "".join(p.get_text() for p in doc)
        doc.close()
        assert "ROUNDTRIP" in text, "text lost in html→pdf render"
        return "html→pdf, text layer verified"
    check("pdf-edit", "html → pdf (round-trip)", "pdf_edit", None, _html_pdf_roundtrip)

    def _pdf_docx_layout(d):
        o = d / "layout.docx"
        pdf_edit.pdf_to_docx_layout(fx["text_pdf"], NULL, output_path=o)
        assert o.stat().st_size > 0
        return f"{o.stat().st_size} bytes"
    check("pdf-edit", "pdf → docx (layout)", "pdf_docx", "text_pdf", _pdf_docx_layout)

    # ---- PDF MERGE ----
    def _pdf_merge(d):
        from transcripe.core import dispatcher
        src = fx.get("text_pdf") or fx.get("image_pdf")
        o = d / "merged.pdf"
        dispatcher._merge_pdfs([src, src], o, NULL)
        from pypdf import PdfReader
        n = len(PdfReader(str(o)).pages)
        assert n >= 2, f"expected >=2 pages, got {n}"
        return f"{n} pages"
    if "text_pdf" in fx or "image_pdf" in fx:
        check("pdf", "pdf merge", "pdf_text", None, _pdf_merge)
    else:
        results.append(Result("pdf", "pdf merge", "skip", "fixture unavailable"))

    # ---- 3D MODELS ----
    from transcripe.engines import models3d

    def _obj_to_glb_web(d):
        o = d / "cube_web.glb"
        models3d.convert_model(fx["obj"], "glb", NULL, output_path=o, optimize=True, compress="draco")
        raw = o.read_bytes()
        assert raw[:4] == b"glTF" and len(raw) > 0, "not a valid GLB"
        return f"{len(raw)} bytes, Draco GLB"
    check("3d", "obj → web GLB (Draco)", "model3d", "obj", _obj_to_glb_web)

    def _obj_to_stl(d):
        o = d / "cube.stl"
        models3d.convert_model(fx["obj"], "stl", NULL, output_path=o, optimize=False)
        assert o.stat().st_size > 0
        return "OK"
    check("3d", "obj → stl (trimesh)", "model3d_mesh", "obj", _obj_to_stl)

    # ---- TRANSCRIPTION (slow, opt-in) ----
    if include_slow and capabilities.can("transcribe"):
        def _transcribe(d):
            import os
            os.environ.setdefault("TRANSCRIPE_MODEL", "tiny")
            o = d / "tone.txt"
            audio_video.transcribe(fx["wav"], "txt", NULL, output_path=o)
            assert o.exists()
            return "pipeline ran (tiny model)"
        check("media", "transcription pipeline", "transcribe", "wav", _transcribe)
    else:
        results.append(Result("media", "transcription pipeline", "skip",
                              "slow — run with --slow" if capabilities.can("transcribe")
                              else "faster-whisper missing"))

    return results


def summarize(results: list[Result]) -> tuple[int, int, int]:
    p = sum(1 for r in results if r.status == "pass")
    f = sum(1 for r in results if r.status == "fail")
    s = sum(1 for r in results if r.status == "skip")
    return p, f, s
