from pathlib import Path
import os
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TaskProgressColumn, MofNCompleteColumn, TimeElapsedColumn,
)
from rich import box
import questionary
from questionary import Style
from transcripe.engines import audio_video, documents, images, data
from transcripe.core import capabilities

# ── Theme ──────────────────────────────────────────────────────────────────
THEME = Style([
    ("qmark",       "fg:#673ab7 bold"),
    ("question",    "fg:#ffffff bold"),
    ("answer",      "fg:#00e676 bold"),
    ("pointer",     "fg:#673ab7 bold"),
    ("highlighted", "fg:#673ab7 bold"),
    ("selected",    "fg:#00e676"),
])


class UserCancelled(Exception):
    """Raised when the user cancels an interactive prompt (Esc / Ctrl-C)."""


def _ask(question):
    """Run a questionary prompt; raise UserCancelled instead of returning None."""
    ans = question.ask()
    if ans is None:
        raise UserCancelled()
    return ans

# ── Supported Extensions ──────────────────────────────────────────────────
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".mpeg", ".mpg", ".m4v", ".ts", ".3gp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".opus", ".amr"}
MEDIA_AUDIO_TARGETS = {"mp3", "wav", "flac", "aac", "ogg", "m4a", "opus", "wma"}
MEDIA_VIDEO_TARGETS = {"mp4", "mkv", "avi", "mov", "webm", "flv", "wmv"}
DOC_EXTS   = {".pptx", ".ppt", ".docx", ".doc", ".epub", ".odt", ".rtf", ".txt", ".md",
              ".html", ".htm", ".tex", ".rst"}
DATA_EXTS  = {".csv", ".tsv", ".json", ".ndjson", ".jsonl", ".parquet",
              ".yaml", ".yml", ".xml", ".xls", ".xlsx", ".ods"}
SUBTITLE_EXTS = {".srt", ".vtt", ".ass", ".ssa"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tiff", ".tif", ".gif", ".ico", ".svg", ".avif"}
PDF_EXTS   = {".pdf"}
ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".7z", ".rar"}
MODEL_EXTS = {".glb", ".gltf", ".obj", ".fbx", ".3ds", ".dae", ".stl", ".ply",
              ".x", ".off", ".3mf", ".lwo", ".ac", ".ms3d", ".blend"}

ALL_SUPPORTED_EXTS = (VIDEO_EXTS | AUDIO_EXTS | DOC_EXTS | DATA_EXTS | IMAGE_EXTS
                      | PDF_EXTS | ARCHIVE_EXTS | MODEL_EXTS | SUBTITLE_EXTS)

# ── Category helpers ──────────────────────────────────────────────────────

