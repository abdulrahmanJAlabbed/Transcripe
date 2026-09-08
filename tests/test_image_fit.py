"""Fitting an image to a file-size budget.

The budget is a hard promise — an upload form rejects 501 KB as surely as it
rejects 5 MB — so every test here asserts the ceiling first. The rest assert
what the picture cost to get there, because a tool that always answered with a
16x16 thumbnail would pass the first assertion every time.
"""
from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="Pillow not installed")

from PIL import Image  # noqa: E402

from transcripe.core import selftest  # noqa: E402
from transcripe.engines import images  # noqa: E402

NULL = selftest.NULL
KB = 1024


def photo(path: Path, width=900, height=1300, fmt=None) -> Path:
    """A picture that behaves like a photograph: smooth gradients with enough
    noise that it cannot be compressed to nothing."""
    import random

    random.seed(11)
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            n = random.randint(0, 40)
            px[x, y] = ((x * 255) // width + n, (y * 255) // height + n,
                        128 + ((x + y) % 64) + n)
    img.save(path, format=fmt)
    return path


# ── the ceiling is the promise ──────────────────────────────────────────────

@pytest.mark.parametrize("suffix", [".jpg", ".png", ".webp"])
@pytest.mark.parametrize("budget", [500 * KB, 120 * KB, 30 * KB])
def test_the_result_is_never_over_budget(tmp_path, suffix, budget):
    src = photo(tmp_path / f"src{suffix}")
    out = images.fit_size(src, NULL, output_path=tmp_path / f"out{suffix}",
                          max_bytes=budget, target_format="auto")
    assert out.stat().st_size <= budget
    Image.open(out).verify()


# ── what the picture paid ───────────────────────────────────────────────────

def test_a_photo_in_a_lossless_format_keeps_its_resolution(tmp_path):
    """The case this feature exists for: a scan saved as PNG, held to an upload
    limit. Shrinking it is the wrong answer when re-encoding costs nothing you
    can see — so auto changes the format instead of the picture."""
    src = photo(tmp_path / "scan.png")
    assert src.stat().st_size > 500 * KB

    out = images.fit_size(src, NULL, output_path=tmp_path / "fitted.png",
                          max_bytes=500 * KB, target_format="auto")

    assert out.stat().st_size <= 500 * KB
    assert out.suffix == ".jpg", "auto should leave a lossless format it cannot fit"
    assert Image.open(out).size == Image.open(src).size, "pixels were spent needlessly"


def test_keeping_the_format_is_still_possible(tmp_path):
    """auto is a default, not a policy. Ask for PNG and you get PNG, even
    though meeting the budget then costs resolution."""
    src = photo(tmp_path / "scan.png")
    out = images.fit_size(src, NULL, output_path=tmp_path / "fitted.png",
                          max_bytes=300 * KB, target_format="png")
    assert out.suffix == ".png"
    assert Image.open(out).format == "PNG"
    assert out.stat().st_size <= 300 * KB


@pytest.mark.parametrize("budget_kb", [300, 150, 60, 25])
def test_the_budget_is_spent_not_merely_respected(tmp_path, budget_kb):
    """Landing at 200 KB when 500 KB was allowed is a worse picture for no
    reason. A stepped search does that; a binary search plus one corrective
    step lands just under the line instead."""
    src = photo(tmp_path / "scan.png")
    budget = budget_kb * KB
    out = images.fit_size(src, NULL, output_path=tmp_path / "out.png",
                          max_bytes=budget, target_format="auto")
    size = out.stat().st_size
    assert size <= budget
    assert size > budget * 0.85, (
        f"used only {size / KB:.0f} KB of a {budget_kb} KB budget")


def test_a_file_already_under_budget_is_left_alone(tmp_path):
    """Re-encoding to solve a problem that doesn't exist costs quality for
    nothing, so an image that already fits is copied byte for byte."""
    src = photo(tmp_path / "small.jpg", width=200, height=200)
    before = src.read_bytes()
    assert len(before) < 500 * KB

    out = images.fit_size(src, NULL, output_path=tmp_path / "out.jpg",
                          max_bytes=500 * KB, target_format="auto")
    assert out.read_bytes() == before


def test_quality_is_spent_before_resolution(tmp_path):
    """The ladder that makes the output look right: a photo at full size and
    middling quality beats the same photo at high quality and half the pixels.
    A 1.9 MB scan squeezed to 150 KB still comes back the size it went in."""
    src = photo(tmp_path / "scan.png")
    original = Image.open(src).size
    out = images.fit_size(src, NULL, output_path=tmp_path / "out.png",
                          max_bytes=150 * KB, target_format="auto")
    assert out.stat().st_size <= 150 * KB
    assert Image.open(out).size == original


def test_pixels_do_go_when_there_is_nothing_else_left(tmp_path):
    """The other half of that promise: resolution is the last thing spent, but
    it is spent. A budget no amount of compression can meet must still be met."""
    src = photo(tmp_path / "scan.png")
    out = images.fit_size(src, NULL, output_path=tmp_path / "out.png",
                          max_bytes=25 * KB, target_format="auto")
    assert out.stat().st_size <= 25 * KB
    assert Image.open(out).size < Image.open(src).size


# ── bounds and bad input ────────────────────────────────────────────────────

def test_a_floor_and_a_ceiling_together(tmp_path):
    src = photo(tmp_path / "src.jpg", width=400, height=400)
    out = images.fit_size(src, NULL, output_path=tmp_path / "out.jpg",
                          min_bytes=40 * KB, max_bytes=200 * KB,
                          target_format="auto")
    assert 40 * KB <= out.stat().st_size <= 200 * KB


