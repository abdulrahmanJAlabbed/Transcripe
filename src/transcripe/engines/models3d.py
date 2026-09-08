"""3D model engine — convert & web-optimize models via a bundled Node toolchain.

Import (any → glTF/GLB/OBJ/STL/PLY) uses assimp (WASM). Web optimization
(Draco compression, texture compression) uses glTF-Transform. Node.js is the
only external requirement; the npm toolchain is installed on first use.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from rich.console import Console

JS_DIR = Path(__file__).parent / "js"

# Input formats assimp can import (common subset).
MODEL_INPUT_EXTS = {
    ".glb", ".gltf", ".obj", ".fbx", ".3ds", ".dae", ".stl", ".ply",
    ".x", ".off", ".3mf", ".lwo", ".ac", ".ms3d", ".blend",
}
# Formats we can write.
MODEL_OUTPUT_FORMATS = {"glb", "gltf", "obj", "stl", "ply"}

_ASSIMP_FMT = {"glb": "glb2", "gltf": "gltf2", "obj": "obj", "stl": "stl", "ply": "ply"}


def node_available() -> bool:
    return shutil.which("node") is not None


def _mktemp_glb() -> Path:
    """Create a closed temp .glb file safely (mkstemp — no mktemp race)."""
    fd, name = tempfile.mkstemp(suffix=".glb")
    os.close(fd)
    return Path(name)


# glTF-Transform's own dependencies use import attributes (`with { type:
# "json" }`), which Node only understands from 20.10. On an older runtime the
# toolchain dies with a SyntaxError deep inside a dependency, so ask first.
MIN_NODE = (20, 10)


def _node_version(node: str) -> tuple[int, ...]:
    try:
        out = subprocess.run([node, "--version"], capture_output=True,
                             text=True, timeout=10).stdout.strip().lstrip("v")
        return tuple(int(part) for part in out.split(".")[:2])
    except Exception:
        return ()


def _ensure_toolchain(console: Console) -> str:
    node = shutil.which("node")
    if not node:
        raise RuntimeError(
            "Node.js not found. Install Node.js (https://nodejs.org) to convert 3D models.")
    version = _node_version(node)
    if version and version < MIN_NODE:
        raise RuntimeError(
            f"Node {'.'.join(map(str, version))} is too old for the 3D toolchain — "
            f"it needs {'.'.join(map(str, MIN_NODE))} or newer. "
            "Upgrade Node.js (https://nodejs.org).")
    have_assimp = (JS_DIR / "node_modules" / "assimpjs").exists()
    have_gltf = (JS_DIR / "node_modules" / "@gltf-transform" / "cli").exists()
    if not (have_assimp and have_gltf):
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm not found. Install Node.js (which includes npm).")
        with console.status("[bold cyan]Installing 3D toolchain (npm, first run only)…[/bold cyan]"):
            # --include=optional matters: sharp ships its native binary as an
            # optional per-platform package, and without it the toolchain
            # installs "successfully" and then dies on first use saying it
            # cannot load sharp for this runtime.
            res = subprocess.run([npm, "install", "--include=optional",
                                  "--no-audit", "--no-fund"],
                                 cwd=str(JS_DIR), capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"npm install failed: {_node_error(res, 'npm error')}")
    return node


def _node_error(res, fallback: str) -> str:
    """The useful part of a Node failure.

    Taking the last line alone turned a precise SyntaxError into "Node.js
    v18.19.1" — the crash banner — which is the one line that says nothing.
    The real cause is the first line naming an error, so prefer that and keep
    a little context around it.
    """
    text = (res.stderr or "").strip() or (res.stdout or "").strip()
    if not text:
        return fallback
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        if "Error" in line or "error" in line:
            return " · ".join(lines[i:i + 2])[:400]
    return " · ".join(lines[-3:])[:400]


def _run_node(script: str, args: list[str], console: Console) -> str:
    node = _ensure_toolchain(console)
    res = subprocess.run([node, str(JS_DIR / script), *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(_node_error(res, "unknown error"))
    return res.stdout


def _gltf_transform(args: list[str], console: Console) -> str:
    _ensure_toolchain(console)
    binp = JS_DIR / "node_modules" / ".bin" / "gltf-transform"
    res = subprocess.run([str(binp), *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(_node_error(res, "gltf-transform error"))
    return res.stdout


def _import_to(input_path: Path, target: str, out_path: Path, console: Console):
    _run_node("import_model.js", [str(input_path), _ASSIMP_FMT[target], str(out_path)], console)


def _export_mesh(input_path: Path, target: str, out_path: Path, console: Console):
    """Export geometry to obj/stl/ply via trimesh (assimp import first if needed)."""
    try:
        import trimesh  # noqa: F401
    except Exception:
        raise RuntimeError(f"Exporting to .{target} needs trimesh — run: pip install trimesh")

    ext = input_path.suffix.lower()
    tmp = None
    if ext in (".glb", ".gltf", ".obj", ".stl", ".ply", ".dae", ".off"):
        src = input_path  # trimesh can read these directly
    else:
        tmp = _mktemp_glb()
        _import_to(input_path, "glb", tmp, console)
        src = tmp

    import trimesh
    scene = trimesh.load(str(src), force="scene")
    scene.export(str(out_path))
    if tmp:
        tmp.unlink(missing_ok=True)


def convert_model(input_path: Path, target_format: str, console: Console,
                  output_path: Path | None = None, optimize: bool = True,
                  compress: str = "draco"):
    """Convert a 3D model. For glb/gltf, `optimize` applies Draco + texture compression."""
    target_format = target_format.lower().lstrip(".")
    if target_format not in MODEL_OUTPUT_FORMATS:
        raise ValueError(f"Unsupported 3D target: .{target_format}")

    out_path = output_path or input_path.with_suffix(f".{target_format}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ext = input_path.suffix.lower()

    # Mesh-only targets → trimesh exporter.
    if target_format in ("obj", "stl", "ply"):
        with console.status(f"[bold cyan]Converting {input_path.name} → {target_format.upper()}…[/bold cyan]"):
            _export_mesh(input_path, target_format, out_path, console)
        size = out_path.stat().st_size / 1024
        console.print(f"[bold green]✓ Created {out_path.name}[/bold green] [dim]({size:.0f} KB)[/dim]")
        return

    # Plain glTF/GLB without optimization → direct assimp convert.
    if target_format in ("glb", "gltf") and not optimize:
        with console.status(f"[bold cyan]Converting {input_path.name} → {target_format.upper()}…[/bold cyan]"):
            _import_to(input_path, target_format, out_path, console)
        size = out_path.stat().st_size / 1024
        console.print(f"[bold green]✓ Created {out_path.name}[/bold green] [dim]({size:.0f} KB)[/dim]")
        return

    # Optimized glTF/GLB for the web: import (if needed) → glTF-Transform optimize.
    original = input_path.stat().st_size
    with console.status(f"[bold cyan]Building web-optimized {target_format.upper()} ({compress})…[/bold cyan]"):
        if ext in (".glb", ".gltf"):
            src = input_path
            tmp = None
        else:
            tmp = _mktemp_glb()
            _import_to(input_path, "glb", tmp, console)
            src = tmp

        args = ["optimize", str(src), str(out_path), "--simplify", "false",
                "--texture-compress", "webp"]
        if compress in ("draco", "meshopt"):
            args += ["--compress", compress]
        else:
            args += ["--compress", "false"]
        _gltf_transform(args, console)

        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)

    new = out_path.stat().st_size
    reduction = (1 - new / original) * 100 if original else 0
    console.print(
        f"[bold green]✓ Created {out_path.name}[/bold green] "
        f"[dim]{original/1_048_576:.1f} MB → {new/1_048_576:.2f} MB "
        f"({reduction:.0f}% smaller, {compress})[/dim]")


def optimize_glb(input_path: Path, console: Console, output_path: Path | None = None,
                 compress: str = "draco"):
    """Optimize an existing GLB/glTF for the web (Draco + WebP textures)."""
    convert_model(input_path, "glb", console, output_path=output_path,
                  optimize=True, compress=compress)


def inspect(input_path: Path, console: Console):
    """Print a summary of a glTF/GLB model."""
    out = _gltf_transform(["inspect", str(input_path)], console)
    console.print(out)