def get_file_category(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext in VIDEO_EXTS:    return "🎬 Video"
    if ext in AUDIO_EXTS:    return "🎵 Audio"
    if ext in DOC_EXTS:      return "📄 Document"
    if ext in IMAGE_EXTS:    return "🖼️  Image"
    if ext in PDF_EXTS:      return "📕 PDF"
    if ext in ARCHIVE_EXTS:  return "🗜️  Archive"
    if ext in MODEL_EXTS:    return "🧊 3D Model"
    if ext in SUBTITLE_EXTS: return "💬 Subtitles"
    return "❓ Unknown"

def _get_ext_category(ext: str) -> str:
    ext = ext.lower()
    if ext in VIDEO_EXTS:    return "video"
    if ext in AUDIO_EXTS:    return "audio"
    if ext in DOC_EXTS:      return "document"
    if ext in DATA_EXTS:     return "data"
    if ext in IMAGE_EXTS:    return "image"
    if ext in PDF_EXTS:      return "pdf"
    if ext in ARCHIVE_EXTS:  return "archive"
    if ext in MODEL_EXTS:    return "model3d"
    if ext in SUBTITLE_EXTS: return "subtitle"
    return "unknown"

# ── Smart detection & suggestions ─────────────────────────────────────────

# Human-readable descriptions and the recommended action per category.
_SUGGESTIONS = {
    "video":    "Transcribe to text, extract audio, convert, compress, trim, or make a GIF.",
    "audio":    "Transcribe to text/subtitles or convert between audio formats.",
    "document": "Convert to PDF, Markdown, HTML, Word, or plain text.",
    "pdf":      "Extract text, convert pages to images, split pages, or convert to Word/MD/HTML.",
    "image":    "OCR text extraction, convert format, resize, compress, or turn into a PDF.",
    "data":     "Convert between CSV, JSON, YAML, Excel — or prettify/minify JSON.",
    "archive":  "List contents, extract files, or convert the files inside.",
    "model3d":  "Convert to web‑ready GLB (Draco‑compressed) or OBJ/STL/PLY/glTF.",
    "subtitle": "Convert between SRT/VTT/ASS, or strip timing to plain text.",
}

_RECOMMENDED = {
    "video":    "Transcription (.txt)",
    "audio":    "Transcription (.txt)",
    "document": "PDF (.pdf)",
    "pdf":      "Extract Text (.txt)",
    "image":    "Convert format",
    "data":     "Convert format",
}


def _human_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1_048_576:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1_073_741_824:
        return f"{num_bytes / 1_048_576:.1f} MB"
    return f"{num_bytes / 1_073_741_824:.2f} GB"


def _show_archive_contents(input_path: Path, console: Console):
    """Print a table of the files inside an archive."""
    from transcripe.engines import archive
    entries = archive.list_contents(input_path)
    table = Table(title=f"📦 {input_path.name}", box=box.ROUNDED, border_style="cyan",
                  title_style="bold bright_cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("File", style="cyan")
    table.add_column("Size", style="green")
    total = 0
    for i, (name, size) in enumerate(entries, 1):
        total += size
        size_str = _human_size(size) if size else "—"
        table.add_row(str(i), name, size_str)
    console.print(table)
    console.print(f"[dim]{len(entries)} file(s), {_human_size(total)} uncompressed[/dim]")


def _describe_file(input_path: Path, console: Console):
    """Show an auto-detected summary panel for a file before asking what to do."""
    cat_label = get_file_category(input_path)
    cat_key = _get_ext_category(input_path.suffix.lower())
    try:
        size = _human_size(input_path.stat().st_size)
    except OSError:
        size = "?"
    suggestion = _SUGGESTIONS.get(cat_key, "No automatic suggestions for this type.")
    console.print(Panel(
        f"[bold white]{input_path.name}[/bold white]\n"
        f"[dim]Detected:[/dim] {cat_label}   [dim]Size:[/dim] {size}   "
        f"[dim]Type:[/dim] {input_path.suffix.lower() or 'n/a'}\n"
        f"[dim]💡 I can:[/dim] {suggestion}",
        title="[bold bright_cyan]🔎 Auto-detected[/bold bright_cyan]",
        border_style="bright_cyan",
        box=box.ROUNDED,
        expand=False,
        padding=(0, 2),
    ))


def _compute_default_output(input_path: Path, target_format: str, params: dict | None = None) -> tuple[Path, bool]:
    """Return (default_output_path, is_directory) for a resolved target/action."""
    params = params or {}
    parent = input_path.parent
    stem = input_path.stem

    directory_map = {
        "__frames": parent / f"{stem}_frames",
        "__pdf_images": parent / f"{stem}_pages",
        "__pdf_imgs_embedded": parent / f"{stem}_images",
    }
    if target_format in directory_map:
        return directory_map[target_format], True

    file_map = {
        "__gif": input_path.with_suffix(".gif"),
        "__compress": parent / f"{stem}_compressed{input_path.suffix}",
        "__trim": parent / f"{stem}_trimmed{input_path.suffix}",
        "__pdf_text": input_path.with_suffix(".txt"),
        "__pdf_ocr": input_path.with_suffix(".txt"),
        "__translate_txt": parent / f"{stem}_en.txt",
        "__translate_srt": parent / f"{stem}_en.srt",
        "__burn_subs": parent / f"{stem}_subtitled{input_path.suffix}",
        "__pdf_edit": parent / f"{stem}_editable.html",
        "__pdf_replace": parent / f"{stem}_edited.pdf",
        "__pdf_searchable": parent / f"{stem}_searchable.pdf",
        "__ocr": input_path.with_suffix(".txt"),
        "__fix_encoding": parent / f"{stem}_utf8{input_path.suffix}",
        "__resize": parent / f"{stem}_resized{input_path.suffix}",
        "__compress_img": parent / f"{stem}_compressed{input_path.suffix}",
        "__img_pdf": input_path.with_suffix(".pdf"),
        "__json_pretty": parent / f"{stem}_pretty.json",
        "__json_minify": parent / f"{stem}_min.json",
        "__m_glb_web": parent / f"{stem}_web.glb",
        "__m_glb": input_path.with_suffix(".glb"),
        "__m_gltf": input_path.with_suffix(".gltf"),
        "__m_obj": input_path.with_suffix(".obj"),
        "__m_stl": input_path.with_suffix(".stl"),
        "__m_ply": input_path.with_suffix(".ply"),
    }
    if target_format in file_map:
        return file_map[target_format], False

    if target_format == "__fit_size":
        # "auto" may settle on a different format than the input's, and the
        # name it lands on is the one to confirm and to guard against.
        ext = params.get("fit_ext") or input_path.suffix.lstrip(".")
        return parent / f"{stem}_fitted.{ext}", False

    if target_format == "__pdf_split":
        rng = params.get("page_range", "pages")
        safe = rng.replace(",", "_").replace("-", "to")
        return parent / f"{stem}_pages_{safe}.pdf", False

    fmt = target_format.lower().strip(".")
    return input_path.with_suffix(f".{fmt}"), False


def _ask_ocr_langs(console: Console) -> list[str] | None:
    """Ask which language(s) to OCR. Returns None for auto (RapidOCR multilingual)."""
    choice = questionary.select(
        "Which language(s) should I read?",
        choices=[
            "🌍  Auto — Latin scripts + Türkçe + numbers (Recommended)",
            "🇬🇧  English only",
            "🇹🇷  Türkçe (Turkish)",
            "🇸🇦  العربية (Arabic)",
            "🇨🇳  中文 (Chinese)",
            "🌐  Other — type language codes…",
        ],
        style=THEME,
    ).ask()
    if not choice or "Auto" in choice:
        return None
    if "English" in choice:
        return ["en"]
    if "Turkish" in choice:
        return ["tr"]
    if "Arabic" in choice:
        return ["ar", "en"]
    if "Chinese" in choice:
        return ["ch_sim", "en"]
    if "Other" in choice:
        raw = questionary.text(
            "Language codes, comma-separated (e.g. en,fr,de or ru,ja):",
            style=THEME,
        ).ask()
        codes = [c.strip() for c in (raw or "").split(",") if c.strip()]
        return codes or None
    return None


def _confirm_output(default_path: Path, is_dir: bool, console: Console) -> Path:
    """Show where output will be saved and let the user change it. Enter = accept."""
    label = "folder" if is_dir else "file"
    icon = "📁" if is_dir else "💾"
    while True:
        console.print(f"\n{icon}  [bold]Output {label} will be saved to:[/bold] [green]{default_path}[/green]")
        ans = questionary.path(
            f"Press Enter to accept, or type a new {label} path:",
            default=str(default_path),
            style=THEME,
        ).ask()

        if not ans or not str(ans).strip():
            chosen = default_path
        else:
            chosen = Path(str(ans).strip().strip("'\"")).expanduser()
            if is_dir:
                chosen = chosen.resolve()
            elif chosen.is_dir() or (not chosen.suffix and not str(ans).strip().endswith(default_path.suffix)):
                # User gave a directory (or extension-less path): keep the default filename.
                chosen = (chosen / default_path.name).resolve()
            else:
                chosen = chosen.resolve()

        # Overwrite protection (files only).
        if not is_dir and chosen.exists():
            overwrite = questionary.confirm(
                f"⚠  {chosen.name} already exists. Overwrite it?",
                default=False,
                style=THEME,
            ).ask()
            if not overwrite:
                default_path = chosen  # keep as the prompt default and ask again
                continue
        return chosen


def _resolve_out(input_path: Path, target_format: str, params: dict | None,
                 confirm_output: bool, output_dir: Path | None, console: Console) -> Path | None:
    """Decide the output path: interactive confirm, batch folder relocation, or engine default."""
    default_out, is_dir = _compute_default_output(input_path, target_format, params)
    if output_dir is not None:
        default_out = output_dir / default_out.name
    if confirm_output:
        return _confirm_output(default_out, is_dir, console)
    return default_out if output_dir is not None else None


def _result_dir(out: Path | None, output_dir: Path | None, input_path: Path) -> Path:
    """Best-effort folder where the output landed (for the 'open folder' prompt)."""
    if output_dir is not None:
        return output_dir
    if out is not None:
        return out if out.suffix == "" else out.parent
    return input_path.parent


# ── Single-file conversion ────────────────────────────────────────────────

def _process_single_file(input_path: Path, target_format: str | None, console: Console,
                         confirm_output: bool = True, output_dir: Path | None = None,
                         explicit_out: Path | None = None):
    """Route a single file to the appropriate engine.

    explicit_out: exact output path (from `convert -o …`) — overrides the
    computed default and skips the interactive confirm.
    """
    ext = input_path.suffix.lower()
    if explicit_out is not None:
        confirm_output = False

    # INTERACTIVE: ask user to pick output format
    if target_format is None:
        _describe_file(input_path, console)
        if ext in VIDEO_EXTS or ext in AUDIO_EXTS:
            is_video = ext in VIDEO_EXTS
            choices = [
                "📝  Transcription (.txt) (Recommended)",
                "🎬  Subtitles (.srt)",
                "🌐  Translate to English (.txt)",
                "🌐  Translate to English (.srt)",
            ]
            if is_video:
                choices += [
                    "💬  Burn subtitles into video",
                    "🎵  Extract Audio (.mp3)",
                    "🎵  Extract Audio (.wav)",
                    "🎵  Extract Audio (.flac)",
                    "🎞️   Convert to GIF",
                    "📦  Compress Video (reduce file size)",
                    "✂️   Trim / Clip Video",
                    "🖼️   Extract Frames as Images",
                    "🔄  Convert to another format",
                ]
            else:
                choices += [
                    "🔄  Convert to MP3",
                    "🔄  Convert to WAV",
                    "🔄  Convert to FLAC",
                    "🔄  Convert to OGG",
                    "🔄  Convert to another format",
                ]
            choice = _ask(questionary.select(
                f"  {input_path.name} → What would you like to do?",
                choices=choices,
                style=THEME,
            ))

            if "Transcription" in choice:       target_format = "txt"
            elif "Translate" in choice:
                target_format = "__translate_srt" if ".srt" in choice else "__translate_txt"
            elif "Burn subtitles" in choice:    target_format = "__burn_subs"
            elif "Subtitles" in choice:         target_format = "srt"
            elif ".mp3" in choice or "MP3" in choice: target_format = "mp3"
            elif ".wav" in choice or "WAV" in choice: target_format = "wav"
            elif ".flac" in choice or "FLAC" in choice: target_format = "flac"
            elif "OGG" in choice:               target_format = "ogg"
            elif "GIF" in choice:               target_format = "__gif"
            elif "Compress" in choice:          target_format = "__compress"
            elif "Trim" in choice:              target_format = "__trim"
            elif "Frames" in choice:            target_format = "__frames"
            elif "another" in choice.lower():
                target_format = _ask(questionary.text(
                    "Enter target format (mp3, wav, flac, ogg, mp4, mkv, webm…):",
                    style=THEME,
                ))

        elif ext in PDF_EXTS:
            pdf_choices = [
                "📝  Extract Text from PDF (Recommended)",
                "✏️   Edit PDF in browser (keeps the design)",
                "🔁  Find & Replace text in PDF",
                "🔎  OCR — read scanned/image PDF (AI)",
            ]
            if capabilities.can("pdf_searchable"):
                pdf_choices.append("🪄  Make searchable (add OCR text layer)")
            pdf_choices += [
                "🖼️   Convert Pages to Images (PNG)",
                "🖼️   Extract Embedded Images",
                "✂️   Split / Extract Pages",
                "📝  Markdown (.md)",
                "🌐  HTML Page (.html)",
                "📄  Word Document (.docx)",
            ]
            choice = _ask(questionary.select(
                f"  {input_path.name} → What would you like to do?",
                choices=pdf_choices,
                style=THEME,
            ))
            if "Edit PDF" in choice:            target_format = "__pdf_edit"
            elif "Find & Replace" in choice:    target_format = "__pdf_replace"
            elif "searchable" in choice:        target_format = "__pdf_searchable"
            elif "Embedded" in choice:          target_format = "__pdf_imgs_embedded"
            elif "OCR" in choice:               target_format = "__pdf_ocr"
            elif "Extract Text" in choice:      target_format = "__pdf_text"
            elif "Images" in choice:            target_format = "__pdf_images"
            elif "Split" in choice:             target_format = "__pdf_split"
            elif "Markdown" in choice:          target_format = "md"
            elif "HTML" in choice:              target_format = "html"
            elif "Word" in choice:              target_format = "docx"

        elif ext in DOC_EXTS:
            _PLAINTEXT = {".txt", ".md", ".rst", ".tex", ".html", ".htm", ".csv"}
            doc_choices = [
                "📕  PDF Document (.pdf) (Recommended)",
                "📝  Markdown (.md)",
                "🌐  HTML Page (.html)",
                "📄  Word Document (.docx)",
                "📃  Plain Text (.txt)",
            ]
            if ext in _PLAINTEXT:
                doc_choices.append("🔧  Fix encoding → clean UTF-8")
            choice = _ask(questionary.select(
                f"  {input_path.name} → What would you like to generate?",
                choices=doc_choices,
                style=THEME,
            ))
            if "Fix encoding" in choice:  target_format = "__fix_encoding"
            elif "PDF" in choice:        target_format = "pdf"
            elif "Markdown" in choice: target_format = "md"
            elif "HTML" in choice:     target_format = "html"
            elif "Word" in choice:     target_format = "docx"
            else:                      target_format = "txt"

        elif ext in DATA_EXTS:
            data_choices = []
            if ext in (".csv", ".tsv"):
                data_choices = ["📊  JSON (.json) (Recommended)", "📊  Excel (.xlsx)",
                                "📊  Parquet (.parquet)", "📊  NDJSON (.ndjson)"]
            elif ext == ".json":
                data_choices = ["📊  CSV (.csv) (Recommended)", "📊  YAML (.yaml)",
                                "📊  Parquet (.parquet)", "📊  NDJSON (.ndjson)",
                                "✨  Prettify JSON", "📦  Minify JSON"]
            elif ext in (".ndjson", ".jsonl"):
                data_choices = ["📊  JSON (.json) (Recommended)", "📊  CSV (.csv)", "📊  Parquet (.parquet)"]
            elif ext == ".parquet":
                data_choices = ["📊  CSV (.csv) (Recommended)", "📊  JSON (.json)", "📊  Excel (.xlsx)"]
            elif ext in (".yaml", ".yml"):
                data_choices = ["📊  JSON (.json) (Recommended)"]
            elif ext in (".xls", ".xlsx", ".ods"):
                data_choices = ["📊  CSV (.csv) (Recommended)", "📊  JSON (.json)", "📊  Parquet (.parquet)"]
            elif ext == ".xml":
                data_choices = ["📊  JSON (.json) (Recommended)"]

            choice = _ask(questionary.select(
                f"  {input_path.name} → What would you like to generate?",
                choices=data_choices,
                style=THEME,
            ))

            if "NDJSON" in choice:    target_format = "ndjson"
            elif "CSV" in choice:     target_format = "csv"
            elif "Parquet" in choice: target_format = "parquet"
            elif "JSON" in choice and "Prettify" not in choice and "Minify" not in choice:
                target_format = "json"
            elif "Excel" in choice:   target_format = "xlsx"
            elif "YAML" in choice:    target_format = "yaml"
            elif "Prettify" in choice: target_format = "__json_pretty"
            elif "Minify" in choice:  target_format = "__json_minify"

        elif ext in IMAGE_EXTS:
            choice = _ask(questionary.select(
                f"  {input_path.name} → What would you like to do?",
                choices=[
                    "📝  Extract Text (OCR → .txt) (Recommended)",
                    "🖼️   Convert to PNG",
                    "🖼️   Convert to WebP",
                    "🖼️   Convert to JPEG",
                    "📐  Resize Image",
                    "📦  Compress Image (reduce file size)",
                    "🎯  Fit to a file-size rule (min/max, e.g. Google ‘min 9.77 KB’)",
                    "📕  Convert to PDF",
                ],
                style=THEME,
            ))
            if "OCR" in choice:       target_format = "__ocr"
            elif "PNG" in choice:     target_format = "png"
            elif "WebP" in choice:    target_format = "webp"
            elif "JPEG" in choice:    target_format = "jpg"
            elif "Resize" in choice:  target_format = "__resize"
            elif "Fit to a file-size" in choice: target_format = "__fit_size"
            elif "Compress" in choice: target_format = "__compress_img"
            elif "PDF" in choice:     target_format = "__img_pdf"

        elif ext in SUBTITLE_EXTS:
            sub_targets = {"srt", "vtt", "ass"} - {ext.lstrip(".")}
            sub_choices = [f"💬  Convert to {t.upper()} (.{t})" for t in sorted(sub_targets)]
            sub_choices.append("📃  Plain text — strip timing (.txt)")
            choice = _ask(questionary.select(
                f"  {input_path.name} → What would you like to do?",
                choices=sub_choices,
                style=THEME,
            ))
            target_format = "txt" if "Plain text" in choice else choice.split("(.")[-1].rstrip(")")

        elif ext in ARCHIVE_EXTS:
            choice = _ask(questionary.select(
                f"  {input_path.name} → What would you like to do?",
                choices=[
                    "📂  Extract all files (Recommended)",
                    "📋  List contents",
                    "🔄  Extract, then convert the files inside",
                ],
                style=THEME,
            ))
            if "List" in choice:          target_format = "__archive_list"
            elif "then convert" in choice: target_format = "__archive_convert"
            else:                          target_format = "__archive_extract"

        elif ext in MODEL_EXTS:
            is_gltf = ext in (".glb", ".gltf")
            model_choices = ["🌐  Web‑optimized GLB — Draco compressed (Recommended)"]
            if is_gltf:
                model_choices.append("🗜️   Optimize this GLB/glTF for web (Draco)")
            model_choices += [
                "📦  GLB (plain, uncompressed)",
                "📄  glTF (.gltf + .bin)",
                "🧊  OBJ (.obj)",
                "🧊  STL (.stl)",
                "🧊  PLY (.ply)",
            ]
            choice = _ask(questionary.select(
                f"  {input_path.name} → What would you like to do?",
                choices=model_choices,
                style=THEME,
            ))
            if "Web‑optimized" in choice or "Optimize this" in choice:
                target_format = "__m_glb_web"
            elif "GLB (plain" in choice: target_format = "__m_glb"
            elif "glTF" in choice:       target_format = "__m_gltf"
            elif "OBJ" in choice:        target_format = "__m_obj"
            elif "STL" in choice:        target_format = "__m_stl"
            elif "PLY" in choice:        target_format = "__m_ply"

        else:
            raise ValueError(f"No interactive options for '{ext}'. Use --to flag.")

    if not target_format:
        raise ValueError("No action selected.")

    # ── Archives (list / extract / extract+convert) ──
    if target_format in ("__archive_list", "__archive_extract", "__archive_convert") or \
       (ext in ARCHIVE_EXTS and target_format in ("extract", "list")):
        from transcripe.engines import archive
        action = target_format.replace("__archive_", "") if target_format.startswith("__archive_") else target_format

        if action == "list":
            _show_archive_contents(input_path, console)
            return input_path.parent

        out_dir = None
        if confirm_output:
            default_dir = (output_dir or input_path.parent) / f"{input_path.stem}_extracted"
            out_dir = _confirm_output(default_dir, True, console)
        elif output_dir is not None:
            out_dir = output_dir / f"{input_path.stem}_extracted"
        extracted = archive.extract(input_path, out_dir, console)

        if action == "convert":
            inside = [p for p in sorted(extracted.rglob("*"))
                      if p.is_file() and p.suffix.lower() in ALL_SUPPORTED_EXTS
                      and p.suffix.lower() not in ARCHIVE_EXTS]
            if not inside:
                console.print("[yellow]No convertible files found inside the archive.[/yellow]")
            else:
                console.print(f"\n[cyan]Converting {len(inside)} file(s) from the archive…[/cyan]")
                dispatch_conversion(inside, None, console)
        return extracted

    # ── Special interactive actions (not a simple format string) ──
    if target_format.startswith("__"):
        params: dict = {}
        if target_format == "__gif":
            params["fps"] = int(_ask(questionary.text("GIF frames per second?", default="10", style=THEME)))
            params["width"] = int(_ask(questionary.text("GIF width in pixels?", default="480", style=THEME)))
        elif target_format == "__compress":
            q = _ask(questionary.select("Compression quality?", choices=["high (minimal loss)", "medium (balanced)", "low (smallest file)"], style=THEME))
            params["quality"] = q.split()[0]
        elif target_format == "__trim":
            params["start"] = _ask(questionary.text("Start time (e.g., 00:00:30 or 30):", default="00:00:00", style=THEME))
            params["end"] = _ask(questionary.text("End time (e.g., 00:01:45 or leave blank for end):", default="", style=THEME))
        elif target_format == "__frames":
            params["fps"] = int(_ask(questionary.text("Extract how many frames per second?", default="1", style=THEME)))
        elif target_format == "__pdf_split":
            params["page_range"] = _ask(questionary.text("Enter page range (e.g., 1-5 or 3,7,10-12):", style=THEME))
        elif target_format == "__resize":
            w = _ask(questionary.text("Target width in pixels (leave blank to auto):", default="", style=THEME))
            h = _ask(questionary.text("Target height in pixels (leave blank to auto):", default="", style=THEME))
            params["width"] = int(w) if w else None
            params["height"] = int(h) if h else None
        elif target_format == "__compress_img":
            params["quality"] = int(_ask(questionary.text("Quality (1-100, lower = smaller):", default="60", style=THEME)))
        elif target_format == "__fit_size":
            mn = _ask(questionary.text("Minimum file size (e.g. 9.77KB — blank for none):", default="", style=THEME))
            mx = _ask(questionary.text("Maximum file size (e.g. 500KB — blank for none):", default="", style=THEME))
            from transcripe.engines import images as _img
            params["min_bytes"] = _img.parse_size(mn) if mn.strip() else None
            params["max_bytes"] = _img.parse_size(mx) if mx.strip() else None
            # "auto" so a photo saved as PNG is re-encoded rather than shrunk;
            # the format changes only when keeping it would cost real detail.
            params["fit_ext"] = _img.planned_extension(
                input_path, params["max_bytes"], "auto")
        elif target_format == "__burn_subs":
            raw = _ask(questionary.path("Subtitle file (.srt/.vtt/.ass) to burn in:", style=THEME))
            subs = Path(str(raw).strip().strip("'\"")).expanduser().resolve()
            if not subs.exists():
                raise ValueError(f"Subtitle file not found: {subs}")
            params["subs"] = subs
        elif target_format in ("__ocr", "__pdf_ocr"):
            params["langs"] = _ask_ocr_langs(console)
        elif target_format == "__pdf_searchable":
            params["langs"] = _ask_ocr_langs(console)
        elif target_format == "__pdf_replace":
            # Collect find→replace pairs until the user leaves 'find' blank.
            reps = []
            console.print("[dim]Enter find → replace pairs. Leave 'Find' empty to finish.[/dim]")
            while True:
                find = _ask(questionary.text(f"Find ({len(reps)} so far):", default="", style=THEME))
                if not find.strip():
                    break
                to = _ask(questionary.text(f"Replace '{find}' with:", default="", style=THEME))
                reps.append({"find": find, "to": to})
            if not reps:
                raise ValueError("No replacements entered.")
            params["replacements"] = reps

        _SPECIAL_FEATURE = {
            "__gif": "media_convert", "__compress": "media_convert",
            "__trim": "media_convert", "__frames": "media_convert",
            "__burn_subs": "media_convert",
            "__translate_txt": "transcribe", "__translate_srt": "transcribe",
            "__pdf_text": "pdf_text", "__pdf_ocr": "pdf_ocr",
            "__pdf_images": "pdf_images", "__pdf_split": "pdf_text",
            "__pdf_edit": "pdf_edit", "__pdf_replace": "pdf_edit",
            "__pdf_imgs_embedded": "pdf_edit", "__pdf_searchable": "pdf_searchable",
            "__ocr": "ocr", "__resize": "image_ops",
            "__compress_img": "image_ops", "__img_pdf": "image_ops",
            "__fit_size": "image_ops",
            "__m_glb_web": "model3d", "__m_glb": "model3d", "__m_gltf": "model3d",
            "__m_obj": "model3d", "__m_stl": "model3d", "__m_ply": "model3d",
        }
        if target_format in _SPECIAL_FEATURE:
            capabilities.require(_SPECIAL_FEATURE[target_format])

        out = explicit_out or _resolve_out(input_path, target_format, params, confirm_output, output_dir, console)

        if target_format in ("__translate_txt", "__translate_srt"):
            fmt = "srt" if target_format.endswith("srt") else "txt"
            audio_video.transcribe(input_path, fmt, console, output_path=out, translate=True)
        elif target_format == "__burn_subs":
            from transcripe.engines import subtitles
            subtitles.burn_subtitles(input_path, params["subs"], console, output_path=out)
        elif target_format == "__gif":
            audio_video.video_to_gif(input_path, params["fps"], params["width"], console, output_path=out)
        elif target_format == "__compress":
            audio_video.compress_video(input_path, params["quality"], console, output_path=out)
        elif target_format == "__trim":
            audio_video.trim_video(input_path, params["start"], params["end"], console, output_path=out)
        elif target_format == "__frames":
            audio_video.extract_frames(input_path, params["fps"], console, output_path=out)
        elif target_format == "__pdf_text":
            documents.pdf_to_text(input_path, console, output_path=out)
        elif target_format == "__pdf_ocr":
            documents.pdf_ocr(input_path, console, output_path=out, langs=params.get("langs"))
        elif target_format == "__pdf_images":
            documents.pdf_to_images(input_path, console, output_path=out)
        elif target_format == "__pdf_split":
            documents.split_pdf(input_path, params["page_range"], console, output_path=out)
        elif target_format == "__pdf_edit":
            from transcripe.engines import pdf_edit
            pdf_edit.editable_html(input_path, console, output_path=out, langs=params.get("langs"))
        elif target_format == "__pdf_replace":
            from transcripe.engines import pdf_edit
            pdf_edit.find_replace(input_path, params["replacements"], console, output_path=out)
        elif target_format == "__pdf_imgs_embedded":
            from transcripe.engines import pdf_edit
            pdf_edit.extract_images(input_path, out, console)
        elif target_format == "__pdf_searchable":
            from transcripe.engines import pdf_edit
            pdf_edit.make_searchable(input_path, console, output_path=out, langs=params.get("langs"))
        elif target_format == "__ocr":
            images.convert_image(input_path, "txt", console, output_path=out, langs=params.get("langs"))
        elif target_format == "__resize":
            images.resize_image(input_path, params["width"], params["height"], console, output_path=out)
        elif target_format == "__compress_img":
            images.compress_image(input_path, params["quality"], console, output_path=out)
        elif target_format == "__fit_size":
            images.fit_size(input_path, console, output_path=out,
                            min_bytes=params.get("min_bytes"),
                            max_bytes=params.get("max_bytes"), target_format="auto")
        elif target_format == "__img_pdf":
            images.image_to_pdf(input_path, console, output_path=out)
        elif target_format == "__json_pretty":
            data.json_prettify(input_path, console, output_path=out)
        elif target_format == "__json_minify":
            data.json_minify(input_path, console, output_path=out)
        elif target_format == "__fix_encoding":
            from transcripe.core import text_utils
            text_utils.reencode_to_utf8(input_path, console, output_path=out)
        elif target_format in ("__m_glb_web", "__m_glb", "__m_gltf", "__m_obj", "__m_stl", "__m_ply"):
            from transcripe.engines import models3d
            _fmt = {"__m_glb_web": "glb", "__m_glb": "glb", "__m_gltf": "gltf",
                    "__m_obj": "obj", "__m_stl": "stl", "__m_ply": "ply"}[target_format]
            models3d.convert_model(input_path, _fmt, console, output_path=out,
                                   optimize=(target_format == "__m_glb_web"), compress="draco")
        return _result_dir(out, output_dir, input_path)

    # ── Standard format routing ──
    target_format = target_format.lower().strip(".")

    out = explicit_out or _resolve_out(input_path, target_format, None, confirm_output, output_dir, console)

    if ext in VIDEO_EXTS or ext in AUDIO_EXTS:
        if target_format in ("txt", "srt"):
            capabilities.require("transcribe")
            audio_video.transcribe(input_path, target_format, console, output_path=out)
        elif target_format in MEDIA_AUDIO_TARGETS or target_format in MEDIA_VIDEO_TARGETS:
            capabilities.require("media_convert")
            audio_video.convert_media(input_path, target_format, console, output_path=out)
        else:
            raise ValueError(f"Cannot convert video/audio to .{target_format}")

    elif ext in PDF_EXTS:
        if target_format == "txt":
            capabilities.require("pdf_text")
            documents.pdf_to_text(input_path, console, output_path=out)
        elif target_format == "docx" and capabilities.can("pdf_docx"):
            # Layout-preserving Word export (tables/columns/images) via pdf2docx.
            from transcripe.engines import pdf_edit
            pdf_edit.pdf_to_docx_layout(input_path, console, output_path=out)
        elif target_format in ("md", "html", "docx"):
            capabilities.require("pdf_text")
            capabilities.require("pandoc")
            documents.pdf_to_document(input_path, target_format, console, output_path=out)
        else:
            raise ValueError(f"Cannot convert PDF to .{target_format}")

    elif ext in DOC_EXTS:
        if target_format == "pdf":
            capabilities.require("doc_to_pdf")
            documents.convert_document_to_pdf_engine(input_path, console, output_path=out)
        elif ext in documents.PANDOC_UNREADABLE:
            # Pandoc has no reader for .doc/.ppt/.pptx — go through LibreOffice.
            capabilities.require("doc_to_pdf")
            documents.convert_office_via_libreoffice(input_path, target_format, console, output_path=out)
        else:
            capabilities.require("pandoc")
            documents.convert_with_pandoc(input_path, target_format, console, output_path=out)

    elif ext in SUBTITLE_EXTS:
        from transcripe.engines import subtitles
        subtitles.convert_subtitle(input_path, target_format, console, output_path=out)

    elif ext in DATA_EXTS:
        _new_frame = (ext in {".tsv", ".ndjson", ".jsonl", ".parquet"}
                      or target_format in ("parquet", "tsv", "ndjson"))
        if _new_frame:
            capabilities.require("data_basic")
            if ext == ".parquet" or target_format == "parquet":
                capabilities.require("data_parquet")
            data.dataframe_convert(input_path, target_format, console, output_path=out)
        elif ext == ".csv" and target_format == "json":
            capabilities.require("data_basic")
            data.csv_to_json(input_path, console, output_path=out)
        elif ext == ".csv" and target_format == "xlsx":
            capabilities.require("data_excel")
            data.csv_to_excel(input_path, console, output_path=out)
        elif ext == ".json" and target_format == "csv":
            capabilities.require("data_basic")
            data.json_to_csv(input_path, console, output_path=out)
        elif ext == ".json" and target_format == "yaml":
            capabilities.require("data_yaml")
            data.json_to_yaml(input_path, console, output_path=out)
        elif ext in (".yaml", ".yml") and target_format == "json":
            capabilities.require("data_yaml")
            data.yaml_to_json(input_path, console, output_path=out)
        elif ext in (".xls", ".xlsx", ".ods") and target_format == "csv":
            capabilities.require("data_excel")
            data.excel_to_csv(input_path, console, output_path=out)
        elif ext in (".xls", ".xlsx", ".ods") and target_format == "json":
            capabilities.require("data_excel")
            data.excel_to_json(input_path, console, output_path=out)
        elif ext == ".xml" and target_format == "json":
            data.xml_to_json(input_path, console, output_path=out)
        else:
            raise ValueError(f"Cannot convert {ext} to .{target_format}")

    elif ext in IMAGE_EXTS:
        capabilities.require("image_ops")
        if target_format == "pdf":
            images.image_to_pdf(input_path, console, output_path=out)
        elif target_format == "txt":
            capabilities.require("ocr")
            images.convert_image(input_path, target_format, console, output_path=out)
        else:
            images.convert_image(input_path, target_format, console, output_path=out)

    else:
        raise ValueError(f"Unsupported format: {ext}")

    return _result_dir(out, output_dir, input_path)


# ── Multi-file conversion ────────────────────────────────────────────────

def _ask_batch_output_dir(default_dir: Path, console: Console) -> Path | None:
    """Ask whether all batch outputs go into one folder. Returns a dir or None (in-place)."""
    choice = questionary.select(
        "Where should the converted files be saved?",
        choices=[
            "📂  Next to each original file (Recommended)",
            "🗂️   All together in one folder…",
        ],
        style=THEME,
    ).ask()
    if choice and "one folder" in choice:
        raw = questionary.path("Output folder:", default=str(default_dir), style=THEME).ask()
        if raw and str(raw).strip():
            d = Path(str(raw).strip().strip("'\"")).expanduser().resolve()
            d.mkdir(parents=True, exist_ok=True)
            console.print(f"[green]All files will be saved to:[/green] [underline]{d}[/underline]")
            return d
    return None


def _default_workers() -> int:
    """Default parallel worker count (overridable via TRANSCRIPE_WORKERS)."""
    env = os.environ.get("TRANSCRIPE_WORKERS")
    if env and env.isdigit() and int(env) > 0:
        return int(env)
    return min(4, os.cpu_count() or 1)


def _is_ml_batch(files: list[Path], fmt: str | None) -> bool:
    """Detect ML work (Whisper transcription / EasyOCR) that must stay sequential."""
    if not fmt:
        return True  # interactive per-file → sequential
    for f in files:
        ext = f.suffix.lower()
        if fmt in ("txt", "srt") and (ext in VIDEO_EXTS or ext in AUDIO_EXTS):
            return True
        if fmt == "txt" and ext in IMAGE_EXTS:
            return True
    return False


def _run_batch(files: list[Path], fmt: str | None, output_dir: Path | None,
               console: Console, workers: int = 1):
    """Run a conversion over many files with a rich progress bar. Returns (ok, failed, dirs).

    workers > 1 runs conversions concurrently; each worker uses its own buffered
    console so only the shared progress bar renders (no interleaved spinners).
    """
    ok: list[Path] = []
    failed: list[tuple[Path, str]] = []
    dirs: set[Path] = set()

    # Interactive per-file mode: questionary prompts conflict with a live
    # progress display (prompt_toolkit vs rich.Live) — use a plain loop.
    if fmt is None:
        for i, f in enumerate(files, 1):
            console.print(f"\n[bold cyan]({i}/{len(files)})[/bold cyan] [cyan]{f.name}[/cyan]")
            try:
                d = _process_single_file(f, None, console, confirm_output=False, output_dir=output_dir)
                ok.append(f)
                if d:
                    dirs.add(d)
            except UserCancelled:
                raise
            except Exception as e:
                failed.append((f, str(e)))
                console.print(f"  [dim red]⚠ Skipped {f.name}: {e}[/dim red]")
        return ok, failed, dirs

    progress = Progress(
        SpinnerColumn(style="magenta"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None, complete_style="green", finished_style="bright_green"),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )

    if workers <= 1:
        with progress:
            task = progress.add_task("Converting…", total=len(files))
            for f in files:
                progress.update(task, description=f"[cyan]{f.name}[/cyan]")
                try:
                    d = _process_single_file(f, fmt, console, confirm_output=False, output_dir=output_dir)
                    ok.append(f)
                    if d:
                        dirs.add(d)
                except Exception as e:
                    failed.append((f, str(e)))
                    console.print(f"  [dim red]⚠ Skipped {f.name}: {e}[/dim red]")
                progress.advance(task)
        return ok, failed, dirs

    # Parallel path — buffered console per task to avoid Live/spinner collisions.
    def _task(f: Path):
        buf = Console(file=io.StringIO(), width=100)
        d = _process_single_file(f, fmt, buf, confirm_output=False, output_dir=output_dir)
        return d

    with progress:
        task = progress.add_task(f"Converting ({workers} parallel)…", total=len(files))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_task, f): f for f in files}
            for fut in as_completed(futures):
                f = futures[fut]
                progress.update(task, description=f"[cyan]{f.name}[/cyan]")
                try:
                    d = fut.result()
                    ok.append(f)
                    if d:
                        dirs.add(d)
                except Exception as e:
                    failed.append((f, str(e)))
                    console.print(f"  [dim red]⚠ Skipped {f.name}: {e}[/dim red]")
                progress.advance(task)
    return ok, failed, dirs


