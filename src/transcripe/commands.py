"""Non-interactive subcommands — full scripting/automation coverage.

    transcripe convert FILE... --to FMT   universal converter (all categories)
    transcripe ui                         full-screen TUI
    transcripe pdf     edit|render|replace|searchable|ocr|split|merge|pages|
                       extract-images
    transcripe media   transcribe|burn|gif|compress|trim|frames|concat
    transcripe image   resize|compress|fit-size
    transcripe data    pretty|minify
    transcripe archive list|extract|create
    transcripe model   convert
    transcripe fix-encoding FILE

Every command is prompt-free: sane defaults, -o/--output to override, exit
code 1 on failure. The interactive wizard (bare `transcripe`) is unchanged.
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()

pdf_app = typer.Typer(help="📕 PDF tools: edit, replace, searchable, ocr, split, merge…")
media_app = typer.Typer(help="🎬 Media tools: gif, compress, trim, frames, concat")
image_app = typer.Typer(help="🖼️  Image tools: resize, compress")
data_app = typer.Typer(help="📊 Data tools: pretty, minify")
archive_app = typer.Typer(help="🗜️  Archive tools: list, extract, create")
model_app = typer.Typer(help="🧊 3D model tools: convert")


def _fail(e: Exception):
    console.print(f"[bold red]Error:[/bold red] {e}")
    raise typer.Exit(code=1)


def _existing(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        _fail(FileNotFoundError(f"Cannot find '{p}'"))
    return p


def _langs(lang: str | None) -> list[str] | None:
    return [c.strip() for c in lang.split(",") if c.strip()] if lang else None


def _out(output: str | None) -> Path | None:
    return Path(output).expanduser() if output else None


# ── universal convert ───────────────────────────────────────────────────────

def convert_cmd(
    files: list[str] = typer.Argument(..., help="Input file(s)"),
    to: str = typer.Option(None, "--to", "-t", help="Target format (pdf, md, mp3, srt, webp, json…). "
                                                    "Omit for an interactive menu."),
    output: str = typer.Option(None, "--output", "-o", help="Output file (single input only)"),
    out_dir: str = typer.Option(None, "--out-dir", "-d", help="Put all outputs in this folder"),
):
    """Convert one or many files to a target format (all categories)."""
    from transcripe.core.dispatcher import _process_single_file, UserCancelled, dispatch_conversion

    paths = [_existing(f) for f in files]
    if output and len(paths) > 1:
        _fail(ValueError("-o works with a single input; use --out-dir for batches"))
    odir = Path(out_dir).expanduser().resolve() if out_dir else None
    if odir:
        odir.mkdir(parents=True, exist_ok=True)

    # No --to → interactive per-file menu (legacy `transcripe file.pdf` behavior).
    if to is None:
        try:
            dispatch_conversion(paths, None, console)
        except UserCancelled:
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit()
        except Exception as e:
            _fail(e)
        return

    failed = 0
    for p in paths:
        try:
            if output:
                out = Path(output).expanduser().resolve()
                out.parent.mkdir(parents=True, exist_ok=True)
                _process_single_file(p, to, console, confirm_output=False, explicit_out=out)
            else:
                _process_single_file(p, to, console, confirm_output=False, output_dir=odir)
        except Exception as e:
            failed += 1
            console.print(f"[red]✗ {p.name}: {e}[/red]")
    if failed:
        raise typer.Exit(code=1)


# ── pdf ─────────────────────────────────────────────────────────────────────

@pdf_app.command("edit")
def pdf_edit_cmd(
    file: str = typer.Argument(..., help="PDF to edit"),
    output: str = typer.Option(None, "--output", "-o"),
    lang: str = typer.Option(None, "--lang", help="OCR languages for scanned pages, e.g. ar,en"),
):
    """PDF → design-preserving editable HTML (open in a browser, click to edit)."""
    from transcripe.engines import pdf_edit
    try:
        pdf_edit.editable_html(_existing(file), console, output_path=_out(output), langs=_langs(lang))
    except Exception as e:
        _fail(e)


@pdf_app.command("replace")
def pdf_replace_cmd(
    file: str = typer.Argument(..., help="Text-layer PDF"),
    find: list[str] = typer.Option(..., "--find", "-f", help="Text to find (repeatable)"),
    to: list[str] = typer.Option(..., "--to", "-t", help="Replacement (repeatable, pairs with --find)"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Find & replace text directly in a PDF (RTL-aware)."""
    if len(find) != len(to):
        _fail(ValueError(f"{len(find)} --find but {len(to)} --to; they must pair up"))
    from transcripe.engines import pdf_edit
    reps = [{"find": f, "to": t} for f, t in zip(find, to)]
    try:
        pdf_edit.find_replace(_existing(file), reps, console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@pdf_app.command("render")
def pdf_render_cmd(
    file: str = typer.Argument(..., help="(Edited) HTML file to print back to PDF"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Render an edited HTML file back to PDF (Chromium print, WeasyPrint fallback)."""
    from transcripe.engines import pdf_edit
    try:
        pdf_edit.html_to_pdf(_existing(file), console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@pdf_app.command("searchable")
def pdf_searchable_cmd(
    file: str = typer.Argument(..., help="Scanned PDF"),
    output: str = typer.Option(None, "--output", "-o"),
    lang: str = typer.Option(None, "--lang", help="OCR languages, e.g. en,tr"),
):
    """Add an invisible OCR text layer (output looks identical, becomes searchable)."""
    from transcripe.core import capabilities
    from transcripe.engines import pdf_edit
    try:
        capabilities.require("pdf_searchable")
        pdf_edit.make_searchable(_existing(file), console, output_path=_out(output), langs=_langs(lang))
    except Exception as e:
        _fail(e)


@pdf_app.command("ocr")
def pdf_ocr_cmd(
    file: str = typer.Argument(..., help="Scanned PDF"),
    output: str = typer.Option(None, "--output", "-o"),
    lang: str = typer.Option(None, "--lang", help="OCR languages, e.g. ar,en"),
):
    """OCR a scanned PDF to plain text."""
    from transcripe.core import capabilities
    from transcripe.engines import documents
    try:
        capabilities.require("pdf_ocr")
        documents.pdf_ocr(_existing(file), console, output_path=_out(output), langs=_langs(lang))
    except Exception as e:
        _fail(e)


@pdf_app.command("split")
def pdf_split_cmd(
    file: str = typer.Argument(..., help="PDF to split"),
    pages: str = typer.Option(..., "--pages", "-p", help="Page range, e.g. 1-5 or 3,7,10-12"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Extract specific pages into a new PDF."""
    from transcripe.engines import documents
    try:
        documents.split_pdf(_existing(file), pages, console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@pdf_app.command("merge")
def pdf_merge_cmd(
    files: list[str] = typer.Argument(..., help="PDFs to merge, in order"),
    output: str = typer.Option(..., "--output", "-o", help="Merged output PDF"),
):
    """Merge multiple PDFs into one."""
    from transcripe.core.dispatcher import _merge_pdfs
    paths = [_existing(f) for f in files]
    if len(paths) < 2:
        _fail(ValueError("Need at least 2 PDFs to merge"))
    out = Path(output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        _merge_pdfs(paths, out, console)
        console.print(f"[bold green]✓ Merged {len(paths)} PDFs → {out}[/bold green]")
    except Exception as e:
        _fail(e)


@pdf_app.command("pages")
def pdf_pages_cmd(
    file: str = typer.Argument(..., help="PDF"),
    output: str = typer.Option(None, "--output", "-o", help="Output folder"),
):
    """Render each PDF page as a PNG image."""
    from transcripe.core import capabilities
    from transcripe.engines import documents
    try:
        capabilities.require("pdf_images")
        documents.pdf_to_images(_existing(file), console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@pdf_app.command("extract-images")
def pdf_extract_images_cmd(
    file: str = typer.Argument(..., help="PDF"),
    output: str = typer.Option(None, "--output", "-o", help="Output folder"),
):
    """Extract the raster images embedded in a PDF."""
    from transcripe.core import capabilities
    from transcripe.engines import pdf_edit
    try:
        capabilities.require("pdf_edit")
        pdf_edit.extract_images(_existing(file), _out(output), console)
    except Exception as e:
        _fail(e)


# ── media ───────────────────────────────────────────────────────────────────

@media_app.command("transcribe")
def media_transcribe_cmd(
    file: str = typer.Argument(..., help="Audio or video file"),
    srt: bool = typer.Option(False, "--srt", help="Output subtitles instead of plain text"),
    translate: bool = typer.Option(False, "--translate", help="Translate speech to English"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Transcribe (or translate to English) audio/video with Whisper."""
    from transcripe.core import capabilities
    from transcripe.engines import audio_video
    try:
        capabilities.require("transcribe")
        audio_video.transcribe(_existing(file), "srt" if srt else "txt", console,
                               output_path=_out(output), translate=translate)
    except Exception as e:
        _fail(e)


@media_app.command("burn")
def media_burn_cmd(
    file: str = typer.Argument(..., help="Video file"),
    subs: str = typer.Option(..., "--subs", "-s", help="Subtitle file (.srt/.vtt/.ass)"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Hard-burn subtitles into a video."""
    from transcripe.engines import subtitles
    try:
        subtitles.burn_subtitles(_existing(file), _existing(subs), console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@media_app.command("gif")
def media_gif_cmd(
    file: str = typer.Argument(...),
    fps: int = typer.Option(10, "--fps"),
    width: int = typer.Option(480, "--width"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Video → optimized GIF (two-pass palette)."""
    from transcripe.engines import audio_video
    try:
        audio_video.video_to_gif(_existing(file), fps, width, console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@media_app.command("compress")
def media_compress_cmd(
    file: str = typer.Argument(...),
    quality: str = typer.Option("medium", "--quality", "-q", help="high | medium | low"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Compress a video (CRF presets)."""
    from transcripe.engines import audio_video
    try:
        audio_video.compress_video(_existing(file), quality, console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@media_app.command("trim")
def media_trim_cmd(
    file: str = typer.Argument(...),
    start: str = typer.Option("00:00:00", "--start", "-s"),
    end: str = typer.Option("", "--end", "-e", help="Empty = until the end"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Trim/clip a video by start–end time."""
    from transcripe.engines import audio_video
    try:
        audio_video.trim_video(_existing(file), start, end, console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@media_app.command("frames")
def media_frames_cmd(
    file: str = typer.Argument(...),
    fps: int = typer.Option(1, "--fps"),
    output: str = typer.Option(None, "--output", "-o", help="Output folder"),
):
    """Extract video frames as PNG images."""
    from transcripe.engines import audio_video
    try:
        audio_video.extract_frames(_existing(file), fps, console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@media_app.command("concat")
def media_concat_cmd(
    files: list[str] = typer.Argument(..., help="Audio/video files, in order (same codec)"),
    output: str = typer.Option(..., "--output", "-o"),
):
    """Concatenate audio/video files (stream copy)."""
    from transcripe.core.dispatcher import _merge_audio
    paths = [_existing(f) for f in files]
    if len(paths) < 2:
        _fail(ValueError("Need at least 2 files to concatenate"))
    out = Path(output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        _merge_audio(paths, out, console)
        console.print(f"[bold green]✓ Concatenated {len(paths)} files → {out}[/bold green]")
    except Exception as e:
        _fail(e)


# ── image ───────────────────────────────────────────────────────────────────

@image_app.command("resize")
def image_resize_cmd(
    file: str = typer.Argument(...),
    width: int = typer.Option(None, "--width", "-w"),
    height: int = typer.Option(None, "--height", "-h"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Resize an image (one dimension scales proportionally)."""
    if not width and not height:
        _fail(ValueError("Give --width and/or --height"))
    from transcripe.engines import images
    try:
        images.resize_image(_existing(file), width, height, console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@image_app.command("compress")
def image_compress_cmd(
    file: str = typer.Argument(...),
    quality: int = typer.Option(60, "--quality", "-q", help="1-100, lower = smaller"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Compress an image by lowering quality."""
    from transcripe.engines import images
    try:
        images.compress_image(_existing(file), quality, console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@image_app.command("fit-size")
def image_fit_size_cmd(
    file: str = typer.Argument(...),
    min: str = typer.Option(None, "--min", help="Minimum file size, e.g. 9.77KB, 500k (upscales)"),
    max: str = typer.Option(None, "--max", help="Maximum file size, e.g. 500KB, 2MB (shrinks)"),
    format: str = typer.Option("auto", "--format", "-f",
                               help="Output format: auto (keeps the picture intact), "
                                    "same (keep the source format), or jpg/webp/png/avif"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Re-encode an image so its file size meets a platform rule (min and/or max).

    Example — fit an upload limit:      transcripe image fit-size photo.png --max 500KB
    Example — Google's "min 9.77 KB":   transcripe image fit-size logo.png --min 9.77KB

    Quality goes in the order that costs least: colour detail first, then
    compression, and only then the resolution. With --format auto a photo in a
    lossless format is re-encoded rather than shrunk.
    """
    from transcripe.engines import images
    try:
        mn = images.parse_size(min) if min else None
        mx = images.parse_size(max) if max else None
        images.fit_size(_existing(file), console, output_path=_out(output),
                        min_bytes=mn, max_bytes=mx,
                        target_format=None if format == "same" else format)
    except Exception as e:
        _fail(e)


# ── data ────────────────────────────────────────────────────────────────────

@data_app.command("pretty")
def data_pretty_cmd(
    file: str = typer.Argument(..., help="JSON file"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Pretty-print JSON."""
    from transcripe.engines import data
    try:
        data.json_prettify(_existing(file), console, output_path=_out(output))
    except Exception as e:
        _fail(e)


@data_app.command("minify")
def data_minify_cmd(
    file: str = typer.Argument(..., help="JSON file"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Minify JSON."""
    from transcripe.engines import data
    try:
        data.json_minify(_existing(file), console, output_path=_out(output))
    except Exception as e:
        _fail(e)


# ── archive ─────────────────────────────────────────────────────────────────

@archive_app.command("list")
def archive_list_cmd(file: str = typer.Argument(..., help="Archive file")):
    """List an archive's contents."""
    from transcripe.core.dispatcher import _show_archive_contents
    try:
        _show_archive_contents(_existing(file), console)
    except Exception as e:
        _fail(e)


@archive_app.command("extract")
def archive_extract_cmd(
    file: str = typer.Argument(...),
    output: str = typer.Option(None, "--output", "-o", help="Output folder"),
):
    """Extract an archive (zip/tar/gz/7z/rar) with path-traversal protection."""
    from transcripe.engines import archive
    try:
        archive.extract(_existing(file), _out(output), console)
    except Exception as e:
        _fail(e)


@archive_app.command("create")
def archive_create_cmd(
    files: list[str] = typer.Argument(..., help="Files to pack"),
    output: str = typer.Option(..., "--output", "-o", help="Archive to create (.zip/.tar.gz/.7z)"),
):
    """Create an archive from files."""
    from transcripe.engines import archive
    paths = [_existing(f) for f in files]
    try:
        archive.create(paths, Path(output).expanduser(), console)
    except Exception as e:
        _fail(e)


# ── 3D models ───────────────────────────────────────────────────────────────

@model_app.command("convert")
def model_convert_cmd(
    file: str = typer.Argument(..., help="3D model (.fbx/.obj/.3ds/.glb/…)"),
    to: str = typer.Option("glb", "--to", "-t", help="glb | gltf | obj | stl | ply"),
    web: bool = typer.Option(True, "--web/--plain",
                             help="--web: Draco + WebP textures (default); --plain: raw convert"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Convert a 3D model (web-optimized GLB by default)."""
    from transcripe.core import capabilities
    from transcripe.engines import models3d
    try:
        capabilities.require("model3d")
        models3d.convert_model(_existing(file), to, console, output_path=_out(output),
                               optimize=web and to in ("glb", "gltf"), compress="draco")
    except Exception as e:
        _fail(e)


# ── text encoding ───────────────────────────────────────────────────────────

def ui_cmd():
    """Launch the full-screen TUI (file browser + live conversion dashboard)."""
    try:
        from transcripe.tui import run_tui
    except ImportError as e:
        _fail(RuntimeError(f"TUI needs 'textual' — pip install textual ({e})"))
    run_tui()


def fix_encoding_cmd(
    file: str = typer.Argument(..., help="Garbled text file"),
    output: str = typer.Option(None, "--output", "-o"),
):
    """Detect a text file's encoding and re-save it as clean UTF-8."""
    from transcripe.core import text_utils
    try:
        text_utils.reencode_to_utf8(_existing(file), console, output_path=_out(output))
    except Exception as e:
        _fail(e)


def studio_cmd(
    host: str = typer.Option(None, "--host", help="Bind address; 0.0.0.0 opens it to your LAN"),
    port: int = typer.Option(None, "--port", help="Port (default 8000)"),
    no_open: bool = typer.Option(False, "--no-open", help="Don't open a browser"),
    lan: bool = typer.Option(False, "--lan", help="Shorthand for --host 0.0.0.0 (for the phone app)"),
):
    """Serve the browser studio (and the API the phone app talks to)."""
    try:
        from transcripe.studio import serve
    except ImportError as e:
        _fail(RuntimeError(
            f"Studio needs its extras — pip install 'transcripe[studio]' ({e})"))
    serve(host="0.0.0.0" if lan else host, port=port, open_browser=not no_open)


# ── registration ────────────────────────────────────────────────────────────

SUBCOMMANDS = {"convert", "pdf", "media", "image", "data", "archive", "model",
               "ui", "studio", "fix-encoding", "--help", "--doctor", "--self-test", "--slow"}


def register(app: typer.Typer) -> None:
    app.command("convert")(convert_cmd)
    app.command("ui")(ui_cmd)
    app.command("studio")(studio_cmd)
    app.command("fix-encoding")(fix_encoding_cmd)
    app.add_typer(pdf_app, name="pdf")
    app.add_typer(media_app, name="media")
    app.add_typer(image_app, name="image")
    app.add_typer(data_app, name="data")
    app.add_typer(archive_app, name="archive")
    app.add_typer(model_app, name="model")