def test_an_impossible_pair_of_bounds_is_refused(tmp_path):
    src = photo(tmp_path / "src.jpg", width=100, height=100)
    with pytest.raises(ValueError):
        images.fit_size(src, NULL, output_path=tmp_path / "out.jpg",
                        min_bytes=200 * KB, max_bytes=100 * KB)


def test_no_bound_at_all_is_refused(tmp_path):
    src = photo(tmp_path / "src.jpg", width=100, height=100)
    with pytest.raises(ValueError):
        images.fit_size(src, NULL, output_path=tmp_path / "out.jpg")


@pytest.mark.parametrize("text,expected", [
    ("500KB", 500 * KB), ("2 MB", 2 * KB * KB), ("9.77KB", 10004),
    ("500k", 500 * KB), ("10000", 10000), ("1B", 1),
])
def test_sizes_are_read_the_way_people_write_them(text, expected):
    assert images.parse_size(text) == expected


def test_transparency_survives_a_budget(tmp_path):
    """A logo with a transparent background must not come back on a black or
    white box, so auto picks the lossy format that keeps alpha."""
    img = Image.new("RGBA", (900, 900), (0, 0, 0, 0))
    for x in range(0, 900, 2):
        for y in range(0, 900, 2):
            img.putpixel((x, y), ((x * 7) % 256, (y * 5) % 256, 90, 255))
    src = tmp_path / "logo.png"
    img.save(src)

    out = images.fit_size(src, NULL, output_path=tmp_path / "out.png",
                          max_bytes=60 * KB, target_format="auto")
    assert out.stat().st_size <= 60 * KB
    assert Image.open(out).mode in ("RGBA", "LA", "P"), "alpha was flattened away"


# ── the name is settled before the file is written ──────────────────────────

def test_the_planned_name_is_the_name_that_gets_written(tmp_path):
    """The wizard shows where a file will land and refuses to overwrite what
    is already there. Both promises are worthless if the extension is decided
    later, so the plan and the result have to agree."""
    src = photo(tmp_path / "scan.png")
    for budget, fmt in ((500 * KB, "auto"), (300 * KB, "png"),
                        (500 * KB, "webp"), (5000 * KB, "auto")):
        planned = images.planned_extension(src, budget, fmt)
        out = images.fit_size(src, NULL, output_path=tmp_path / "out.png",
                              max_bytes=budget, target_format=fmt)
        assert out.suffix == f".{planned}", f"planned .{planned}, wrote {out.suffix}"


def test_keeping_the_source_format_needs_no_guesswork(tmp_path):
    src = photo(tmp_path / "scan.png")
    assert images.planned_extension(src, 100 * KB, None) == "png"


# ── every format it claims to read ──────────────────────────────────────────

def written_in(path: Path, ext: str) -> Path:
    """Save the standard fixture in `ext`, or skip when the codec is absent."""
    images._pil()  # registers the HEIF/AVIF openers
    img = Image.open(photo(path.parent / "seed.png"))
    if ext == "gif":
        img = img.convert("P")
    out = path.parent / f"in.{ext}"
    try:
        img.save(out)
    except Exception as exc:  # noqa: BLE001 - codec absence is a skip, not a failure
        pytest.skip(f"no encoder for .{ext} here ({type(exc).__name__})")
    return out


READABLE = ["png", "jpg", "webp", "bmp", "tiff", "gif", "ico", "heic", "avif"]


@pytest.mark.parametrize("ext", READABLE)
def test_a_budget_works_from_every_format_we_read(tmp_path, ext):
    """The formats people actually arrive with. .heic especially: phones hand
    those over, and Pillow registers the container as HEIF, so asking it to
    write "HEIC" used to fail with a bare KeyError."""
    src = written_in(tmp_path / "x", ext)
    out = images.fit_size(src, NULL, output_path=tmp_path / f"out.{ext}",
                          max_bytes=25 * KB, target_format="auto")
    assert out.stat().st_size <= 25 * KB
    Image.open(out).verify()


@pytest.mark.parametrize("ext", READABLE)
def test_a_resize_works_from_every_format_we_read(tmp_path, ext):
    src = written_in(tmp_path / "x", ext)
    images.resize_image(src, 120, None, NULL,
                        output_path=tmp_path / f"small.{ext}")
    assert (tmp_path / f"small.{ext}").stat().st_size > 0


def test_a_vector_source_lands_somewhere_that_can_be_written(tmp_path):
    """SVG only comes in: it is rasterised on the way past _open_image and
    there is no writing it back, so keeping the source extension would ask
    Pillow for the impossible. PNG keeps every pixel of the raster."""
    pytest.importorskip("cairosvg", reason="cairosvg not installed")
    svg = tmp_path / "logo.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" '
                   'height="120"><rect width="200" height="120" fill="#246"/></svg>')

    assert images.planned_extension(svg, 40 * KB, "auto") != "svg"
    out = images.fit_size(svg, NULL, output_path=tmp_path / "out.svg",
                          max_bytes=40 * KB, target_format="auto")
    assert out.suffix != ".svg"
    assert out.stat().st_size <= 40 * KB
    Image.open(out).verify()


@pytest.mark.parametrize("ext", READABLE + ["svg"])
def test_the_planned_extension_is_always_writable(tmp_path, ext):
    """planned_extension feeds the wizard's output path and its overwrite
    guard, so an extension nothing can write there is a promise that breaks
    only once the work is already done."""
    images._pil()
    assert images._writable(ext) == images._writable(images._writable(ext))
    assert images._writable("svg") == "png"


def test_asking_for_a_read_only_format_says_so(tmp_path):
    src = photo(tmp_path / "src.png")
    with pytest.raises(ValueError, match="read-only"):
        images.fit_size(src, NULL, output_path=tmp_path / "o.png",
                        max_bytes=40 * KB, target_format="svg")