def _print_batch_summary(ok: list[Path], failed: list[tuple[Path, str]], console: Console):
    table = Table(title="Batch Results", box=box.ROUNDED, border_style="cyan",
                  title_style="bold bright_cyan", show_lines=False)
    table.add_column("Status", width=8)
    table.add_column("File", style="white")
    table.add_column("Detail", style="dim")
    for f in ok:
        table.add_row("[green]✓[/green]", f.name, "converted")
    for f, err in failed:
        table.add_row("[red]✗[/red]", f.name, err)
    console.print(table)
    console.print(
        f"[bold green]{len(ok)} succeeded[/bold green]  ·  "
        f"[bold red]{len(failed)} failed[/bold red]"
    )


def _pick_workers(files: list[Path], fmt: str | None, console: Console) -> int:
    """Choose worker count: sequential for ML/interactive work, parallel otherwise."""
    if _is_ml_batch(files, fmt) or len(files) < 2:
        return 1
    workers = min(_default_workers(), len(files))
    if workers > 1:
        console.print(
            f"[dim]⚡ Running up to [bold]{workers}[/bold] conversions in parallel "
            f"(set TRANSCRIPE_WORKERS to change).[/dim]"
        )
    return workers


def dispatch_conversion(files: list[Path], target_format: str | None, console: Console):
    """Convert one or many files. Asks for format interactively if needed. Returns result dirs."""
    if len(files) == 1:
        d = _process_single_file(files[0], target_format, console)
        return {d} if d else set()

    # Multiple files: show what we have, ask for a format strategy
    console.print(f"[bold cyan]Processing {len(files)} files:[/bold cyan]")

    # Group by category
    categories = {}
    for f in files:
        cat = _get_ext_category(f.suffix.lower())
        categories.setdefault(cat, []).append(f)

    # If all same category, ask once
    if len(categories) == 1:
        cat = list(categories.keys())[0]
        if target_format is None:
            target_format = _ask_format_for_category(cat)
        output_dir = _ask_batch_output_dir(files[0].parent, console)
        workers = _pick_workers(files, target_format, console)
        ok, failed, dirs = _run_batch(files, target_format, output_dir, console, workers=workers)

    else:
        # Mixed types: ask per-file or use a uniform format
        strategy = _ask(questionary.select(
            "You selected files of different types. How should I convert them?",
            choices=[
                "🎯  Ask me for each file individually",
                "📄  Convert everything to Text (.txt)",
                "📕  Convert everything to PDF (.pdf)",
            ],
            style=THEME,
        ))

        fmt = None
        if "Text" in strategy: fmt = "txt"
        elif "PDF" in strategy: fmt = "pdf"

        output_dir = _ask_batch_output_dir(files[0].parent, console) if fmt else None
        workers = _pick_workers(files, fmt, console)
        ok, failed, dirs = _run_batch(files, fmt, output_dir, console, workers=workers)

    console.print()
    _print_batch_summary(ok, failed, console)
    console.print(f"\n[bold green]✓ Batch conversion complete![/bold green]")
    return dirs


