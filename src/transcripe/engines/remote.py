"""Have another Transcripe studio do a transcription.

The server sends work to stronger machines this way (the PC's GPU, the Pi), and
`transcripe talk` on a machine with no GPU sends it to the server. Standard
library only, so the CLI can use it without the studio extras.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import time
import urllib.error
import urllib.request

POLL_SECONDS = 2.0


class RemoteGone(Exception):
    """This studio can't finish the job; somebody else has to."""


class Studio:
    def __init__(self, url: str, token: str = ""):
        self.url, self.token = url.rstrip("/"), token

    def _open(self, path: str, data=None, headers=None, timeout: float = 10):
        return urllib.request.urlopen(urllib.request.Request(
            f"{self.url}{path}", data=data,
            # Cloudflare answers urllib's default User-Agent with a 403.
            headers={"User-Agent": "transcripe", "X-Transcripe-Token": self.token, **(headers or {})},
        ), timeout=timeout)

    def model(self) -> str:
        """This studio's Whisper model when it is up and will take work, else ""."""
        try:
            with self._open("/api/health", timeout=3) as res:
                health = json.load(res)
        except (OSError, ValueError):
            return ""
        if health.get("authorized") and health.get("features", {}).get("transcribe"):
            return health.get("model") or ""
        return ""

    def _upload(self, path: str, fmt: str, translate: bool, mixed: bool) -> str:
        boundary = secrets.token_hex(16)
        fields = "".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            for name, value in (("targetFormat", fmt), ("translate", str(translate).lower()),
                                ("mixed", str(mixed).lower())))
        # An ASCII name of our own: the client's (often Arabic) filename has no
        # business in a header, and the transcript is named on this side anyway.
        head = (fields + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="audio{os.path.splitext(path)[1]}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n").encode()
        tail = f"\r\n--{boundary}--\r\n".encode()

        def body():
            yield head
            with open(path, "rb") as f:
                while chunk := f.read(1024 * 256):
                    yield chunk
            yield tail

        with self._open("/api/transcribe", data=body(), timeout=120, headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(head) + os.path.getsize(path) + len(tail))}) as res:
            return json.load(res)["job"]

    def transcribe(self, path: str, out_path: str, fmt: str = "txt", translate: bool = False,
                   mixed: bool = True, patience: float = 120, cancelled=lambda: False,
                   on_state=lambda state: None) -> bool:
        """Run one transcription here and fetch the result to out_path.

        False if `cancelled` said to stop; raises RemoteGone if this studio
        can't finish. An outage shorter than `patience` is waited out: a tunnel
        reconnecting doesn't stop the job on the far side, and starting over
        elsewhere would throw that work away.
        """
        try:
            job = self._upload(path, fmt, translate, mixed)
        except (OSError, ValueError, KeyError) as e:
            raise RemoteGone(f"upload failed: {e}")

        answered = time.time()
        while True:
            time.sleep(POLL_SECONDS)
            if cancelled():
                try:
                    self._open(f"/api/jobs/{job}/cancel", data=b"", timeout=5).close()
                except OSError:
                    pass  # it'll expire there on its own
                return False
            try:
                with self._open(f"/api/jobs/{job}") as res:
                    state = json.load(res)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise RemoteGone("it restarted and lost the job")
                state = None
            except (OSError, ValueError):
                state = None
            if state is None:
                if time.time() - answered > patience:
                    raise RemoteGone("it stopped answering")
                continue
            answered = time.time()
            if state.get("status") in ("error", "cancelled"):
                raise RemoteGone(state.get("detail") or state.get("status"))
            if state.get("status") == "done":
                break
            on_state(state)

        try:
            with self._open(state["download"], timeout=60) as res, open(out_path, "wb") as f:
                shutil.copyfileobj(res, f)
        except (OSError, KeyError) as e:
            raise RemoteGone(f"could not fetch the transcript: {e}")
        return True
