# ⚡ Transcripe

**The Universal Semantic File Converter, Merger & Transcriber — 100% local.**

Transcripe is an interactive command‑line tool that converts, merges, extracts, and
transcribes almost any file — video, audio, documents, PDFs, images, and data — using
AI (Whisper, EasyOCR) and best‑in‑class engines (FFmpeg, LibreOffice, Pandoc, Poppler).
Everything runs on **your machine**. No uploads, no cloud, no tracking.

```
████████╗██████╗  █████╗ ███╗   ██╗███████╗ ██████╗██████╗ ██╗██████╗ ███████╗
╚══██╔══╝██╔══██╗██╔══██╗████╗  ██║██╔════╝██╔════╝██╔══██╗██║██╔══██╗██╔════╝
   ██║   ██████╔╝███████║██╔██╗ ██║███████╗██║     ██████╔╝██║██████╔╝█████╗
   ██║   ██╔══██╗██╔══██║██║╚██╗██║╚════██║██║     ██╔══██╗██║██╔═══╝ ██╔══╝
   ██║   ██║  ██║██║  ██║██║ ╚████║███████║╚██████╗██║  ██║██║██║     ███████╗
   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝╚═╝     ╚══════╝
```

---

## ✨ Features

### 🎬 Video & 🎵 Audio
- **Transcribe** to text (`.txt`) or subtitles (`.srt`) with **Whisper** (GPU‑accelerated when available)
- **Extract audio** from video (`.mp4` → `.mp3` / `.wav` / `.flac`)
- **Convert** between any media format (`.mkv` → `.mp4`, `.wav` → `.ogg`, …)
- **Video → GIF** (optimized two‑pass palette encoding)
- **Compress** video (high / medium / low presets)
- **Trim / clip** by start–end time
- **Extract frames** as PNG images at a chosen FPS

### 📄 Documents
- Convert `.docx`, `.pptx`, `.ppt`, `.odt`, `.epub`, `.rtf` → **PDF** (auto‑picks MS Office for high fidelity when installed, else LibreOffice)
- Convert `.docx` / `.pptx` → **Markdown / HTML / plain text** (Pandoc)

### 📕 PDF
- **✏️ Edit in browser** — converts any PDF (text **or scanned**) into an editable HTML
  page that *keeps the original design*: text-layer pages use exact position/size/color
  spans; scanned pages use OCR overlays. Click any text, edit, then either press the
  Save-as-PDF button or run `transcripe pdf render edited.html` — the round-trip prints
  through headless Chromium (WeasyPrint fallback) with a real text layer.
- **🔁 Find & Replace** — redact + reinsert text directly in the PDF (RTL/Arabic aware)
- **🪄 Make searchable** — add an invisible OCR text layer to scanned PDFs (OCRmyPDF)
- **Word export (layout-preserving)** — PDF → `.docx` keeping tables/columns/images (pdf2docx)
- **Extract text** (no OCR needed for text‑based PDFs)
- **OCR** scanned / image‑based PDFs → text (renders pages, then reads with AI)
- **Pages → images** (PNG) · **Extract embedded images**
- **Split / extract pages** (e.g. `3-7` or `1,4,9-12`)
- Convert to **Markdown / HTML** (text is extracted first, then rendered)

