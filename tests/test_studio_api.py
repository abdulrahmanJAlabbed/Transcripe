"""Studio API: access control, upload limits, conversion, result handoff.

Everything here talks to the FastAPI app in-process. Conversions that need a
real encoder are skipped when the encoder isn't installed, matching the rest
of the suite.
"""
import importlib
import shutil

import pytest

fastapi_testclient = pytest.importorskip(
    "fastapi.testclient", reason="studio extras not installed")
TestClient = fastapi_testclient.TestClient

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def load_studio(monkeypatch, **env):
    """Import the studio with a fresh environment (module-level config)."""
    for key in ("TRANSCRIPE_TOKEN", "TRANSCRIPE_MAX_UPLOAD_MB"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import transcripe.studio as studio
    return importlib.reload(studio)


@pytest.fixture
def open_studio(monkeypatch):
    """No token configured — the loopback default."""
    return load_studio(monkeypatch)


@pytest.fixture
def locked_studio(monkeypatch):
    return load_studio(monkeypatch, TRANSCRIPE_TOKEN="s3cret")


def wav_bytes(fixtures):
    return fixtures["wav"].read_bytes() if "wav" in fixtures else b"RIFFfake"


# ── access control ──────────────────────────────────────────────────────────

def test_open_studio_needs_no_token(open_studio):
    with TestClient(open_studio.app) as client:
        health = client.get("/api/health").json()
    assert health["auth_required"] is False
    assert health["authorized"] is True


def test_locked_studio_reports_itself_but_stays_reachable(locked_studio):
    """Health stays open so a client can tell 'locked' from 'not running'."""
    with TestClient(locked_studio.app) as client:
        health = client.get("/api/health").json()
    assert health["auth_required"] is True
    assert health["authorized"] is False


def test_locked_studio_rejects_work_without_token(locked_studio):
    with TestClient(locked_studio.app) as client:
        res = client.post("/api/convert/url", json={"url": "https://example.com/x"})
    assert res.status_code == 401


def test_locked_studio_rejects_a_wrong_token(locked_studio):
    with TestClient(locked_studio.app) as client:
        res = client.post(
            "/api/convert/url",
            json={"url": "https://example.com/x"},
            headers={"X-Transcripe-Token": "not-it"},
        )
    assert res.status_code == 401


def test_token_accepted_from_header_or_query(locked_studio):
    with TestClient(locked_studio.app) as client:
        assert client.get(
            "/api/health", headers={"X-Transcripe-Token": "s3cret"}
        ).json()["authorized"] is True
        assert client.get("/api/health?token=s3cret").json()["authorized"] is True


# ── upload limits ───────────────────────────────────────────────────────────

def test_upload_over_the_cap_is_refused(monkeypatch):
    studio = load_studio(monkeypatch, TRANSCRIPE_MAX_UPLOAD_MB="0.001")  # 1 KB
    with TestClient(studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("big.wav", b"x" * 50_000, "audio/wav")},
            data={"targetFormat": "mp3"},
        )
    assert res.status_code == 413
    assert "larger than" in res.json()["detail"]


# ── conversion ──────────────────────────────────────────────────────────────

@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_audio_conversion_returns_a_real_file(open_studio, fixtures):
    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("clip.wav", wav_bytes(fixtures), "audio/wav")},
            data={"targetFormat": "mp3"},
        )
    assert res.status_code == 200
    assert res.content[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3")


def test_image_conversion_does_not_go_through_ffmpeg(open_studio, tmp_path):
    """Images route through Pillow — ffmpeg can't read HEIC/AVIF at all."""
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    src = tmp_path / "shot.png"
    PIL.new("RGB", (32, 24), (200, 80, 42)).save(src)

    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("shot.png", src.read_bytes(), "image/png")},
            data={"targetFormat": "webp"},
        )
    assert res.status_code == 200
    assert res.content[:4] == b"RIFF"


