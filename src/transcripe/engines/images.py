from pathlib import Path
from rich.console import Console
from transcripe.engines import ocr

_HEIF_REGISTERED = False


def _pil():
    """Lazy Pillow import (images extra) + one-time HEIC/AVIF plugin registration."""
    global _HEIF_REGISTERED
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            "Image operations need Pillow — pip install 'transcripe[images]'") from e
    if not _HEIF_REGISTERED:
        _HEIF_REGISTERED = True
        # Register each opener on its own: pillow-heif ≥ 1.0 dropped
        # register_avif_opener (Pillow reads AVIF natively now), and importing
        # both together used to take HEIC support down with it.
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass
        try:
            from pillow_heif import register_avif_opener
            register_avif_opener()
        except ImportError:
            pass
    return Image


def _open_image(input_path: Path):
    """Open any supported image; rasterizes SVG (Pillow can't read vectors).

    SVG is vector, so its native pixel box is often tiny (e.g. a 170×50 logo).
    Rasterizing at 1× would produce a low-resolution PNG. We upscale so the
    larger side is at least TRANSCRIPE_SVG_MIN px (default 1920 — "full HD"),
    capped at 8× to avoid runaway sizes. Override with TRANSCRIPE_SVG_MIN.
    """
    import os
    Image = _pil()
    if input_path.suffix.lower() == ".svg":
        try:
            import cairosvg
        except ImportError:
            raise RuntimeError(
                "SVG input needs 'cairosvg' — pip install cairosvg "
                "(requires the system cairo library)")
        import io
        # First pass at 1× just to read the intrinsic size.
        base = Image.open(io.BytesIO(cairosvg.svg2png(url=str(input_path))))
        target_min = int(os.environ.get("TRANSCRIPE_SVG_MIN", "1920"))
        longest = max(base.width, base.height)
        # SVG is vector — re-rendering larger is crisp, never blurry — so we can
        # upscale freely to the target (capped at 30× as a runaway guard).
        scale = max(1.0, min(30.0, target_min / longest)) if longest else 1.0
        if scale > 1.0:
            png_bytes = cairosvg.svg2png(
                url=str(input_path),
                output_width=round(base.width * scale),
                output_height=round(base.height * scale))
            return Image.open(io.BytesIO(png_bytes))
        return base
    try:
        img = Image.open(input_path)
    except Exception as e:
        ext = input_path.suffix.lower()
        if ext in (".heic", ".avif"):
            raise RuntimeError(
                f"Cannot open {ext} — install the HEIF plugin: pip install pillow-heif") from e
        raise

    # Phone cameras store the sensor's own orientation and a tag saying how to
    # turn it. Without this a portrait photo converts to a sideways one — and
    # browsers, which honour the tag, would disagree with us about the same file.
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img) or img
    except Exception:
        pass
    return img


def get_reader():
    """Backwards-compatible EasyOCR reader accessor (prefer engines.ocr.ocr_image)."""
    return ocr._get_easy(("en",))

