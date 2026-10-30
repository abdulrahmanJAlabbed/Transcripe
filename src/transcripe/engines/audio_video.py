import time
from pathlib import Path
from rich.console import Console
import os
import shutil

# Model cache lives outside the package (src layout): ~/.cache/transcripe by
# default, overridable with TRANSCRIPE_CACHE.
CACHE_DIR = Path(os.environ.get("TRANSCRIPE_CACHE",
                                Path.home() / ".cache" / "transcripe")) / "model_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(CACHE_DIR))

MODEL_SIZE = os.environ.get("TRANSCRIPE_MODEL", "large-v3")
BEAM_SIZE = int(os.environ.get("TRANSCRIPE_BEAM", "5"))

# Cached Whisper model so batches don't reload it for every file.
_MODEL = None
_MODEL_KEY = None


def _load_pip_cuda() -> None:
    """Make CUDA libraries installed from pip visible to CTranslate2.

    The nvidia-cublas-cu12 / nvidia-cudnn-cu12 wheels (the [gpu] extra) put
    their libraries inside site-packages, where the dynamic linker never
    looks. Loading them here by full path, globally, means CTranslate2's own
    dlopen("libcublas.so.12") finds them already resident — no
    LD_LIBRARY_PATH to set before the process starts. A no-op without them.
    """
    import ctypes
    import glob
    import importlib.util

    libs = []
    for package in ("nvidia.cublas", "nvidia.cudnn"):
        spec = importlib.util.find_spec(package)
        for root in (spec.submodule_search_locations or []) if spec else []:
            libs += sorted(glob.glob(os.path.join(root, "lib", "*.so*")))
    # cuDNN's pieces depend on one another; keep passing over the rest until
    # a pass loads nothing new.
    while libs:
        failed = []
        for lib in libs:
            try:
                ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                failed.append(lib)
        if len(failed) == len(libs):
            break
        libs = failed


def _detect_device() -> tuple[str, str]:
    """Pick the best (device, compute_type). Override via TRANSCRIPE_DEVICE."""
    device = os.environ.get("TRANSCRIPE_DEVICE")
    if device:
        compute = os.environ.get("TRANSCRIPE_COMPUTE", "float16" if device == "cuda" else "int8")
        return device, compute
    if shutil.which("nvidia-smi"):
        return "cuda", os.environ.get("TRANSCRIPE_COMPUTE", "float16")
    return "cpu", os.environ.get("TRANSCRIPE_COMPUTE", "int8")


def get_model(console: Console):
    """Load (once) and cache the Whisper model, auto-selecting GPU when available."""
    global _MODEL, _MODEL_KEY
    from faster_whisper import WhisperModel

    device, compute = _detect_device()
    if device == "cuda":
        _load_pip_cuda()
    key = (MODEL_SIZE, device, compute)
    if _MODEL is not None and _MODEL_KEY == key:
        return _MODEL, device, compute

    try:
        _MODEL = WhisperModel(MODEL_SIZE, device=device, compute_type=compute, download_root=str(CACHE_DIR))
        if device != "cpu":
            # Loading proves nothing: CTranslate2 opens cuBLAS lazily, so a
            # machine with the NVIDIA driver but not the CUDA libraries loads
            # fine and then dies on the first encode with "libcublas.so.12 is
            # not found". One silent window of encoding settles it up front.
            import numpy as np
            from ctranslate2 import StorageView

            fe = _MODEL.feature_extractor
            _MODEL.model.encode(StorageView.from_array(
                np.zeros((1, fe.mel_filters.shape[0], fe.nb_max_frames), dtype=np.float32)))
    except Exception as e:
        if device != "cpu":
            console.print(f"[yellow]GPU init failed ({e}); falling back to CPU.[/yellow]")
            device, compute = "cpu", "int8"
            _MODEL = WhisperModel(MODEL_SIZE, device=device, compute_type=compute, download_root=str(CACHE_DIR))
        else:
            raise
    _MODEL_KEY = (MODEL_SIZE, device, compute)
    return _MODEL, device, compute