def test_heic_input_is_readable(open_studio, tmp_path):
    """Regression: pillow-heif ≥ 1.0 dropped register_avif_opener, and importing
    it alongside the HEIF one used to silently disable HEIC entirely."""
    pytest.importorskip("pillow_heif", reason="pillow-heif not installed")
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    import pillow_heif

    pillow_heif.register_heif_opener()
    src = tmp_path / "photo.heic"
    PIL.new("RGB", (40, 30), (10, 120, 90)).save(src, format="HEIF")

    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("photo.heic", src.read_bytes(), "image/heic")},
            data={"targetFormat": "jpg"},
        )
    assert res.status_code == 200, res.text
    assert res.content[:3] == b"\xff\xd8\xff"


def test_impossible_pairing_fails_honestly(open_studio, tmp_path):
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    src = tmp_path / "shot.png"
    PIL.new("RGB", (8, 8)).save(src)

    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("shot.png", src.read_bytes(), "image/png")},
            data={"targetFormat": "mp3"},
        )
    assert res.status_code == 422
    assert "image" in res.json()["detail"].lower()


# ── result handoff ──────────────────────────────────────────────────────────

@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_link_delivery_hands_back_a_single_use_url(open_studio, fixtures):
    with TestClient(open_studio.app) as client:
        started = client.post(
            "/api/convert/file",
            files={"file": ("clip.wav", wav_bytes(fixtures), "audio/wav")},
            data={"targetFormat": "mp3", "deliver": "link"},
        )
        assert started.status_code == 200
        job = started.json()
        assert job["download"].startswith("/api/result/")

        first = client.get(job["download"])
        assert first.status_code == 200
        assert len(first.content) > 0

        # The token is spent: a replay must not resurrect the file.
        assert client.get(job["download"]).status_code == 404


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_a_partial_download_can_be_resumed(open_studio, fixtures):
    """Phones lose signal. Without ranges the whole transfer restarts, which on
    a large video is the difference between a hiccup and giving up."""
    with TestClient(open_studio.app) as client:
        started = client.post(
            "/api/convert/file",
            files={"file": ("clip.wav", wav_bytes(fixtures), "audio/wav")},
            data={"targetFormat": "mp3", "deliver": "link"},
        )
        url = started.json()["download"]

        head = client.get(url, headers={"Range": "bytes=0-99"})
        assert head.status_code == 206
        assert head.headers["accept-ranges"] == "bytes"
        assert head.headers["content-range"].startswith("bytes 0-99/")
        total = int(head.headers["content-range"].split("/")[1])

        # The token must survive a partial read, or resuming is impossible.
        rest = client.get(url, headers={"Range": f"bytes=100-"})
        assert rest.status_code == 206
        assert head.content + rest.content == b"".join([head.content, rest.content])
        assert len(head.content) + len(rest.content) == total

        # ...and be spent once the last byte has gone.
        assert client.get(url).status_code == 404


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_a_range_past_the_end_is_refused(open_studio, fixtures):
    with TestClient(open_studio.app) as client:
        started = client.post(
            "/api/convert/file",
            files={"file": ("clip.wav", wav_bytes(fixtures), "audio/wav")},
            data={"targetFormat": "wav", "deliver": "link"},
        )
        url = started.json()["download"]
        assert client.get(url, headers={"Range": "bytes=99999999-"}).status_code == 416


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_job_delivery_reports_progress_and_finishes(open_studio, fixtures):
    """An indeterminate bar tells you nothing about a conversion that might run
    for twenty minutes; ffmpeg will say how far along it is if asked."""
    import time as _time

    with TestClient(open_studio.app) as client:
        started = client.post(
            "/api/convert/file",
            files={"file": ("clip.wav", wav_bytes(fixtures), "audio/wav")},
            data={"targetFormat": "flac", "deliver": "job"},
        )
        assert started.status_code == 200
        job = started.json()["job"]

        state = {}
        for _ in range(80):
            state = client.get(f"/api/jobs/{job}").json()
            if state["status"] in ("done", "error"):
                break
            _time.sleep(0.25)

        assert state["status"] == "done", state
        assert state["progress"] == 1.0
        assert client.get(state["download"]).status_code == 200


def test_unknown_result_token_is_not_found(open_studio):
    with TestClient(open_studio.app) as client:
        assert client.get("/api/result/made-up-token").status_code == 404


def test_unknown_job_is_not_found(open_studio):
    with TestClient(open_studio.app) as client:
        assert client.get("/api/jobs/made-up-job").status_code == 404


