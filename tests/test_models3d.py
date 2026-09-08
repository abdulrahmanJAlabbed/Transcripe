"""3D model conversion (needs Node.js toolchain; skips otherwise)."""
import pytest

from transcripe.engines import models3d
from transcripe.core import capabilities

pytestmark = pytest.mark.skipif(not capabilities.can("model3d"),
                                reason="Node.js toolchain unavailable")


def test_obj_to_web_glb_is_draco(fixtures, tmp_path, nullconsole):
    if "obj" not in fixtures:
        pytest.skip("obj fixture unavailable")
    out = tmp_path / "cube_web.glb"
    models3d.convert_model(fixtures["obj"], "glb", nullconsole,
                           output_path=out, optimize=True, compress="draco")
    data = out.read_bytes()
    assert data[:4] == b"glTF", "not a valid GLB container"
    assert len(data) > 0


def test_obj_to_plain_glb(fixtures, tmp_path, nullconsole):
    if "obj" not in fixtures:
        pytest.skip("obj fixture unavailable")
    out = tmp_path / "cube.glb"
    models3d.convert_model(fixtures["obj"], "glb", nullconsole,
                           output_path=out, optimize=False)
    assert out.read_bytes()[:4] == b"glTF"


@pytest.mark.skipif(not capabilities.can("model3d_mesh"), reason="trimesh unavailable")
def test_obj_to_stl_and_ply(fixtures, tmp_path, nullconsole):
    if "obj" not in fixtures:
        pytest.skip("obj fixture unavailable")
    for fmt in ("stl", "ply"):
        out = tmp_path / f"cube.{fmt}"
        models3d.convert_model(fixtures["obj"], fmt, nullconsole, output_path=out, optimize=False)
        assert out.stat().st_size > 0, f"{fmt} export empty"


# ── failures should say what failed ─────────────────────────────────────────

class _Res:
    def __init__(self, stderr="", stdout=""):
        self.stderr, self.stdout = stderr, stdout


def test_a_node_crash_reports_its_cause_not_its_version_banner():
    """A Node crash ends with its own version line, so taking the last line
    turned a precise SyntaxError into "Node.js v18.19.1" — the one line that
    explains nothing. Debugging that cost real time."""
    from transcripe.engines.models3d import _node_error

    crash = (
        "file:///…/node_modules/sharp/dist/utility.mjs:14\n"
        'import pkg from "../package.json" with { type: "json" };\n'
        "                                  ^^^^\n"
        "\n"
        "SyntaxError: Unexpected token 'with'\n"
        "    at ModuleLoader.moduleStrategy (node:internal/modules/esm/translators:152:18)\n"
        "\n"
        "Node.js v18.19.1\n"
    )
    msg = _node_error(_Res(stderr=crash), "unknown error")
    assert "SyntaxError" in msg
    assert msg != "Node.js v18.19.1"


def test_an_empty_failure_still_says_something():
    from transcripe.engines.models3d import _node_error

    assert _node_error(_Res(), "gltf-transform error") == "gltf-transform error"


def test_the_toolchain_declares_the_node_it_needs():
    """glTF-Transform's dependencies use import attributes, which Node only
    understands from 20.10 — and the failure without them is a SyntaxError
    deep inside a dependency rather than anything actionable."""
    import json
    from pathlib import Path as P

    from transcripe.engines import models3d

    manifest = json.loads((P(models3d.JS_DIR) / "package.json").read_text())
    assert manifest["engines"]["node"].startswith(">=20")
    assert models3d.MIN_NODE >= (20, 10)
