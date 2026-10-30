"""Talk: record the microphone, transcribe it, hand the text over.

Two ways in. `transcripe talk` records in the terminal until Enter. And
`transcripe talk --toggle`, bound to a desktop shortcut, makes it work from
any app: the first press starts listening, the second stops, transcribes, and
puts the text on the clipboard with a notification, ready to paste.

Speech is transcribed in mixed mode by default — the owner speaks Arabic,
Turkish and English, often in the same breath — see audio_video._by_utterance.
"""
from __future__ import annotations

import io
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from rich.console import Console

# A forgotten recording must not run until the disk fills: 16 kHz mono is
# ~115 MB an hour, and past a quarter of an hour the wait for the transcript
# stops feeling like dictation anyway.
MAX_SECONDS = 15 * 60

STATE = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "transcripe-talk"
HOTKEY_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/transcripe-talk/"
MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
SERVER = os.environ.get("TRANSCRIPE_SERVER", "https://alabed.site")
LOCAL_WORKER = "http://127.0.0.1:8111"


def recorder(wav: Path) -> list[str]:
    """A command that records 16 kHz mono WAV to `wav` until SIGINT.

    16 kHz mono is all Whisper hears, so capturing more only costs disk.
    """
    limit = ["timeout", "--signal=INT", str(MAX_SECONDS)]
    if shutil.which("pw-record"):  # PipeWire: every current desktop
        return limit + ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", str(wav)]
    if shutil.which("arecord"):
        return limit + ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", str(wav)]
    if shutil.which("ffmpeg"):
        return limit + ["ffmpeg", "-v", "error", "-y", "-f", "pulse", "-i", "default",
                        "-ac", "1", "-ar", "16000", str(wav)]
    raise RuntimeError("No way to record: install PipeWire (pw-record), alsa-utils or ffmpeg")