def test_cancelling_a_queued_job_stops_it_before_it_starts(open_studio):
    """A job cancelled while waiting its turn must never reach the model."""
    import time as _time

    job_id = "test-job"
    with open_studio._jobs_lock:
        open_studio._jobs[job_id] = {
            "status": "queued", "stage": "queued", "touched": _time.time()}

    with TestClient(open_studio.app) as client:
        assert client.post(f"/api/jobs/{job_id}/cancel").json()["status"] == "cancelled"
        assert client.get(f"/api/jobs/{job_id}").json()["cancelled"] is True


def test_cancelling_an_unknown_job_is_not_found(open_studio):
    with TestClient(open_studio.app) as client:
        assert client.post("/api/jobs/nope/cancel").status_code == 404


def test_cancel_needs_the_token_too(locked_studio):
    with TestClient(locked_studio.app) as client:
        assert client.post("/api/jobs/anything/cancel").status_code == 401


def test_empty_upload_is_named_plainly(open_studio):
    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("silence.wav", b"", "audio/wav")},
            data={"targetFormat": "mp3"},
        )
    assert res.status_code == 422
    assert "empty" in res.json()["detail"]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_failure_reports_the_reason_not_the_ffmpeg_banner(open_studio):
    """The old slice showed users 200 characters of build configuration."""
    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("fake.wav", b"this is not audio", "audio/wav")},
            data={"targetFormat": "mp3"},
        )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "ffmpeg version" not in detail
    assert "configuration:" not in detail
    assert "Invalid data" in detail or "Error" in detail


def test_ffmpeg_reason_picks_the_error_line(open_studio):
    stderr = (
        "ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023 the FFmpeg developers\n"
        "  built with gcc 13 (Ubuntu 13.2.0)\n"
        "  configuration: --prefix=/usr --extra-version=3ubuntu5 --toolchain=hardened\n"
        "  libavutil      58. 29.100 / 58. 29.100\n"
        "[in#0] Error opening input: Invalid data found when processing input\n"
    )
    assert open_studio.ffmpeg_reason(stderr) == (
        "[in#0] Error opening input: Invalid data found when processing input")


def test_absurdly_long_filenames_are_trimmed(open_studio):
    """255 bytes is the usual filesystem limit, and we append to the name."""
    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("x" * 300 + ".wav", b"", "audio/wav")},
            data={"targetFormat": "mp3"},
        )
    # It reaches the emptiness check, which means the write itself succeeded.
    assert res.status_code == 422
    assert "empty" in res.json()["detail"]


def test_hardware_encoding_is_off_unless_asked_for(monkeypatch):
    """Measured head to head, NVENC was slower than x264 on a VP9 source and
    produced a 19% larger file for a 0.001 SSIM difference. Not a default."""
    studio = load_studio(monkeypatch)
    assert studio.HWACCEL == "off"
    assert studio.detect_hw_encoder() == ""


def test_hardware_encoding_probes_before_trusting_it(monkeypatch):
    """ffmpeg lists h264_vaapi on machines where it fails with an I/O error,
    so listed support is not working support — only a real encode proves it."""
    studio = load_studio(monkeypatch, TRANSCRIPE_HWACCEL="on")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 1
        return R()

    monkeypatch.setattr(studio.subprocess, "run", fake_run)
    studio._hw_encoder = None
    assert studio.detect_hw_encoder() == "", "a failing probe must not be trusted"
    assert calls, "it has to actually try an encode"


# ── depth and breadth ───────────────────────────────────────────────────────

@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_wav_keeps_the_source_bit_depth(open_studio, tmp_path):
    """A 24-bit master converted to WAV came back 16-bit. WAV has no
    compression to hide behind — writing pcm_s16le throws the depth away."""
    import subprocess

    from transcripe.engines.audio_video import pcm_codec_for

    src = tmp_path / "master.flac"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=1:sample_rate=96000",
         "-c:a", "flac", "-sample_fmt", "s32", str(src)], check=True, timeout=120)

    assert pcm_codec_for(src) in ("pcm_s24le", "pcm_s32le", "pcm_f32le")

    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("master.flac", src.read_bytes(), "audio/flac")},
            data={"targetFormat": "wav"},
        )
    assert res.status_code == 200
    out = tmp_path / "out.wav"
    out.write_bytes(res.content)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=sample_fmt",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True, timeout=60).stdout
    assert "s16" not in probe, f"depth was flattened: {probe.strip()}"