LOSSLESS_SOURCES = {".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


def _save_options(img, target_format: str, source: Path | None = None) -> dict:
    """Encoder settings that keep the picture.

    Pillow defaults to JPEG quality 75 and WebP 80 — fine for a thumbnail,
    visibly soft for someone converting a photo they care about. Quality is
    the point of this tool, so ask for near-transparent settings and keep the
    colour profile that came in. Override the target with TRANSCRIPE_IMAGE_Q.
    """
    import os

    quality = int(os.environ.get("TRANSCRIPE_IMAGE_Q", "95"))
    opts: dict = {}

    # A colour profile is part of the picture: drop it and the colours shift.
    icc = img.info.get("icc_profile")
    if icc:
        opts["icc_profile"] = icc

    fmt = target_format.lower()
    if fmt in ("jpg", "jpeg"):
        opts.update(quality=quality, optimize=True, progressive=True,
                    # 4:4:4 — no chroma subsampling, so fine coloured detail
                    # (text, UI screenshots) survives.
                    subsampling=0)
        exif = img.info.get("exif")
        if exif:
            opts["exif"] = exif
    elif fmt == "webp":
        # Re-encoding something lossless into lossy WebP throws away detail for
        # no reason; keep it lossless when it arrived that way.
        if source and source.suffix.lower() in LOSSLESS_SOURCES:
            opts.update(lossless=True, quality=100, method=6)
        else:
            opts.update(quality=quality, method=6)
    elif fmt == "avif":
        # AVIF beats WebP at the same quality; keep a lossless source lossless.
        if source and source.suffix.lower() in LOSSLESS_SOURCES:
            opts.update(quality=100, lossless=True)
        else:
            opts.update(quality=quality)
    elif fmt == "ico":
        # Icons are a set of sizes, not one image; give the usual ones.
        opts["sizes"] = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    elif fmt == "png":
        opts.update(optimize=True, compress_level=9)
    elif fmt in ("tif", "tiff"):
        opts.update(compression="tiff_lzw")
    return opts


def convert_image(input_path: Path, target_format: str, console: Console,
                  output_path: Path | None = None, langs: list[str] | None = None):
    if target_format == "txt":
        # OCR
        engine = ocr.available_engine(langs)
        lang_label = ", ".join(langs) if langs else "auto"
        with console.status(f"[bold cyan]Running OCR on {input_path.name} ({engine}, {lang_label})…[/bold cyan]"):
            text = ocr.ocr_image(input_path, langs)

            out_path = output_path or input_path.with_suffix(".txt")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)

            console.print(f"[bold green]✓ OCR completed! Saved to {out_path.name}[/bold green] [dim]({len(text)} chars)[/dim]")

    elif target_format in ["png", "jpg", "jpeg", "webp", "bmp", "tiff", "gif", "ico", "avif"]:
        # Format conversion
        with console.status(f"[bold cyan]Converting image to {target_format.upper()}...[/bold cyan]"):
            img = _open_image(input_path)
            # Handle alpha channel if saving to jpeg
            if target_format in ["jpg", "jpeg"] and img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            out_path = output_path or input_path.with_suffix(f".{target_format}")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(out_path, **_save_options(img, target_format, input_path))
            console.print(f"[bold green]✓ Converted! Saved to {out_path.name}[/bold green]")
    else:
        raise ValueError(f"Cannot convert image to {target_format}")


