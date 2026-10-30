"""`transcripe doctor` — environment report + optional conversion self-test."""
from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich import box

from transcripe.core import capabilities, selftest


def print_environment(console: Console) -> None:
    caps = capabilities.probe()
    table = Table(title="🩺 Environment", box=box.ROUNDED, border_style="cyan",
                  title_style="bold bright_cyan", show_lines=False)
    table.add_column("Component", style="bold")
    table.add_column("Status", width=8, justify="center")
    table.add_column("Detail", style="dim")
    table.add_column("Used for", style="dim")

    order = ["ffmpeg", "libreoffice", "msoffice", "poppler", "pandoc", "node",
             "rapidocr", "easyocr", "faster_whisper", "pypdf", "pdf2image",
             "fitz", "pdf2docx", "ocrmypdf", "weasyprint", "chromium",
             "pandas", "openpyxl", "pyarrow", "yaml", "charset_normalizer", "py7zr", "rarfile",
             "trimesh", "PIL", "gpu"]
    for key in order:
        c = caps.get(key)
        if not c:
            continue
        mark = "[green]✓[/green]" if c.ok else "[red]✗[/red]"
        detail = c.detail if c.ok else f"[yellow]{c.hint}[/yellow]"
        table.add_row(c.label, mark, detail, c.used_for)
    console.print(table)

    # Feature readiness
    feats = ["transcribe", "media_convert", "doc_to_pdf", "pandoc",
             "pdf_text", "pdf_images", "pdf_ocr", "ocr",
             "pdf_edit", "pdf_docx", "pdf_searchable", "md_pdf",
             "image_ops", "data_basic", "data_excel", "data_yaml", "data_parquet", "subtitles",
             "archive", "archive_7z", "archive_rar", "model3d", "model3d_mesh"]
    ft = Table(title="Feature readiness", box=box.SIMPLE_HEAD, border_style="dim")
    ft.add_column("Feature", style="bold")
    ft.add_column("Ready", justify="center")
    for f in feats:
        ok = capabilities.can(f)
        ft.add_row(f, "[green]yes[/green]" if ok else "[red]no[/red]")
    console.print(ft)


def print_selftest(console: Console, include_slow: bool = False) -> int:
    console.print("\n[bold cyan]Running conversion self-tests…[/bold cyan] "
                  "[dim](synthetic fixtures, temp files)[/dim]\n")
    results = selftest.run_all(include_slow=include_slow)

    table = Table(title="🧪 Conversion self-test", box=box.ROUNDED,
                  border_style="cyan", title_style="bold bright_cyan", show_lines=False)
    table.add_column("Category", style="yellow")
    table.add_column("Conversion", style="white")
    table.add_column("Result", width=8, justify="center")
    table.add_column("Detail", style="dim")

    marks = {"pass": "[green]PASS[/green]", "fail": "[red]FAIL[/red]", "skip": "[dim]skip[/dim]"}
    for r in results:
        table.add_row(r.category, r.name, marks[r.status], r.detail)
    console.print(table)

    p, f, s = selftest.summarize(results)
    color = "green" if f == 0 else "red"
    console.print(f"\n[bold {color}]{p} passed[/bold {color}]  ·  "
                  f"[bold red]{f} failed[/bold red]  ·  [dim]{s} skipped[/dim]")
    return f


def run(console: Console | None = None, do_selftest: bool = False, include_slow: bool = False) -> int:
    console = console or Console()
    print_environment(console)
    failures = 0
    if do_selftest:
        failures = print_selftest(console, include_slow=include_slow)
    return failures