def test_subtitles_convert_without_the_cli(open_studio, tmp_path):
    """The subtitle engine was always here; the studio just had no route to
    it, so uploading an .srt got you a 'use the CLI' shrug."""
    src = tmp_path / "cues.srt"
    src.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n\n")

    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("cues.srt", src.read_bytes(), "text/plain")},
            data={"targetFormat": "vtt"},
        )
    assert res.status_code == 200, res.text
    assert res.content.startswith(b"WEBVTT")


def test_tabular_data_converts_without_the_cli(open_studio, tmp_path):
    pytest.importorskip("pandas", reason="data extra not installed")
    src = tmp_path / "rows.csv"
    src.write_text("name,score\nRahman,91\n")

    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("rows.csv", src.read_bytes(), "text/csv")},
            data={"targetFormat": "json"},
        )
    assert res.status_code == 200, res.text
    assert b"Rahman" in res.content


def test_modern_image_targets_are_offered(open_studio, tmp_path):
    """AVIF carries the same picture in less space than WebP; not offering it
    means handing people a bigger file than they need."""
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    pytest.importorskip("pillow_heif", reason="pillow-heif not installed")
    src = tmp_path / "shot.png"
    PIL.new("RGB", (64, 48), (124, 92, 255)).save(src)

    with TestClient(open_studio.app) as client:
        for target in ("avif", "gif", "ico"):
            res = client.post(
                "/api/convert/file",
                files={"file": ("shot.png", src.read_bytes(), "image/png")},
                data={"targetFormat": target},
            )
            assert res.status_code == 200, f"{target}: {res.text[:120]}"
            assert len(res.content) > 50


# ── download quality ────────────────────────────────────────────────────────

def test_best_quality_does_not_restrict_the_codec(open_studio):
    """Demanding avc1 means H.264, and YouTube caps H.264 at 1080p — measured
    on a 4K source it fetched 1920x1080 while 3840x2160 AV1 sat next to it."""
    args = " ".join(open_studio.ytdlp_quality_args("mp4", "best"))
    assert "vcodec^=avc1" not in args, "hard codec filter is what caps the resolution"
    assert "res" in args, "resolution has to lead the sort"


def test_compatible_mode_still_available_for_old_players(open_studio):
    args = " ".join(open_studio.ytdlp_quality_args("mp4", "compatible"))
    assert "avc1" in args


def test_a_js_runtime_is_offered_to_youtube_when_one_exists(open_studio):
    """YouTube hands out a JS challenge and yt-dlp only enables Deno itself;
    with no runtime it drops formats and often fails outright."""
    import shutil as _shutil

    args = open_studio.js_runtime_args()
    if any(_shutil.which(r) for r in open_studio.JS_RUNTIMES):
        assert args[0] == "--js-runtimes"
        assert ":" in args[1], "pass the resolved path, not just a name"
    else:
        assert args == []


def test_audio_downloads_ask_for_the_best_encode(open_studio):
    """yt-dlp defaults to --audio-quality 5, about 130 kbps for mp3."""
    args = open_studio.ytdlp_quality_args("mp3", "best")
    assert "--audio-quality" in args
    assert args[args.index("--audio-quality") + 1] == "0"


def test_dimensions_are_honoured_and_keep_the_aspect(open_studio):
    """The control people reach for first: make it smaller in pixels. Giving
    one side has to scale the other, or every caller does that arithmetic."""
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    import io

    with TestClient(open_studio.app) as client:
        started = client.post(
            "/api/convert/file",
            files={"file": ("scan.png", scan_png_bytes(900, 1200), "image/png")},
            data={"targetFormat": "jpg", "width": "300", "deliver": "link"},
        )
        assert started.status_code == 200, started.text
        got = client.get(started.json()["download"])

    assert PIL.open(io.BytesIO(got.content)).size == (300, 400)