def _ask_format_for_category(cat: str) -> str:
    """Ask the user for an output format based on file category."""
    if cat == "archive":
        return "extract"
    if cat in ("video", "audio"):
        c = _ask(questionary.select(
            "Output format for all video/audio files?",
            choices=["📝 Transcription (.txt)", "🎬 Subtitles (.srt)"],
            style=THEME,
        ))
        return "txt" if "Transcription" in c else "srt"

    elif cat in ("document", "pdf"):
        c = _ask(questionary.select(
            "Output format for all documents?",
            choices=[
                "📕 PDF (.pdf)", "📝 Markdown (.md)", "🌐 HTML (.html)",
                "📄 Word (.docx)", "📃 Plain Text (.txt)",
            ],
            style=THEME,
        ))
        if "PDF" in c:        return "pdf"
        elif "Markdown" in c: return "md"
        elif "HTML" in c:     return "html"
        elif "Word" in c:     return "docx"
        else:                 return "txt"

    elif cat == "image":
        c = _ask(questionary.select(
            "Output format for all images?",
            choices=[
                "📝 Extract Text – OCR (.txt)", "🖼️  PNG", "🖼️  WebP", "🖼️  JPEG",
            ],
            style=THEME,
        ))
        if "OCR" in c:   return "txt"
        elif "PNG" in c: return "png"
        elif "WebP" in c: return "webp"
        else:            return "jpg"

    return _ask(questionary.text("Enter target extension:", style=THEME)) or "txt"