def resize_image(input_path: Path, width: int | None, height: int | None, console: Console, output_path: Path | None = None):
    """Resize an image. If only one dimension is given, the other scales proportionally."""
    img = _open_image(input_path)
    original_w, original_h = img.size

    if width and height:
        new_size = (width, height)
    elif width:
        ratio = width / original_w
        new_size = (width, int(original_h * ratio))
    elif height:
        ratio = height / original_h
        new_size = (int(original_w * ratio), height)
    else:
        console.print("[red]Please specify a width or height.[/red]")
        return

    with console.status(f"[bold cyan]Resizing {input_path.name} ({original_w}x{original_h} → {new_size[0]}x{new_size[1]})…[/bold cyan]"):
        img = img.resize(new_size, _pil().LANCZOS)

        out_path = output_path or (
            input_path.parent
            / f"{input_path.stem}_resized.{_writable(input_path.suffix)}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Handle alpha channel for jpeg
        if out_path.suffix.lower() in (".jpg", ".jpeg") and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Without these, a bare save() re-encodes a JPEG at Pillow's default
        # quality of 75 — so asking for a smaller picture quietly cost you a
        # worse one as well. Same policy the converter uses.
        img.save(out_path, **_save_options(img, out_path.suffix.lstrip("."), input_path))

    console.print(f"[bold green]✓ Resized! {original_w}x{original_h} → {new_size[0]}x{new_size[1]}[/bold green]")
    console.print(f"Saved to: [bold underline]{out_path.name}[/bold underline]")


def compress_image(input_path: Path, quality: int, console: Console, output_path: Path | None = None):
    """Compress an image by reducing quality (1-100). Lower = smaller file."""
    img = _open_image(input_path)
    original_size = input_path.stat().st_size

    out_path = output_path or (input_path.parent / f"{input_path.stem}_compressed{input_path.suffix}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Handle alpha channel for jpeg
    if out_path.suffix.lower() in (".jpg", ".jpeg") and img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    with console.status(f"[bold cyan]Compressing {input_path.name} (quality={quality})…[/bold cyan]"):
        save_kwargs = {"optimize": True}
        ext = out_path.suffix.lower()

        if ext in (".jpg", ".jpeg"):
            save_kwargs["quality"] = quality
        elif ext == ".png":
            save_kwargs["compress_level"] = min(9, max(0, (100 - quality) // 10))
        elif ext == ".webp":
            save_kwargs["quality"] = quality

        img.save(out_path, **save_kwargs)

    new_size = out_path.stat().st_size
    reduction = (1 - new_size / original_size) * 100 if original_size > 0 else 0
    orig_kb = original_size / 1024
    new_kb = new_size / 1024
    console.print(f"[bold green]✓ Compressed! {orig_kb:.0f} KB → {new_kb:.0f} KB ({reduction:.0f}% smaller)[/bold green]")
    console.print(f"Saved to: [bold underline]{out_path.name}[/bold underline]")


def parse_size(text: str) -> int:
    """Parse a human file size like '9.77KB', '2 MB', '500k', '10000' → bytes."""
    s = str(text).strip().upper().replace(" ", "")
    mult = 1
    for suffix, m in (("KB", 1024), ("K", 1024), ("MB", 1024 ** 2),
                      ("M", 1024 ** 2), ("GB", 1024 ** 3), ("G", 1024 ** 3), ("B", 1)):
        if s.endswith(suffix):
            s = s[:-len(suffix)]
            mult = m
            break
    return int(round(float(s) * mult))


# ── Fitting an image to a file-size budget ──────────────────────────────────

# Encoders with a quality dial to search. Anything else (PNG, BMP, TIFF…) can
# only be made smaller by throwing pixels away.
LOSSY_FORMATS = {"jpg", "jpeg", "webp", "avif"}

_QUALITY_CEILING = 95
# Below this, JPEG/WebP artefacts are uglier than the same picture at fewer
# pixels, so this is where we stop turning the dial and start scaling.
_QUALITY_FLOOR = 55
# Above this there is room to spare — keep full 4:4:4 chroma.
_CHROMA_KEEP_ABOVE = 80


def _pil_format(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return {"jpg": "JPEG", "jpeg": "JPEG", "tif": "TIFF", "tiff": "TIFF",
            # pillow-heif registers the container as HEIF. ".heic" is one of
            # its extensions, not a name Pillow will answer to.
            "heic": "HEIF", "heif": "HEIF", "hif": "HEIF"}.get(ext, ext.upper())


def _writable(ext: str) -> str:
    """The nearest extension Pillow can actually write.

    Some formats only come in. SVG is vector: it is rasterised on the way past
    _open_image and there is no writing it back, so a resize or a size budget
    that kept the source extension would be asking for the impossible. PNG is
    the honest landing place — every pixel survives — and if a budget then
    rules PNG out, _choose_format carries on from there.
    """
    Image = _pil()
    ext = ext.lower().lstrip(".")
    Image.registered_extensions()  # loads the plugins that populate SAVE
    return ext if _pil_format(ext) in Image.SAVE else "png"


def _encode(img, ext: str, quality: int | None = None,
            subsampling: int | None = None, icc: bytes | None = None) -> bytes:
    """Encode to memory and hand back the bytes.

    Searching for a size means encoding the same picture a dozen times. Writing
    each attempt to disk is by far the slowest part of that and leaves nothing
    behind worth keeping, so every trial happens in RAM and only the winner is
    ever saved.
    """
    import io

    fmt = _pil_format(ext)
    kw: dict = {}
    if icc:
        kw["icc_profile"] = icc
    if fmt == "JPEG":
        if img.mode != "RGB":
            img = img.convert("RGB")
        kw.update(quality=quality or 90, optimize=True, progressive=True,
                  subsampling=0 if subsampling is None else subsampling)
    elif fmt == "WEBP":
        kw.update(quality=quality or 90, method=6)
    elif fmt == "AVIF":
        kw.update(quality=quality or 90)
    elif fmt == "PNG":
        kw.update(optimize=True, compress_level=9)
    elif fmt == "TIFF":
        kw.update(compression="tiff_lzw")
    elif fmt == "GIF" and img.mode not in ("P", "L"):
        img = img.convert("P", palette=_pil().ADAPTIVE)
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


def _best_under(img, ext: str, limit: int, subsampling: int | None,
                icc: bytes | None) -> tuple[bytes, int] | None:
    """Highest quality whose encode still fits in `limit`, or None.

    Binary search rather than a walk down from 95: seven encodes cover the
    whole range, and the answer lands just under the budget instead of far
    below it — the difference between spending your 500 KB and using 370.
    """
    lo, hi = 20, _QUALITY_CEILING
    best: tuple[bytes, int] | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        data = _encode(img, ext, mid, subsampling, icc)
        if len(data) <= limit:
            best = (data, mid)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _fit_under(img, ext: str, limit: int, icc: bytes | None):
    """Squeeze `img` into `limit` bytes, spending the cheapest thing first.

    The order is what makes the result look good: chroma costs less than
    quality, and quality costs less than resolution. A photo at full size and
    q70 beats the same photo at q95 and half the pixels every time, so pixels
    are the last thing to go — not the first.

    Returns (bytes, image_actually_encoded, quality_or_None).
    """
    import math

    Image = _pil()
    is_jpeg = _pil_format(ext) == "JPEG"
    lossy = ext.lower().lstrip(".") in LOSSY_FORMATS

    if lossy:
        full = _best_under(img, ext, limit, 0 if is_jpeg else None, icc)
        if full and full[1] >= _CHROMA_KEEP_ABOVE:
            return full[0], img, full[1]
        if is_jpeg:
            # 4:2:0 halves the colour resolution. Photographs don't show it;
            # text and line art do — so it is worth spending only once the
            # quality dial is already tight.
            reduced = _best_under(img, ext, limit, 2, icc)
            if reduced and reduced[1] >= _QUALITY_FLOOR:
                return reduced[0], img, reduced[1]
        elif full and full[1] >= _QUALITY_FLOOR:
            return full[0], img, full[1]

    # Out of quality: start removing pixels. File size tracks pixel count
    # closely, so solve for the scale instead of stepping 15% at a time
    # toward it — that is the difference between two encodes and nine.
    sub = 2 if is_jpeg else None
    probe = _encode(img, ext, _QUALITY_CEILING if lossy else None, sub, icc)
    scale = min(1.0, math.sqrt(limit / len(probe)) * 0.95) if probe else 1.0

    def attempt(factor: float):
        """Best encode at this scale, or None if even it overshoots."""
        width = max(1, round(img.width * factor))
        height = max(1, round(img.height * factor))
        shrunk = img if factor >= 1.0 else img.resize((width, height), Image.LANCZOS)
        if lossy:
            got = _best_under(shrunk, ext, limit, sub, icc)
            return (got[0], shrunk, got[1]) if got else None
        data = _encode(shrunk, ext, None, None, icc)
        return (data, shrunk, None) if len(data) <= limit else None

    for _ in range(8):
        found = attempt(scale)
        if found:
            # The estimate is deliberately conservative. One corrective step
            # spends the leftover budget on pixels instead of handing back a
            # needlessly small picture.
            if scale < 1.0 and len(found[0]) < limit * 0.9:
                wider = min(1.0, scale * math.sqrt(limit / len(found[0])) * 0.98)
                if wider > scale * 1.02:
                    grown = attempt(wider)
                    if grown:
                        return grown
            return found
        if min(round(img.width * scale), round(img.height * scale)) <= 16:
            break
        scale *= 0.85

    raise RuntimeError(
        f"Could not reach {limit / 1024:.2f} KB even at 16 px — "
        "the budget is smaller than any usable image.")


def _has_alpha(img) -> bool:
    return img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info)


def _choose_format(img, source_ext: str, limit: int | None,
                   icc: bytes | None) -> str:
    """Decide what to encode as when the caller asked for 'auto'.

    Keeping the user's own format is the default and the polite answer. The
    exception is a photograph living in a lossless one — a scan saved as PNG,
    a BMP export. Held to a small budget those can only shed pixels, while the
    same picture as JPEG or WebP meets the budget at full resolution. So the
    format changes only when keeping it would cost real detail.
    """
    ext = _writable(source_ext)
    if limit is None or ext in LOSSY_FORMATS:
        return ext
    if len(_encode(img, ext, None, None, icc)) <= limit:
        return ext  # fits as it is — no reason to touch the format
    # WebP is the one that keeps transparency; JPEG is the one everything opens.
    return "webp" if _has_alpha(img) else "jpg"


def planned_extension(input_path: Path, max_bytes: int | None,
                      target_format: str | None) -> str:
    """The extension fit_size is going to write, decided in advance.

    The wizard shows you where a file will land and refuses to clobber
    something already sitting there. Both of those promises need the real
    name, and with "auto" the format is a decision, not the input's suffix.
    """
    source_ext = input_path.suffix.lower().lstrip(".")
    if target_format and target_format.lower() != "auto":
        return target_format.lower().lstrip(".")
    if not target_format:
        return _writable(source_ext)
    img = _open_image(input_path)
    return _choose_format(img, source_ext, max_bytes, img.info.get("icc_profile"))


def fit_size(input_path: Path, console: Console, output_path: Path | None = None,
             min_bytes: int | None = None, max_bytes: int | None = None,
             target_format: str | None = None):
    """Re-encode an image so its file size lands within [min_bytes, max_bytes].

    Solves platform upload rules like "min 9.77 KB" (Google) or "max 2 MB".
    - Too small → upscale (and, for PNG, add a tiny metadata pad) until ≥ min.
    - Too large → spend chroma, then quality, then resolution until ≤ max.
    Both bounds may be given at once.

    target_format: an extension to encode as, "auto" to let the tool pick one
    that keeps the picture intact, or None to keep the source format.
    """
    Image = _pil()
    img = _open_image(input_path)
    orig = input_path.stat().st_size

    if min_bytes is None and max_bytes is None:
        raise ValueError("Give --min and/or --max a target size.")
    if min_bytes and max_bytes and min_bytes > max_bytes:
        raise ValueError("min size is larger than max size")

    # A colour profile is part of the picture; carry it through the re-encode.
    # EXIF is not — _open_image has already baked the orientation into the
    # pixels, and its thumbnail can be tens of kilobytes of the budget.
    icc = img.info.get("icc_profile")

    source_ext = input_path.suffix.lower().lstrip(".")
    if target_format and target_format.lower() != "auto":
        ext = target_format.lower().lstrip(".")
        if _writable(ext) != ext:
            raise ValueError(
                f"Nothing can write .{ext} — it is a read-only format here. "
                "Pick png, jpg, webp or avif.")
    elif target_format:
        ext = _choose_format(img, source_ext, max_bytes, icc)
    else:
        ext = _writable(source_ext)
    switched = ext != source_ext

    out_path = output_path or (input_path.parent / f"{input_path.stem}_fitted.{ext}")
    if out_path.suffix.lower().lstrip(".") != ext:
        out_path = out_path.with_suffix(f".{ext}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Already inside the budget and no format change asked for? Re-encoding
    # would only throw away detail to solve a problem that doesn't exist.
    if (not switched and not min_bytes and max_bytes and orig <= max_bytes
            and input_path.resolve() != out_path.resolve()):
        import shutil
        shutil.copyfile(input_path, out_path)
        console.print(f"[bold green]✓ Already under {max_bytes / 1024:.2f} KB[/bold green] "
                      f"[dim]({orig / 1024:.1f} KB, untouched)[/dim]")
        console.print(f"Saved to: [bold underline]{out_path.name}[/bold underline]")
        return out_path

    quality = None
    with console.status(f"[bold cyan]Fitting {input_path.name} to size…[/bold cyan]"):
        if max_bytes:
            data, img, quality = _fit_under(img, ext, max_bytes, icc)
        else:
            data = _encode(img, ext, None, None, icc)

        # ── Too small → upscale until we clear the floor. ──
        if min_bytes and len(data) < min_bytes:
            for _ in range(12):
                if len(data) >= min_bytes:
                    break
                img = img.resize((max(1, int(img.width * 1.4)),
                                  max(1, int(img.height * 1.4))), Image.LANCZOS)
                data = _encode(img, ext, quality, None, icc)
            # Last resort for a lossless format still under the floor: pad
            # trailing bytes after IEND so the file meets the minimum without
            # altering a single pixel.
            if len(data) < min_bytes and ext == "png":
                data = data + b"\x00" * (min_bytes - len(data))

        out_path.write_bytes(data)

    size = len(data)
    within = (not min_bytes or size >= min_bytes) and (not max_bytes or size <= max_bytes)
    tag = "[bold green]✓" if within else "[bold yellow]⚠ (best effort)"
    bounds = []
    if min_bytes:
        bounds.append(f"min {min_bytes / 1024:.2f} KB")
    if max_bytes:
        bounds.append(f"max {max_bytes / 1024:.2f} KB")
    detail = f"{img.width}x{img.height}"
    if quality is not None:
        detail += f", quality {quality}"
    console.print(f"{tag} {orig / 1024:.1f} KB → {size / 1024:.1f} KB "
                  f"({detail}, target {' & '.join(bounds)})[/]")
    if switched:
        console.print(f"[dim]Saved as .{ext} — .{source_ext} is lossless, so meeting "
                      f"that budget would have meant shrinking the picture.[/dim]")
    console.print(f"Saved to: [bold underline]{out_path.name}[/bold underline]")
    if not within:
        raise RuntimeError(
            f"Could not fully reach the target ({size / 1024:.2f} KB).")
    return out_path


def image_to_pdf(input_path: Path, console: Console, output_path: Path | None = None):
    """Convert a single image to a PDF document."""
    img = _open_image(input_path).convert("RGB")
    out_path = output_path or input_path.with_suffix(".pdf")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with console.status(f"[bold cyan]Converting {input_path.name} to PDF…[/bold cyan]"):
        img.save(out_path)

    console.print(f"[bold green]✓ Created {out_path.name}[/bold green]")