def test_both_dimensions_given_are_taken_literally(open_studio):
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    import io

    with TestClient(open_studio.app) as client:
        started = client.post(
            "/api/convert/file",
            files={"file": ("scan.png", scan_png_bytes(900, 1200), "image/png")},
            data={"targetFormat": "jpg", "width": "320", "height": "200",
                  "deliver": "link"},
        )
        got = client.get(started.json()["download"])

    assert PIL.open(io.BytesIO(got.content)).size == (320, 200)


def test_resizing_and_a_budget_compose(open_studio):
    """Both at once is the real request — "1000 px and under 40 KB". Resizing
    has to happen first, or the budget is spent on pixels being thrown away."""
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    import io

    with TestClient(open_studio.app) as client:
        started = client.post(
            "/api/convert/file",
            files={"file": ("scan.png", scan_png_bytes(900, 1200), "image/png")},
            data={"targetFormat": "auto", "width": "500", "maxSize": "40KB",
                  "deliver": "link"},
        )
        assert started.status_code == 200, started.text
        got = client.get(started.json()["download"])

    assert len(got.content) <= 40 * 1024
    assert PIL.open(io.BytesIO(got.content)).width == 500


def test_resizing_alone_keeps_the_format_it_arrived_in(open_studio):
    """"auto" is the engine choosing a format to meet a budget. With only a
    resize there is no budget to choose against, so nothing should change."""
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    import io

    with TestClient(open_studio.app) as client:
        started = client.post(
            "/api/convert/file",
            files={"file": ("scan.png", scan_png_bytes(600, 400), "image/png")},
            data={"targetFormat": "auto", "width": "200", "deliver": "link"},
        )
        assert started.status_code == 200, started.text
        assert started.json()["filename"].endswith(".png")
        got = client.get(started.json()["download"])

    assert PIL.open(io.BytesIO(got.content)).format == "PNG"


@pytest.mark.parametrize("bad", ["0", "-40", "99999", "abc", "1.5.2"])
def test_a_dimension_that_is_not_a_dimension_is_refused(open_studio, bad):
    """Silently ignoring it would hand back a picture that is not the size the
    caller asked for, which is worse than saying no."""
    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("scan.png", scan_png_bytes(300, 300), "image/png")},
            data={"targetFormat": "jpg", "width": bad},
        )
    assert res.status_code == 422


def test_dimensions_on_something_that_is_not_an_image_are_refused(
        open_studio, fixtures):
    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("clip.wav", wav_bytes(fixtures), "audio/wav")},
            data={"targetFormat": "mp3", "width": "640"},
        )
    assert res.status_code == 422


# ── image fidelity ──────────────────────────────────────────────────────────

def test_exif_rotation_is_applied(tmp_path):
    """A phone photo tags its orientation instead of rotating the pixels.
    Ignoring the tag hands the user a sideways picture — and disagrees with
    every browser, which honours it."""
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    piexif = pytest.importorskip("piexif", reason="piexif not installed")
    from PIL import ImageDraw

    from transcripe.engines.images import _open_image

    src = tmp_path / "portrait.jpg"
    img = PIL.new("RGB", (600, 400), (240, 240, 240))
    ImageDraw.Draw(img).rectangle([0, 0, 600, 60], fill=(200, 40, 40))
    img.save(src, exif=piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6}}))

    opened = _open_image(src)
    assert opened.size == (400, 600), "orientation tag was ignored"


def test_jpeg_is_saved_at_quality_not_pillow_default(tmp_path):
    """Pillow defaults to quality 75, which is visibly soft. This tool is for
    people who care about the file they get back."""
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    from transcripe.engines.images import _save_options

    img = PIL.new("RGB", (64, 64), (10, 20, 30))
    opts = _save_options(img, "jpg", tmp_path / "x.png")
    assert opts["quality"] >= 90
    assert opts["subsampling"] == 0, "chroma subsampling blurs coloured detail"