# ── Merge Engine ──────────────────────────────────────────────────────────

def dispatch_merge(files: list[Path], console: Console):
    """Interactive merge wizard for combining multiple files."""
    if len(files) < 2:
        raise ValueError("You need at least 2 files to merge.")

    # Show files in order
    table = Table(title="Files to Merge (in this order)", box=box.ROUNDED, border_style="cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("File", style="cyan")
    table.add_column("Type", style="yellow")
    for i, f in enumerate(files, 1):
        table.add_row(str(i), f.name, get_file_category(f))
    console.print(table)

    # Reorder?
    reorder = questionary.confirm("Would you like to reorder these files?", default=False, style=THEME).ask()
    if reorder:
        console.print("[dim]Enter the new order as numbers separated by spaces (e.g., 3 1 2):[/dim]")
        order_str = questionary.text("New order:", style=THEME).ask()
        try:
            indices = [int(x) - 1 for x in order_str.split()]
            files = [files[i] for i in indices]
            console.print("[green]✓ Files reordered.[/green]")
        except Exception:
            console.print("[yellow]Invalid order. Keeping original sequence.[/yellow]")

    # Detect what kind of merge is possible
    exts = {f.suffix.lower() for f in files}
    all_text   = all(_get_ext_category(e) in ("document",) for e in exts) or all(e in (".txt", ".md") for e in exts)
    all_images = all(e in IMAGE_EXTS for e in exts)
    all_pdf    = all(e in (".pdf",) for e in exts)
    all_audio  = all(e in AUDIO_EXTS or e in VIDEO_EXTS for e in exts)

    # Choose merge type
    merge_choices = []
    if all_text or all_pdf:
        merge_choices.append("📄  Merge into a single Text file (.txt)")
        merge_choices.append("📝  Merge into a single Markdown file (.md)")
    if all_pdf:
        merge_choices.append("📕  Merge PDFs into one PDF")
    if all_images:
        merge_choices.append("📕  Combine images into a single PDF")
        merge_choices.append("🖼️   Stitch images vertically into one image")
        merge_choices.append("🖼️   Create a side-by-side collage")
    if all_audio:
        merge_choices.append("🎵  Concatenate audio/video into one file")
    # Always available
    merge_choices.append("📃  Merge all content into a single Text file")

    merge_type = _ask(questionary.select(
        "How would you like to merge these files?",
        choices=merge_choices,
        style=THEME,
    ))

    # Output location
    default_out = files[0].parent / f"merged_output{_ext_for_merge(merge_type)}"
    out_path_str = _ask(questionary.text(
        f"Where should I save the merged file?",
        default=str(default_out),
        style=THEME,
    ))
    out_path = Path(out_path_str).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Execute merge. NOTE: text merges prompt for a separator, so they must not run
    # inside a live spinner (prompt_toolkit and rich.Live conflict).
    is_text_merge = ("Text" in merge_type or "Markdown" in merge_type or
                     not any(k in merge_type.lower() for k in ("image", "pdf", "audio", "stitch", "collage")))

    def _do_merge():
        if "PDF" in merge_type and "images" in merge_type.lower():
            _merge_images_to_pdf(files, out_path, console)
        elif "Stitch" in merge_type or "vertically" in merge_type.lower():
            _merge_images_vertical(files, out_path, console)
        elif "collage" in merge_type.lower():
            _merge_images_collage(files, out_path, console)
        elif "PDFs into one" in merge_type:
            _merge_pdfs(files, out_path, console)
        elif "Concatenate audio" in merge_type:
            _merge_audio(files, out_path, console)
        else:
            _merge_text_files(files, out_path, merge_type, console)

    if is_text_merge:
        _do_merge()
    else:
        with console.status(f"[bold cyan]Merging {len(files)} files…[/bold cyan]"):
            _do_merge()

    console.print(f"\n[bold green]✓ Merged! Saved to:[/bold green] [underline]{out_path}[/underline]")
    return {out_path.parent}


def _ext_for_merge(merge_type: str) -> str:
    if "PDF" in merge_type:  return ".pdf"
    if "Markdown" in merge_type: return ".md"
    if "image" in merge_type.lower() and "Stitch" in merge_type: return ".png"
    if "collage" in merge_type.lower(): return ".png"
    if "audio" in merge_type.lower(): return ".mp4"
    return ".txt"


def _read_text_for_merge(f: Path) -> str:
    """Extract text from a file for text merges — handles PDFs and rich documents."""
    ext = f.suffix.lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(f))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as e:
            return f"[Could not extract PDF text from {f.name}: {e}]\n"
    if ext in (".docx", ".doc", ".odt", ".rtf", ".epub", ".html", ".htm"):
        try:
            import pypandoc
            return pypandoc.convert_file(str(f), "plain")
        except Exception:
            pass  # fall through to plain read
    from transcripe.core import text_utils
    text, enc = text_utils.read_text_safe(f)
    corrupt, reason = text_utils.looks_corrupt(text)
    if corrupt:
        return f"[Could not read {f.name} as text — {reason}]\n"
    return text