def pcm_codec_for(input_path: Path) -> str:
    """The PCM flavour that keeps this source's depth.

    WAV has no compression to hide behind: writing pcm_s16le is a decision to
    throw away everything above 16 bits. A 24-bit master converted to WAV came
    out 16-bit, silently, which is the one thing a lossless target must not do.
    """
    import subprocess

    probe = shutil.which("ffprobe")
    if not probe:
        return "pcm_s16le"
    try:
        res = subprocess.run(
            [probe, "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=sample_fmt,bits_per_raw_sample", "-of", "csv=p=0", str(input_path)],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return "pcm_s16le"

    parts = [p.strip() for p in res.stdout.strip().split(",") if p.strip()]
    sample_fmt = parts[0] if parts else ""
    bits = 0
    for p in parts[1:]:
        if p.isdigit():
            bits = int(p)

    if bits >= 32 or sample_fmt.startswith(("flt", "dbl")):
        return "pcm_f32le"
    if bits >= 24:
        return "pcm_s24le"
    if sample_fmt.startswith("s32"):
        return "pcm_s32le"
    if sample_fmt.startswith("u8"):
        return "pcm_u8"
    return "pcm_s16le"


# One quality policy for the CLI and the studio, set for the best each lossy
# encoder offers rather than a size compromise: people convert here to keep a
# file, and a re-encode is a generation of loss they can't undo.
# mp3 -q:a 0 is LAME's top VBR (~245 kbps, was 2 / ~190); AAC at 256 kbps is
# where ffmpeg's native encoder stops being audibly different (was 192); Vorbis
# q8 (~256 kbps, was q6); Opus 192 kbps (was 128).
AUDIO_ENCODERS = {
    "mp3": ["-codec:a", "libmp3lame", "-q:a", "0"],
    "flac": ["-codec:a", "flac"],
    "ogg": ["-codec:a", "libvorbis", "-q:a", "8"],
    "opus": ["-codec:a", "libopus", "-b:a", "192k"],
    "aac": ["-codec:a", "aac", "-b:a", "256k"],
    # Left to ffmpeg these two came out at its 128 kbps default.
    "m4a": ["-codec:a", "aac", "-b:a", "256k"],
    "wma": ["-codec:a", "wmav2", "-b:a", "192k"],
}
# The audio track inside a video target.
VIDEO_AUDIO = ["-codec:a", "aac", "-b:a", "256k"]
# CRF 18 is x264's "visually lossless" point (was 23, which shows banding and
# smeared texture on gradients). It costs size, not encode time: the preset is
# what sets the speed, so the server's job ceiling is unchanged.
X264_CRF = "18"
# VP9's constant-quality equivalent (was 32 in the studio, 30 in the CLI).
VP9_CRF = "24"


def audio_encoder_args(target_format: str, input_path: Path) -> list:
    """ffmpeg arguments for an audio target, depth-preserving for WAV."""
    if target_format == "wav":
        return ["-codec:a", pcm_codec_for(input_path)]
    return list(AUDIO_ENCODERS.get(target_format, []))


def fmt_time(s: float) -> str:
    ms = int((s % 1) * 1000)
    return f"{int(s)//3600:02d}:{(int(s)//60)%60:02d}:{int(s)%60:02d},{ms:03d}"

def transcribe(video: Path, target_format: str, console: Console, output_path: Path | None = None,
               translate: bool = False, on_progress=None):
    """Transcribe (or translate to English, translate=True) audio/video to txt/srt.

    on_progress, if given, receives the fraction of the audio done after each
    segment — a big model on a small CPU runs for many minutes, and "still
    transcribing" for twenty of them tells the user nothing.
    """
    # Anything else would run the whole model and then write an empty file,
    # since only these two have a writer below.
    if target_format not in ("txt", "srt"):
        raise ValueError(
            f"Transcription writes .txt or .srt, not .{target_format} "
            "(convert the .srt afterwards for other subtitle formats)")
    txt_path = output_path or video.with_suffix(f".{target_format}")
    txt_path.parent.mkdir(parents=True, exist_ok=True)

    task_label = "Translating (→ English)" if translate else "Transcribing"
    with console.status(f"[bold cyan]Loading Whisper model ({MODEL_SIZE})…[/bold cyan]") as status:
        model, device, compute = get_model(console)
        console.print(f"[green]Model ready[/green] [dim]({MODEL_SIZE} · {device} · {compute})[/dim]")
        if on_progress:
            on_progress(0.0)

        status.update(f"[bold yellow]{task_label} {video.name}...[/bold yellow]")

        t0 = time.time()
        segments, info = model.transcribe(
            str(video),
            beam_size=BEAM_SIZE,
            task="translate" if translate else "transcribe",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        
        console.print(f"Detected Language: [bold]{info.language}[/bold] ({info.language_probability:.0%})")
        console.print(f"Duration: [bold]{info.duration:.1f}s[/bold]")
        
        with open(txt_path, "w", encoding="utf-8") as out_f:
            for i, seg in enumerate(segments, start=1):
                text = seg.text.strip()
                
                # Write to file based on target format
                if target_format == "txt":
                    out_f.write(text + "\n")
                elif target_format == "srt":
                    out_f.write(f"{i}\n{fmt_time(seg.start)} --> {fmt_time(seg.end)}\n{text}\n\n")
                    
                out_f.flush()
                if on_progress and info.duration:
                    on_progress(min(0.999, seg.end / info.duration))
                # Print real-time progress to console (trimming text so it doesn't clutter)
                display_text = text if len(text) < 50 else text[:47] + "..."
                console.print(f"  [dim]{fmt_time(seg.start)}[/dim] {display_text}")

        elapsed = time.time() - t0
        speed = info.duration / elapsed if elapsed else 0
        console.print(f"\n[bold green]✓ Done in {elapsed/60:.1f} min ({speed:.1f}x real-time)[/bold green]")
        console.print(f"Saved to: [bold underline]{txt_path.name}[/bold underline]")


def convert_media(input_path: Path, target_format: str, console: Console, output_path: Path | None = None):
    """Convert between media formats using FFmpeg (e.g. mp4→mp3, wav→flac, mkv→mp4)."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg not found! Please install FFmpeg and try again.")

    out_path = output_path or input_path.with_suffix(f".{target_format}")

    # Build ffmpeg command with smart defaults
    cmd = [ffmpeg, "-i", str(input_path), "-y"]  # -y = overwrite

    # Audio extraction from video (e.g., mp4 → mp3/wav/flac/aac/ogg)
    audio_targets = {"mp3", "wav", "flac", "aac", "ogg", "m4a", "opus", "wma"}
    video_targets = {"mp4", "mkv", "avi", "mov", "webm", "flv", "wmv"}

    if target_format in audio_targets:
        cmd += ["-vn"]  # strip video track
        cmd += audio_encoder_args(target_format, input_path)

    elif target_format in video_targets:
        if target_format == "mp4":
            # -pix_fmt yuv420p: force 4:2:0 chroma so browsers/QuickTime/phones
            # can play it (yuv444/422 sources otherwise produce a valid but
            # unplayable file). +faststart: moov atom up front for web streaming.
            cmd += ["-codec:v", "libx264", "-preset", "medium", "-crf", X264_CRF,
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", *VIDEO_AUDIO]
        elif target_format == "webm":
            cmd += ["-codec:v", "libvpx-vp9", "-crf", VP9_CRF, "-b:v", "0",
                    "-pix_fmt", "yuv420p", "-codec:a", "libopus", "-b:a", "192k"]
        elif target_format in ("mov", "mkv", "avi"):
            # Default to widely-playable H.264 4:2:0 rather than ffmpeg's guess.
            cmd += ["-codec:v", "libx264", "-preset", "medium", "-crf", X264_CRF,
                    "-pix_fmt", "yuv420p", *VIDEO_AUDIO]
        # else: let ffmpeg auto-select codecs

    cmd.append(str(out_path))

    with console.status(f"[bold cyan]Converting {input_path.name} → {out_path.name} using FFmpeg…[/bold cyan]"):
        result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        error_msg = result.stderr.strip().split('\n')[-1] if result.stderr else "unknown error"
        raise RuntimeError(f"FFmpeg failed: {error_msg}")

    size_mb = out_path.stat().st_size / 1_048_576
    console.print(f"[bold green]✓ Converted! Saved to {out_path.name} ({size_mb:.1f} MB)[/bold green]")


def _get_ffmpeg():
    import shutil
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg not found! Please install FFmpeg.")
    return ffmpeg


def video_to_gif(input_path: Path, fps: int, width: int, console: Console, output_path: Path | None = None):
    """Convert a video to an optimized GIF using a two-pass palette method."""
    import os as _os
    import subprocess, tempfile

    ffmpeg = _get_ffmpeg()
    out_path = output_path or input_path.with_suffix(".gif")
    fd, palette_name = tempfile.mkstemp(suffix=".png")
    _os.close(fd)
    palette = Path(palette_name)

    filters = f"fps={fps},scale={width}:-1:flags=lanczos"

    with console.status(f"[bold cyan]Creating GIF from {input_path.name} ({fps}fps, {width}px wide)…[/bold cyan]"):
        # Pass 1: generate optimal palette
        subprocess.run(
            [ffmpeg, "-i", str(input_path), "-vf", f"{filters},palettegen", "-y", str(palette)],
            capture_output=True,
        )
        # Pass 2: use palette to create high-quality GIF
        result = subprocess.run(
            [ffmpeg, "-i", str(input_path), "-i", str(palette),
             "-lavfi", f"{filters} [x]; [x][1:v] paletteuse",
             "-y", str(out_path)],
            capture_output=True, text=True,
        )
        palette.unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr.strip().split(chr(10))[-1]}")

    size_mb = out_path.stat().st_size / 1_048_576
    console.print(f"[bold green]✓ GIF created! {out_path.name} ({size_mb:.1f} MB)[/bold green]")


def compress_video(input_path: Path, quality: str, console: Console, output_path: Path | None = None):
    """Compress a video using FFmpeg CRF tuning. quality: 'high', 'medium', 'low'."""
    import subprocess

    ffmpeg = _get_ffmpeg()
    stem = input_path.stem
    out_path = output_path or (input_path.parent / f"{stem}_compressed{input_path.suffix}")

    crf_map = {"high": "20", "medium": "28", "low": "35"}
    crf = crf_map.get(quality, "28")

    original_mb = input_path.stat().st_size / 1_048_576

    with console.status(f"[bold cyan]Compressing {input_path.name} (quality: {quality}, CRF {crf})…[/bold cyan]"):
        result = subprocess.run(
            [ffmpeg, "-i", str(input_path),
             "-codec:v", "libx264", "-preset", "slow", "-crf", crf,
             "-pix_fmt", "yuv420p",
             "-codec:a", "aac", "-b:a", "128k",
             "-movflags", "+faststart",
             "-y", str(out_path)],
            capture_output=True, text=True,
        )

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr.strip().split(chr(10))[-1]}")

    new_mb = out_path.stat().st_size / 1_048_576
    reduction = (1 - new_mb / original_mb) * 100 if original_mb > 0 else 0
    console.print(f"[bold green]✓ Compressed! {original_mb:.1f} MB → {new_mb:.1f} MB ({reduction:.0f}% smaller)[/bold green]")
    console.print(f"Saved to: [bold underline]{out_path.name}[/bold underline]")


def trim_video(input_path: Path, start: str, end: str, console: Console, output_path: Path | None = None):
    """Trim a video from start to end time. Times in HH:MM:SS or SS format."""
    import subprocess

    ffmpeg = _get_ffmpeg()
    stem = input_path.stem
    out_path = output_path or (input_path.parent / f"{stem}_trimmed{input_path.suffix}")

    cmd = [ffmpeg, "-i", str(input_path), "-ss", start]
    if end:
        cmd += ["-to", end]
    cmd += ["-codec", "copy", "-y", str(out_path)]

    with console.status(f"[bold cyan]Trimming {input_path.name} ({start} → {end or 'end'})…[/bold cyan]"):
        result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr.strip().split(chr(10))[-1]}")

    size_mb = out_path.stat().st_size / 1_048_576
    console.print(f"[bold green]✓ Trimmed! Saved to {out_path.name} ({size_mb:.1f} MB)[/bold green]")


def extract_frames(input_path: Path, fps: int, console: Console, output_path: Path | None = None):
    """Extract frames from a video as PNG images."""
    import subprocess

    ffmpeg = _get_ffmpeg()
    out_dir = output_path or (input_path.parent / f"{input_path.stem}_frames")
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%04d.png")

    with console.status(f"[bold cyan]Extracting frames at {fps} fps…[/bold cyan]"):
        result = subprocess.run(
            [ffmpeg, "-i", str(input_path), "-vf", f"fps={fps}", "-y", pattern],
            capture_output=True, text=True,
        )

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr.strip().split(chr(10))[-1]}")

    count = len(list(out_dir.glob("*.png")))
    console.print(f"[bold green]✓ Extracted {count} frames to {out_dir.name}/[/bold green]")