def test_a_resize_keeps_the_quality_policy(tmp_path):
    """A bare Pillow save() re-encodes JPEG at quality 75. Asking for a smaller
    picture should not quietly hand back a worse one as well."""
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    import random

    from transcripe.core import selftest
    from transcripe.engines.images import resize_image

    random.seed(5)
    img = PIL.new("RGB", (900, 600))
    px = img.load()
    for y in range(600):
        for x in range(900):
            n = random.randint(0, 40)
            px[x, y] = ((x * 255) // 900 + n, (y * 255) // 600 + n, 120 + n)
    src = tmp_path / "photo.jpg"
    img.save(src, quality=98, subsampling=0)

    out = tmp_path / "small.jpg"
    resize_image(src, 600, None, selftest.NULL, output_path=out)

    assert PIL.open(out).size == (600, 400)
    # Pillow's default would land far below this for the same pixels.
    naive = tmp_path / "naive.jpg"
    PIL.open(src).resize((600, 400), PIL.LANCZOS).save(naive)
    assert out.stat().st_size > naive.stat().st_size * 1.3, (
        "resize appears to have fallen back to Pillow's default quality")


def test_lossless_source_stays_lossless_into_webp(tmp_path):
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    from transcripe.engines.images import _save_options

    img = PIL.new("RGB", (32, 32), (1, 2, 3))
    from_png = _save_options(img, "webp", tmp_path / "a.png")
    from_jpg = _save_options(img, "webp", tmp_path / "a.jpg")
    assert from_png.get("lossless") is True
    assert from_jpg.get("lossless") is not True


def test_colour_profile_survives_conversion(tmp_path):
    """Dropping the ICC profile shifts every colour in the picture."""
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    from transcripe.engines.images import _save_options

    img = PIL.new("RGB", (8, 8))
    img.info["icc_profile"] = b"fake-profile"
    assert _save_options(img, "jpg", None)["icc_profile"] == b"fake-profile"


# ── fitting an upload limit ─────────────────────────────────────────────────

def scan_png_bytes(width=900, height=1300) -> bytes:
    """A photograph-like PNG, comfortably over any budget we ask of it."""
    import io
    import random

    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    random.seed(11)
    img = PIL.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            n = random.randint(0, 40)
            px[x, y] = ((x * 255) // width + n, (y * 255) // height + n,
                        128 + ((x + y) % 64) + n)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_a_size_budget_is_met_and_the_picture_survives(open_studio):
    """The studio's half of the promise: ask for 500 KB and 500 KB is what
    comes back — at the resolution it went in, because auto re-encodes a
    lossless photo rather than shrinking it."""
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    import io

    src = scan_png_bytes()
    assert len(src) > 500 * 1024
    with TestClient(open_studio.app) as client:
        started = client.post(
            "/api/convert/file",
            files={"file": ("scan.png", src, "image/png")},
            data={"targetFormat": "auto", "maxSize": "500KB", "deliver": "link"},
        )
        assert started.status_code == 200, started.text
        body = started.json()
        assert body["filename"].endswith(".jpg")
        got = client.get(body["download"])

    assert len(got.content) <= 500 * 1024
    assert PIL.open(io.BytesIO(got.content)).size == (900, 1300)


def test_a_budget_honours_an_explicit_format(open_studio):
    """auto is a default, not a policy — ask for WebP and the budget is met
    in WebP."""
    PIL = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    import io

    with TestClient(open_studio.app) as client:
        started = client.post(
            "/api/convert/file",
            files={"file": ("scan.png", scan_png_bytes(), "image/png")},
            data={"targetFormat": "webp", "maxSize": "200KB", "deliver": "link"},
        )
        assert started.status_code == 200, started.text
        got = client.get(started.json()["download"])

    assert len(got.content) <= 200 * 1024
    assert PIL.open(io.BytesIO(got.content)).format == "WEBP"


def test_auto_without_a_budget_is_refused(open_studio):
    """"auto" only means anything as "hit this size" — on its own it is not a
    format, and guessing one would be inventing an answer."""
    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("scan.png", scan_png_bytes(300, 300), "image/png")},
            data={"targetFormat": "auto"},
        )
    assert res.status_code == 422


def test_a_budget_on_something_that_is_not_an_image_is_refused(open_studio, fixtures):
    """Video has its own size controls; silently ignoring the number here
    would hand back a file that misses the limit the user asked for."""
    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("clip.wav", wav_bytes(fixtures), "audio/wav")},
            data={"targetFormat": "mp3", "maxSize": "500KB"},
        )
    assert res.status_code == 422
    assert "image" in res.json()["detail"].lower()