def _merge_text_files(files: list[Path], out_path: Path, merge_type: str, console: Console):
    """Merge text/document files into a single text or markdown file."""
    # Ask for separator
    sep_choice = _ask(questionary.select(
        "How should files be separated in the merged document?",
        choices=[
            "📏  Horizontal line (---)",
            "📄  Filename as header",
            "🔢  Numbered sections",
            "⬜  Blank line only",
            "🚫  No separator (continuous)",
        ],
        style=THEME,
    ))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as out:
        for i, f in enumerate(files):
            # Write separator
            if i > 0:
                if "Horizontal" in sep_choice:
                    out.write("\n\n---\n\n")
                elif "Filename" in sep_choice:
                    out.write(f"\n\n## {f.name}\n\n")
                elif "Numbered" in sep_choice:
                    out.write(f"\n\n## Section {i + 1}: {f.stem}\n\n")
                elif "Blank" in sep_choice:
                    out.write("\n\n")
                # No separator: nothing

            out.write(_read_text_for_merge(f))
            console.print(f"  [dim]+ {f.name}[/dim]")


def _merge_images_to_pdf(files: list[Path], out_path: Path, console: Console):
    """Combine images into a single PDF document."""
    from PIL import Image
    images_list = []
    for f in files:
        img = Image.open(f).convert("RGB")
        images_list.append(img)
        console.print(f"  [dim]+ {f.name} ({img.width}x{img.height})[/dim]")
    if images_list:
        images_list[0].save(out_path, save_all=True, append_images=images_list[1:])