### 🖼️ Images
- **OCR** — extract text with **RapidOCR** (fast, accurate, multilingual) and an **EasyOCR** fallback for extra scripts
- **Multi‑language OCR** — auto (Latin + Türkçe + numbers) or pick English / Turkish / Arabic / Chinese / custom codes
- **Convert** between `.png`, `.jpg`, `.webp`, `.bmp`, `.tiff`, `.gif`, `.heic`, `.avif`, and **`.svg`** (vector → full‑HD raster, `TRANSCRIPE_SVG_MIN` to tune)
- **Resize** (proportional or exact) and **compress** (quality control)
- **🎯 Fit a file‑size limit** — land under an upload cap (*“max 500 KB”*) or over a floor
  (Google's *“min 9.77 KB”*): `transcripe image fit-size photo.png --max 500KB`.
  Quality is spent in the order that costs least — colour detail, then compression,
  and only then resolution — so the picture keeps the size it had on screen unless
  the budget leaves no other way. The search is a binary search encoded in memory,
  so it lands *just* under the limit (typically 90–99% of the budget used) instead
  of far below it. A photo saved as PNG is re‑encoded rather than shrunk;
  `--format same` keeps the original format, `--format jpg|webp|png|avif` pins one.
- **Image → PDF**

### 💬 Subtitles
- Convert between **SRT ↔ VTT ↔ ASS**, or strip timing to plain text
- **Burn‑in** — hard‑burn subtitles into a video (FFmpeg)

### 📊 Data
- **CSV ↔ JSON ↔ YAML**, **CSV → Excel**, **Excel → CSV / JSON** (multi‑sheet aware)
- **Parquet / NDJSON / TSV** any‑to‑any, **XML → JSON**, JSON **prettify / minify**

### 🗜️ Archives
- **List / extract** `.zip`, `.tar(.gz/.bz2/.xz)`, `.gz`, `.7z`, `.rar` (with Zip‑Slip protection)
- **Extract‑and‑convert** — unpack an archive and convert the files inside in one step
- **Create** archives (`.zip`, `.tar.gz`, `.7z`) from selected files
- *RAR extraction needs the `unar` (or `unrar`) binary — installed automatically by `install.sh`*

### 🧊 3D Models (for the web)
- Convert `.3ds`, `.fbx`, `.obj`, `.dae`, `.stl`, `.ply`, `.glb`, `.gltf`, … → **web‑ready GLB**
- **Draco compression** + WebP textures — typically **90–97% smaller** (e.g. a 31 MB car → ~1.9 MB, a `.3ds` → ~0.75 MB)
- Also export to plain GLB / glTF, and **OBJ / STL / PLY** (via trimesh)
- Powered by a bundled Node toolchain (**assimp** import + **glTF‑Transform** optimize); installed on first use

### 🩹 Robustness (corrupted files & weird characters)
- **Encoding auto‑detection** — reads non‑UTF‑8 text (Latin‑1/CP1252/CP1250/ISO‑8859‑9…) correctly instead of mojibake
- **"Fix encoding → UTF‑8"** action re‑saves garbled text files cleanly
- **Corruption detection** — warns when extracted/merged text looks like garbage (binary, wrong encoding, replacement chars) instead of writing junk

### 🔗 Merge
- **Text/Docs** — merge with separators (rules, filename headers, numbered sections); PDFs & DOCX are text‑extracted automatically
- **Images** — combine into a PDF, stitch vertically, or side‑by‑side collage
- **PDFs** — merge many into one
- **Audio/Video** — concatenate with FFmpeg

### 🤖 Smart interactive agent
- Big animated banner + themed, arrow‑key menus (Rich + Questionary + pyfiglet)
- **Auto‑detects** each file's type and **recommends** the best action
- **Shows where output will be saved** and lets you change it (with overwrite protection)
- **Batch mode** — convert many files at once, optionally into a single folder
- **Parallel processing** for subprocess conversions (≈**3× faster** batches)
- Native file browser (Zenity on Linux, tkinter on macOS/Windows), drag‑and‑drop, and turbo filename search
- Offers to open the output folder when finished

---

## 📦 Installation

### pip (lean core + pick your features)
```bash
pip install transcripe                # core CLI/TUI (subtitles, archives, encoding)
pip install 'transcripe[pdf,docs]'    # + PDF editing & document conversion
pip install 'transcripe[all]'         # everything (Whisper, OCR, data, 3D…)
```
Features auto-enable based on what's installed — `transcripe --doctor` shows the map.

### Linux / macOS (one command, full setup)
```bash
git clone https://github.com/abdulrahmanJAlabbed/Convert.git transcripe
cd transcripe
./install.sh
```
`install.sh` auto‑detects your package manager (apt / dnf / pacman / Homebrew), installs the
system tools, creates a virtualenv, installs Python deps, and adds a global `transcripe` command.

### Windows
```powershell
git clone https://github.com/abdulrahmanJAlabbed/Convert.git transcripe
cd transcripe
python -m venv venv
venv\Scripts\pip install -r requirements.txt -e .
venv\Scripts\python cli.py
```
Then install the system tools (see below) and make sure they're on your `PATH`.

### System prerequisites

| Tool         | Used for                     | Linux (apt)             | macOS (brew)              | Windows            |
|--------------|------------------------------|-------------------------|---------------------------|--------------------|
| **Python 3.10+** | everything               | `python3`               | `python`                  | python.org         |
| **FFmpeg**   | audio/video                  | `ffmpeg`                | `ffmpeg`                  | choco / gyan.dev   |
| **LibreOffice** | documents → PDF           | `libreoffice`           | `--cask libreoffice`      | libreoffice.org    |
| **Poppler**  | PDF → images                 | `poppler-utils`         | `poppler`                 | conda / release    |
| **Pandoc**   | document formats             | `pandoc`                | `pandoc`                  | choco / pandoc.org |
| **unar**     | RAR extraction               | `unar`                  | `unar`                    | choco (`unar`)     |
| **Node.js**  | 3D model conversion          | `nodejs npm`            | `node`                    | nodejs.org         |

> Pandoc can also self‑install: `python -c "import pypandoc; pypandoc.download_pandoc()"`.
> Whisper and EasyOCR models download automatically on first use into `model_cache/`.
> **Optional (Windows/macOS):** `pip install docx2pdf` + MS Office enables the high‑fidelity
> Office backend for `.docx`/`.pptx`; Transcripe auto‑detects it and falls back to LibreOffice otherwise.

---

## 🚀 Usage

### Interactive mode (recommended)
```bash
transcripe
```
The agent guides you through file selection → detected type → recommended action → output location.

### Full-screen TUI
```bash
transcripe ui
```
A complete terminal app (Textual): directory-tree file browser on the left,
selection table on the right, category-aware action picker, and a live
conversion dashboard with per-file status + streaming engine log.
Keys: `Enter` add file · `c` convert · `x` remove · `C` clear · `h` hidden files · `q` quit.

### Direct mode
```bash
transcripe lecture.mp4 --to srt      # transcribe to subtitles
transcripe slides.pptx --to pdf      # PowerPoint → PDF
transcripe report.docx --to md       # Word → Markdown
transcripe data.csv   --to json      # CSV → JSON
transcripe scan.png   --to txt       # OCR
```

### Subcommands (scripting / automation — no prompts)
```bash
transcripe convert *.docx --to pdf --out-dir ./pdfs   # batch, one folder
transcripe ui                                        # full-screen TUI
transcripe pdf edit cv.pdf                            # → editable HTML, design kept
transcripe pdf render cv_editable.html               # edited HTML → PDF (round-trip)
transcripe pdf replace cv.pdf -f "old@mail.com" -t "new@mail.com"
transcripe pdf searchable scan.pdf --lang en,tr       # invisible OCR text layer
transcripe pdf split report.pdf --pages 1-5           # extract pages
transcripe pdf merge a.pdf b.pdf c.pdf -o all.pdf
transcripe pdf ocr scan.pdf --lang ar,en              # scanned PDF → text
transcripe pdf pages file.pdf                         # pages → PNGs
transcripe pdf extract-images file.pdf                # embedded images
transcripe media transcribe talk.mp4 --srt --translate   # → English subtitles
transcripe media burn clip.mp4 --subs clip.srt        # hard-burn subtitles
transcripe media gif clip.mp4 --fps 12 --width 640
transcripe media trim talk.mp4 --start 00:01:00 --end 00:05:00
transcripe media compress video.mp4 -q low
transcripe media concat part1.mp3 part2.mp3 -o full.mp3
transcripe image resize photo.jpg --width 1200
transcripe image compress photo.jpg -q 50
transcripe image fit-size photo.png --max 500KB       # land under an upload limit
transcripe image fit-size logo.png --min 9.77KB      # meet a platform size floor
transcripe convert subs.srt --to vtt                  # subtitle format convert
transcripe convert data.csv --to parquet              # tabular any-to-any
transcripe data pretty api_response.json
transcripe archive extract backup.rar
transcripe archive create -o bundle.zip file1 file2
transcripe model convert car.fbx                      # → web-ready Draco GLB
transcripe fix-encoding weird_chars.txt
```
Every command takes `-o/--output`; `--help` on any level lists options.

### Check your machine & verify quality
```bash
transcripe --doctor        # environment + capability report
transcripe --self-test     # run one real conversion per feature, show pass/fail
transcripe --self-test --slow   # also exercise the transcription pipeline
```

---

## ⚙️ Configuration (environment variables)

| Variable                 | Default            | Description                                        |
|--------------------------|--------------------|----------------------------------------------------|
| `TRANSCRIPE_MODEL`       | `large-v3`         | Whisper model (`tiny`,`base`,`small`,`medium`,`large-v3`) |
| `TRANSCRIPE_DEVICE`      | auto (`cuda`/`cpu`)| Force transcription device                          |
| `TRANSCRIPE_COMPUTE`     | `float16`/`int8`   | Compute type (GPU/CPU)                              |
| `TRANSCRIPE_BEAM`        | `5`                | Whisper beam size                                   |
| `TRANSCRIPE_WORKERS`     | `min(4, CPUs)`     | Parallel workers for batch conversions             |
| `TRANSCRIPE_DOC_BACKEND` | auto               | Force document→PDF backend (`libreoffice` / `msoffice`) |
| `TRANSCRIPE_HOST`        | `127.0.0.1`        | Studio bind address — `0.0.0.0` exposes it to your LAN  |
| `TRANSCRIPE_PORT`        | `8000`             | Studio port                                             |
| `TRANSCRIPE_TOKEN`       | auto on LAN        | Shared token for the studio API (see below)             |
| `TRANSCRIPE_MAX_UPLOAD_MB` | `2048`           | Reject uploads larger than this                         |
| `TRANSCRIPE_ORIGINS`     | site + dev ports   | Comma-separated CORS origins for the browser studio     |
| `TRANSCRIPE_NO_OPEN`     | unset              | Set to `1` to stop the studio opening a browser tab      |

Example — fast CPU transcription:
```bash
TRANSCRIPE_MODEL=small TRANSCRIPE_DEVICE=cpu transcripe lecture.mp4 --to txt
```

---

## 🖥️ Studio (browser + phone)

Beyond the CLI, Transcripe ships a local studio for the everyday jobs —
converting media and grabbing links.

```bash
pip install "transcripe[studio]"
cd web && npm install && npm run build && cd ..   # builds the UI (git checkout only)
transcripe studio                                  # http://localhost:8000/transcripe/
```

One process, one command: it serves the built UI *and* the conversion API, and
opens your browser. Drop a file anywhere on the page, or paste a link anywhere,
and it converts locally — including Whisper transcription to `.srt`/`.txt`,
which runs as a background job you can watch (and cancel). Drop an image and a
**Maximum size** row appears: pick 500 KB, 1 MB, 2 MB or type your own, and the
page fits it on your own machine through WebCodecs — the photo never leaves the
device to meet an upload limit. The phone app has the same control. Chrome and Edge offer to install it as a desktop app.
From a git checkout, `python server.py` does the same thing. Without a built
UI the API still runs — the studio says so instead of failing.

There's a public demo at **[alabed.site/transcripe](https://alabed.site/transcripe/)**.
It converts on that server rather than on your machine, and says so — the
private path is the local install above. Deploy it with:

```bash
./deploy.sh            # site + engine   (or: ./deploy.sh site | engine)
```

Every deploy backs up what it replaces into `/var/backups` on the VM. The demo
box has no Whisper, so it reports that through `/api/health` and the UI simply
doesn't offer transcription there.

A phone app lives in [`mobile/`](mobile/README.md) — Expo Go, same design, same
engine over your Wi-Fi:

```bash
transcripe studio --lan     # same as TRANSCRIPE_HOST=0.0.0.0
```

On loopback the studio needs no ceremony. The moment it's reachable from the
network it mints a token and prints the two lines to paste into `mobile/.env` —
these endpoints fetch arbitrary URLs (optionally with your browser cookies) and
write to your disk, which isn't something to leave open on café Wi-Fi. Set
`TRANSCRIPE_TOKEN` yourself to keep one token across restarts.

---

## 🧪 Testing

Transcripe ships a self-testing architecture so you always know *exactly* which
conversion works on a given machine:

- **`core/capabilities.py`** probes every dependency (FFmpeg, LibreOffice, MS Office,
  Poppler, Pandoc, RapidOCR/EasyOCR, Whisper, GPU…) and gates features accordingly.
- **`core/selftest.py`** generates synthetic fixtures and runs one real conversion
  per feature, returning a pass/fail/skip matrix.
- **`transcripe --self-test`** prints that matrix; missing‑dependency conversions
  are *skipped* (not failed), so the tool adapts to any environment.

Run the developer test suite with pytest (each conversion is an individual test,
and round‑trip data‑integrity checks guard import/export quality):
```bash
pip install -r requirements-dev.txt
pytest            # skips conversions whose tools aren't installed
pytest --slow     # include the transcription pipeline
```

---

## ⚡ Performance

- **Instant startup** — heavy ML libraries load lazily (≈0.1 s to first menu).
- **GPU auto‑detect** — Whisper uses CUDA when available, else CPU (verified ~6× real‑time on GPU).
- **Model caching** — the Whisper model loads once and is reused across a batch.
- **Parallel batches** — independent conversions run concurrently (measured **2.8×** on LibreOffice PPTX→PDF). Transcription/OCR stay sequential for stability.
- **Document fidelity** — auto‑selects MS Office for `.docx/.pptx` when installed (Windows/macOS), else LibreOffice; MS Office failures self‑heal to LibreOffice.

---

## 🏗️ Architecture

```
transcripe/
├── src/transcripe/            # the installable package (src layout)
│   ├── cli.py                 # Typer entry point, banner, wizard, --doctor/--self-test
│   ├── commands.py            # 25 non-interactive subcommands (pdf/media/image/data/…)
│   ├── tui.py                 # full-screen TUI (`transcripe ui`, Textual)
│   ├── core/
│   │   ├── dispatcher.py      # file routing, batch/parallel engine, merge logic
│   │   ├── capabilities.py    # environment detection + feature gating
│   │   ├── selftest.py        # fixture generation + per-conversion smoke tests
│   │   ├── text_utils.py      # encoding detection/repair, corruption checks
│   │   └── doctor.py          # --doctor / --self-test reports
│   └── engines/
│       ├── audio_video.py     # Whisper (transcribe/translate) + FFmpeg ops
│       ├── documents.py       # LibreOffice + Pandoc + WeasyPrint + pypdf
│       ├── pdf_edit.py        # edit-in-browser, find/replace, pdf2docx, OCRmyPDF
│       ├── subtitles.py       # SRT/VTT/ASS convert + burn-in
│       ├── images.py          # Pillow ops (+HEIC/AVIF/SVG) + OCR
│       ├── ocr.py             # RapidOCR primary + EasyOCR fallback, box output
│       ├── archive.py         # zip/tar/gz/7z/rar with traversal protection
│       ├── models3d.py        # assimp import + glTF-Transform optimize
│       ├── js/                # bundled Node toolchain (installed on first use)
│       └── data.py            # csv/tsv/json/ndjson/parquet/xlsx/yaml/xml
├── tests/                     # pytest suite (parametrized over the self-test matrix)
├── install.sh                 # cross-platform installer
├── pyproject.toml             # packaging (extras: whisper/ocr/pdf/docs/…)
└── requirements.txt           # full install (== transcripe[all])
```
Whisper/OCR models cache in `~/.cache/transcripe/` (override: `TRANSCRIPE_CACHE`).

---

## ⚠️ Known limitations

- **OCR** uses RapidOCR by default (great for Latin scripts + Turkish + numbers); for Arabic / Chinese / Cyrillic / Indic it automatically switches to EasyOCR language packs. Very low‑quality photos may still drop spaces in dense lines.
- System tools (FFmpeg / LibreOffice / Poppler) must be installed separately on macOS/Windows.
- The code paths are written cross‑platform (macOS/Windows branches for the file browser, folder‑open, and search), but the maintainers primarily test on Linux.

---

## 🔒 Privacy

Everything runs **100% locally**. Your files never leave your machine.

## 📄 License

MIT