@pytest.mark.parametrize("bad", ["banana", "", "0KB", "-5MB", "12 gigabytes"])
def test_a_size_that_is_not_a_size_is_refused_not_guessed(open_studio, bad):
    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("scan.png", scan_png_bytes(300, 300), "image/png")},
            data={"targetFormat": "jpg", "maxSize": bad},
        )
    # An empty string means "no budget", which is a plain conversion.
    assert res.status_code == (200 if bad == "" else 422)


# ── remux vs re-encode ──────────────────────────────────────────────────────

@pytest.fixture
def h264_clip(tmp_path):
    """A tiny H.264/yuv420p mp4 — the shape most phone video arrives in."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    import subprocess

    out = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc=size=160x120:rate=15:duration=2", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)],
        check=True, timeout=120)
    return out


def test_matching_codec_is_copied_not_re_encoded(open_studio, h264_clip):
    """H.264 into mkv/mov/mp4 is only a change of wrapper; re-encoding it
    costs ~35x the time and loses quality for nothing."""
    for target in ("mkv", "mov", "mp4"):
        assert open_studio.can_remux(str(h264_clip), target, False) is True


def test_container_that_cannot_hold_the_codec_re_encodes(open_studio, h264_clip):
    # webm takes VP8/VP9/AV1 — never H.264.
    assert open_studio.can_remux(str(h264_clip), "webm", False) is False


def test_audio_target_from_video_is_not_copied(open_studio, h264_clip):
    """The clip has no audio at all, so an audio container would get nothing."""
    assert open_studio.can_remux(str(h264_clip), "mp3", True) is False


def test_unknown_container_never_claims_it_can_copy(open_studio, h264_clip):
    assert open_studio.can_remux(str(h264_clip), "xyz", False) is False


def test_probe_of_a_non_media_file_is_empty(open_studio, tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("not media")
    assert open_studio.probe_streams(str(junk)) == []
    assert open_studio.can_remux(str(junk), "mp4", False) is False


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_remuxed_video_keeps_its_codec_and_duration(open_studio, h264_clip):
    import subprocess

    with TestClient(open_studio.app) as client:
        res = client.post(
            "/api/convert/file",
            files={"file": ("clip.mp4", h264_clip.read_bytes(), "video/mp4")},
            data={"targetFormat": "mkv"},
        )
    assert res.status_code == 200
    out = h264_clip.parent / "out.mkv"
    out.write_bytes(res.content)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
         "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, timeout=60).stdout
    assert "h264" in probe
    assert "2.0" in probe or "1.9" in probe


# ── download selection ──────────────────────────────────────────────────────

def test_download_pick_ignores_sidecars(open_studio, tmp_path):
    """yt-dlp drops thumbnails and .part files next to the media; taking the
    first glob hit could hand the user a JPEG instead of their video."""
    (tmp_path / "video.mp4").write_bytes(b"m" * 5000)
    (tmp_path / "video.jpg").write_bytes(b"t" * 9000)      # bigger, but a thumbnail
    (tmp_path / "video.info.json").write_text("{}")
    (tmp_path / "video.mp4.part").write_bytes(b"p" * 8000)

    assert open_studio.pick_download(str(tmp_path)).endswith("video.mp4")


def test_download_pick_prefers_the_largest_real_file(open_studio, tmp_path):
    (tmp_path / "audio.m4a").write_bytes(b"a" * 100)
    (tmp_path / "video.mp4").write_bytes(b"v" * 9000)
    assert open_studio.pick_download(str(tmp_path)).endswith("video.mp4")


def test_download_pick_returns_empty_when_nothing_landed(open_studio, tmp_path):
    (tmp_path / "only.part").write_bytes(b"x" * 10)
    assert open_studio.pick_download(str(tmp_path)) == ""


# ── cookie opt-out ──────────────────────────────────────────────────────────

def test_browser_cookies_are_not_read_when_declined(open_studio, monkeypatch):
    """Regression: the UI's privacy toggle was accepted and then ignored."""
    monkeypatch.setattr(open_studio.glob, "glob", lambda *a, **k: [])
    assert open_studio.get_rotated_cookie_flag(False) == []
    assert open_studio.get_rotated_cookie_flag(True)[0] == "--cookies-from-browser"