def wait_for_audio(wav: Path, seconds: float = 6) -> bool:
    """True once samples are really arriving.

    A sound card asleep takes up to two seconds to wake (3 s of recording once
    held 1.15 s of audio). Saying "listening" before that loses the first words.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        if wav.exists() and wav.stat().st_size > 2048:
            return True
        time.sleep(0.05)
    return False


def stop(proc_or_pid) -> None:
    """Stop a recorder the way it expects, so the WAV header is finished."""
    pid = proc_or_pid if isinstance(proc_or_pid, int) else proc_or_pid.pid
    try:
        os.killpg(pid, signal.SIGINT)
    except ProcessLookupError:
        return
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        if not isinstance(proc_or_pid, int) and proc_or_pid.poll() is not None:
            return
        time.sleep(0.1)


def transcribe_wav(wav: Path, mixed: bool = True, console: Console | None = None,
                   local_only: bool = False) -> str:
    """The best transcriber within reach.

    This machine's GPU if it has a working one: nothing leaves the machine and
    nothing is faster. Otherwise the server, which itself picks the best of the
    machines that are on. Otherwise this machine's CPU, slowly, because a slow
    transcript beats none when the network is down too.
    """
    from transcripe.engines import remote

    console = console or Console(file=io.StringIO())
    out = wav.with_suffix(".txt")

    def here() -> str:
        from transcripe.engines.audio_video import transcribe

        transcribe(wav, "txt", console, output_path=out, mixed=mixed)
        return out.read_text(encoding="utf-8").strip()

    # This machine's own worker has the model on the GPU already, and a second
    # copy beside it would run a 6 GB card out of memory.
    worker = _local_worker()
    if worker and worker.model():
        try:
            worker.transcribe(str(wav), str(out), mixed=mixed)
            return out.read_text(encoding="utf-8").strip()
        except remote.RemoteGone:
            pass
    if local_only or _has_working_gpu(console):
        return here()
    server = remote.Studio(SERVER, os.environ.get("TRANSCRIPE_TOKEN", ""))
    if server.model():
        try:
            server.transcribe(str(wav), str(out), mixed=mixed)
            return out.read_text(encoding="utf-8").strip()
        except remote.RemoteGone:
            pass
    return here()


def _local_worker():
    from transcripe.engines import remote

    try:
        env = (Path.home() / ".config/transcripe/worker.env").read_text()
    except OSError:
        return None
    for line in env.splitlines():
        if line.startswith("TRANSCRIPE_TOKEN="):
            return remote.Studio(LOCAL_WORKER, line.split("=", 1)[1].strip())
    return None


def _has_working_gpu(console: Console) -> bool:
    """Loads the model, which is the only honest test, and is kept for the
    transcription that follows."""
    if not shutil.which("nvidia-smi"):
        return False
    try:
        from transcripe.engines.audio_video import get_model

        return get_model(console)[1] != "cpu"
    except Exception:
        return False


def copy(text: str) -> str:
    """Put text on the clipboard; returns the tool used, or "" if none."""
    for tool in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if shutil.which(tool[0]):
            # wl-copy forks to keep serving the clipboard after we exit.
            subprocess.run(tool, input=text.encode("utf-8"), check=False, timeout=10)
            return tool[0]
    return ""


def notify(title: str, body: str = "") -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Transcripe", "-h", "string:x-canonical-private-synchronous:talk",
                        title, body[:400]], check=False, timeout=10)


def toggle(mixed: bool = True, local_only: bool = False) -> str | None:
    """One press of the shortcut. Starts listening, or stops and delivers.

    Returns the transcript when this press finished one, None when it started.
    """
    STATE.mkdir(parents=True, exist_ok=True)
    pid_file, wav = STATE / "recording.pid", STATE / "talk.wav"
    pid = int(pid_file.read_text()) if pid_file.exists() else 0

    alive = False
    if pid:
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            pass

    if not alive:
        wav.unlink(missing_ok=True)
        # Its own session, so it outlives this process and the shortcut's.
        proc = subprocess.Popen(recorder(wav), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        pid_file.write_text(str(proc.pid))
        if not wait_for_audio(wav):
            stop(proc.pid)
            pid_file.unlink(missing_ok=True)
            notify("The microphone isn't giving any audio", "Check Settings → Sound → Input.")
            return ""
        notify("Listening…", "Press the shortcut again to stop.")
        return None

    stop(pid)
    pid_file.unlink(missing_ok=True)
    if not wav.exists() or wav.stat().st_size < 16000:  # under half a second
        notify("Nothing recorded", "Check the microphone in Settings → Sound.")
        return ""
    notify("Transcribing…")
    text = transcribe_wav(wav, mixed=mixed, local_only=local_only)
    if not text:
        notify("No speech heard")
        return ""
    tool = copy(text)
    notify("Copied — paste with Ctrl+V" if tool else "Transcribed (install wl-clipboard to copy)", text)
    (STATE / "last.txt").write_text(text, encoding="utf-8")
    return text


def _gsettings(*args: str) -> str:
    return subprocess.run(["gsettings", *args], capture_output=True, text=True, check=True).stdout.strip()


def install_hotkey(binding: str, command: str) -> None:
    """Bind `command` to `binding` as a GNOME custom shortcut (idempotent)."""
    import ast

    if not shutil.which("gsettings"):
        raise RuntimeError("Not a GNOME desktop: bind `transcripe talk --toggle` to a key yourself")
    raw = _gsettings("get", MEDIA_KEYS, "custom-keybindings")
    paths = ast.literal_eval(raw.removeprefix("@as ")) or []
    if HOTKEY_PATH not in paths:
        _gsettings("set", MEDIA_KEYS, "custom-keybindings", str(paths + [HOTKEY_PATH]))
    schema = f"{MEDIA_KEYS}.custom-keybinding:{HOTKEY_PATH}"
    _gsettings("set", schema, "name", "Transcripe: talk")
    _gsettings("set", schema, "command", command)
    _gsettings("set", schema, "binding", binding)