def _merge_images_vertical(files: list[Path], out_path: Path, console: Console):
    """Stitch images vertically into one tall image."""
    from PIL import Image
    imgs = [Image.open(f) for f in files]
    max_w = max(im.width for im in imgs)
    total_h = sum(im.height for im in imgs)
    result = Image.new("RGB", (max_w, total_h), (255, 255, 255))
    y = 0
    for im, f in zip(imgs, files):
        result.paste(im, (0, y))
        y += im.height
        console.print(f"  [dim]+ {f.name}[/dim]")
    result.save(out_path)


def _merge_images_collage(files: list[Path], out_path: Path, console: Console):
    """Create a side-by-side collage from images."""
    from PIL import Image
    imgs = [Image.open(f) for f in files]
    max_h = max(im.height for im in imgs)
    total_w = sum(im.width for im in imgs)
    result = Image.new("RGB", (total_w, max_h), (255, 255, 255))
    x = 0
    for im, f in zip(imgs, files):
        result.paste(im, (x, 0))
        x += im.width
        console.print(f"  [dim]+ {f.name}[/dim]")
    result.save(out_path)


def _merge_pdfs(files: list[Path], out_path: Path, console: Console):
    """Merge multiple PDF files into one (pypdf 3+ / 5+ compatible: PdfWriter.append)."""
    try:
        from pypdf import PdfWriter
    except ImportError as e:
        raise RuntimeError("PDF merging requires 'pypdf' — pip install pypdf") from e

    writer = PdfWriter()
    for f in files:
        writer.append(str(f))
        console.print(f"  [dim]+ {f.name}[/dim]")
    with open(out_path, "wb") as fh:
        writer.write(fh)
    writer.close()


def _merge_audio(files: list[Path], out_path: Path, console: Console):
    """Concatenate audio/video files using FFmpeg."""
    import shutil, tempfile
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg not found. Please install FFmpeg.")

    # Create a concat list file. ffmpeg concat syntax: escape ' as '\'' inside quotes.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
        for f in files:
            escaped = str(f).replace("'", "'\\''")
            tmp.write(f"file '{escaped}'\n")
            console.print(f"  [dim]+ {f.name}[/dim]")
        list_path = tmp.name

    import subprocess
    try:
        result = subprocess.run(
            [ffmpeg, "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", str(out_path), "-y"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            err = result.stderr.strip().splitlines()[-1] if result.stderr else "unknown error"
            raise RuntimeError(
                f"FFmpeg concat failed: {err} "
                "(files may use different codecs — convert them to the same format first)")
    finally:
        Path(list_path).unlink(missing_ok=True)
