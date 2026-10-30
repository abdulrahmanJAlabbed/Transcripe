"""`transcripe talk`: the shortcut's two presses, and who does the transcribing."""
import sys

import pytest

from transcripe.engines import remote, talk


@pytest.fixture(autouse=True)
def no_real_worker(monkeypatch):
    """A worker may really be running on this machine; tests don't talk to it."""
    monkeypatch.setattr(talk, "_local_worker", lambda: None)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(talk, "STATE", tmp_path)
    monkeypatch.setattr(talk, "notify", lambda *a, **k: None)
    # A "recorder" that writes a second of audio's worth of bytes and waits.
    script = ("import sys,time,signal; open(sys.argv[1],'wb').write(b'0'*32000); "
              "signal.signal(signal.SIGINT, lambda *a: sys.exit(0)); time.sleep(60)")
    monkeypatch.setattr(talk, "recorder", lambda wav: [sys.executable, "-c", script, str(wav)])
    return tmp_path


def test_first_press_listens_second_press_delivers(state, monkeypatch):
    import time

    copied = []
    monkeypatch.setattr(talk, "copy", lambda text: copied.append(text) or "wl-copy")
    monkeypatch.setattr(talk, "transcribe_wav", lambda wav, mixed, local_only: "merhaba مرحبا hello")

    assert talk.toggle() is None
    assert (state / "recording.pid").exists()
    time.sleep(0.5)  # let the recorder write
    assert talk.toggle() == "merhaba مرحبا hello"
    assert copied == ["merhaba مرحبا hello"]
    assert not (state / "recording.pid").exists()


def test_a_recorder_that_died_means_a_fresh_start(state):
    (state / "recording.pid").write_text("999999")
    assert talk.toggle() is None  # starts over rather than transcribing nothing
    talk.stop(int((state / "recording.pid").read_text()))


def test_no_gpu_goes_to_the_server(tmp_path, monkeypatch):
    wav = tmp_path / "talk.wav"
    wav.write_bytes(b"0")
    monkeypatch.setattr(talk, "_has_working_gpu", lambda console: False)
    monkeypatch.setattr(remote.Studio, "model", lambda self: "large-v3-turbo")

    def server(self, path, out, mixed):
        open(out, "w", encoding="utf-8").write("from the server\n")
        return True

    monkeypatch.setattr(remote.Studio, "transcribe", server)
    assert talk.transcribe_wav(wav) == "from the server"


def test_the_local_worker_comes_first(tmp_path, monkeypatch):
    """It has the model on the GPU already; a second copy wouldn't fit."""
    wav = tmp_path / "talk.wav"
    wav.write_bytes(b"0")

    class Worker:
        def model(self):
            return "large-v3"

        def transcribe(self, path, out, mixed):
            open(out, "w", encoding="utf-8").write("from the worker")
            return True

    monkeypatch.setattr(talk, "_local_worker", Worker)
    monkeypatch.setattr(talk, "_has_working_gpu", lambda console: pytest.fail("loaded a second copy"))
    assert talk.transcribe_wav(wav) == "from the worker"


def test_local_only_never_contacts_the_server(tmp_path, monkeypatch):
    import transcripe.engines.audio_video as av

    wav = tmp_path / "talk.wav"
    wav.write_bytes(b"0")

    def nope(self):
        raise AssertionError("the recording must not leave this machine")

    def here(src, fmt, console, output_path=None, mixed=False):
        output_path.write_text("stayed here", encoding="utf-8")

    monkeypatch.setattr(remote.Studio, "model", nope)
    monkeypatch.setattr(av, "transcribe", here)
    assert talk.transcribe_wav(wav, local_only=True) == "stayed here"
