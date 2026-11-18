"""Compile article-local diagrams to an ignored Hugo content overlay.

Only ``content/posts/<slug>/diagrams/*.tex`` are entry points.  They are full,
single-page LaTeX documents; dependencies can live anywhere inside the bundle.
Source bundles are copied into temporary build space and are never modified.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from articles import validate_articles


SCHEMA = 2
COMPILE_TIMEOUT = 60
OUTPUT_DIRECTORY = Path(".cache/tikz-content")
CACHE_DIRECTORY = Path(".cache/tikz")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == raw:
        return
    descriptor, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _future(value, now: dt.datetime) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        value = dt.datetime.combine(value, dt.time())
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return value > now


def _entry_points(root: Path, include_drafts: bool, now: dt.datetime) -> list[Path]:
    sources = []
    for article in validate_articles(root):
        if article["draft"] and not include_drafts:
            continue
        if _future(article.get("date"), now):
            continue
        diagrams = article["path"].parent / "diagrams"
        if diagrams.is_dir():
            sources.extend(sorted(diagrams.glob("*.tex")))
    return sources


def _tool(name: str) -> Path:
    executable = shutil.which(name)
    if executable is None:
        candidate = Path("/Library/TeX/texbin") / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            executable = str(candidate)
    if executable is None:
        raise RuntimeError(
            "TikZ requires latex and dvisvgm (TeX Live/MacTeX); "
            f"cannot find {name}. No diagrams were published."
        )
    # TeX selects its format from argv[0]; resolving the latex symlink would
    # invoke pdftex instead and lose the LaTeX format.
    return Path(executable).absolute()


def _run(command: list[str], cwd: Path, *, timeout: int = COMPILE_TIMEOUT) -> str:
    try:
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, errors="replace",
            timeout=timeout, env=dict(os.environ, openout_any="p"),
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"TikZ command timed out after {timeout}s: {Path(command[0]).name}") from error
    if result.returncode:
        output = (result.stdout + "\n" + result.stderr).strip()
        raise RuntimeError(f"TikZ {Path(command[0]).name} failed:\n{output[-10000:]}")
    return result.stdout + result.stderr


def _read_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict) and data.get("schema") == SCHEMA and isinstance(data.get("sources"), dict):
        return data["sources"]
    return {}


def _fresh(entry: dict, tools: str, root: Path, output: Path) -> bool:
    if not isinstance(entry, dict) or entry.get("tools") != tools or not output.is_file():
        return False
    dependencies = entry.get("inputs")
    if not isinstance(dependencies, dict) or not dependencies:
        return False
    try:
        if _sha256(output) != entry.get("output_sha256"):
            return False
        return all(_sha256(root / location) == digest for location, digest in dependencies.items())
    except (OSError, TypeError):
        return False


def _inputs(fls: Path, cwd: Path, copied_bundle: Path, original_bundle: Path, root: Path, temporary: Path) -> dict[str, str]:
    paths = {}
    for line in fls.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("INPUT "):
            continue
        path = Path(line[6:])
        if not path.is_absolute():
            path = cwd / path
        path = path.resolve()
        if path.is_relative_to(copied_bundle):
            digest = _sha256(path)
            path = original_bundle / path.relative_to(copied_bundle)
            if not path.is_file() or _sha256(path) != digest:
                raise RuntimeError(f"TikZ input changed during compilation; retry: {path}")
        elif path.is_relative_to(temporary):
            continue  # generated .aux files are not author inputs
        elif path.is_file():
            digest = _sha256(path)
        if path.is_file():
            paths[path] = digest
    return {
        str(path.relative_to(root)) if path.is_relative_to(root) else str(path): digest
        for path, digest in sorted(paths.items())
    }


def _dvi_specials(path: Path) -> list[bytes]:
    """Read classic DVI specials without interpreting or rewriting the DVI."""
    raw = path.read_bytes()
    if raw[:2] != b"\xf7\x02":
        raise RuntimeError("TikZ requires classic DVI output from latex.")
    specials = []
    cursor = 0
    while cursor < len(raw):
        opcode = raw[cursor]
        cursor += 1
        if opcode <= 127 or opcode in (138, 140, 141, 142, 147, 152, 161, 166) or 171 <= opcode <= 234:
            continue
        if 239 <= opcode <= 242:
            size = opcode - 238
            length = int.from_bytes(raw[cursor:cursor + size], "big")
            cursor += size
            specials.append(raw[cursor:cursor + length])
            cursor += length
        elif 243 <= opcode <= 246:
            fixed = opcode - 242 + 12
            cursor += fixed + 2 + raw[cursor + fixed] + raw[cursor + fixed + 1]
        elif opcode == 247:
            cursor += 14 + raw[cursor + 13]
        elif opcode == 248:
            break
        elif opcode in (132, 137):
            cursor += 8
        elif opcode == 139:
            cursor += 44
        elif 128 <= opcode <= 131:
            cursor += opcode - 127
        elif 133 <= opcode <= 136:
            cursor += opcode - 132
        elif 143 <= opcode <= 146:
            cursor += opcode - 142
        elif 148 <= opcode <= 151:
            cursor += opcode - 147
        elif 153 <= opcode <= 156:
            cursor += opcode - 152
        elif 157 <= opcode <= 160:
            cursor += opcode - 156
        elif 162 <= opcode <= 165:
            cursor += opcode - 161
        elif 167 <= opcode <= 170:
            cursor += opcode - 166
        elif 235 <= opcode <= 238:
            cursor += opcode - 234
        else:
            raise RuntimeError(f"TikZ produced unsupported DVI opcode {opcode}.")
    return specials


def _compile(root: Path, source: Path, latex: Path, dvisvgm: Path) -> tuple[bytes, dict[str, str]]:
    bundle = source.parent.parent
    if any(character in source.name for character in "%{}\\\r\n"):
        raise ValueError(f"TikZ entry-point filename contains unsupported TeX characters: {source.name}")
    with tempfile.TemporaryDirectory(prefix="tikz-", dir=root / CACHE_DIRECTORY) as directory:
        temporary = Path(directory).resolve()
        copied_bundle = temporary / "bundle"
        shutil.copytree(bundle, copied_bundle)
        cwd = copied_bundle / "diagrams"
        output = temporary / "output"
        output.mkdir()
        # LaTeX's \include writes per-file .aux files and does not create their
        # parent directories inside -output-directory.
        for directory in cwd.rglob("*"):
            if directory.is_dir():
                (output / directory.relative_to(cwd)).mkdir(parents=True, exist_ok=True)
        _run([
            str(latex), "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
            "-file-line-error", "-recorder", "-jobname=figure", f"-output-directory={output}",
            # Select PGF's SVG driver before loading the author's document.
            # The default dvips driver needs Ghostscript and may otherwise
            # leave only glyphs while silently dropping paths and arrows.
            r"\RequirePackage[backend=dvisvgm]{expl3}"
            r"\PassOptionsToPackage{dvisvgm}{graphics,graphicx,color,xcolor}"
            r"\def\pgfsysdriver{pgfsys-dvisvgm.def}\input{\detokenize{" + source.name + "}}",
        ], cwd)
        dvi = output / "figure.dvi"
        if not dvi.is_file():
            raise RuntimeError(f"TikZ produced no DVI: {source.relative_to(root)}")
        # standalone emits PostScript page-box metadata even with the SVG
        # graphics driver. It is safe to ignore just this metadata: dvisvgm
        # computes its own tight box. All drawing PostScript must be rejected.
        postscript = [value for value in _dvi_specials(dvi) if value.startswith((b"ps:", b"PSfile=", b"header=", b"!", b'"'))]
        if any(not value.startswith((b"ps::%%HiResBoundingBox:", b"ps::%%PageBoundingBox:")) for value in postscript):
            raise RuntimeError("TikZ contains unsupported PostScript drawing specials; use SVG-compatible TikZ graphics.")
        conversion = _run([
            str(dvisvgm), "--no-fonts", "--embed-bitmaps", "--bbox=min", "--page=1-",
            f"--output={output / 'figure-%p.svg'}", str(dvi),
        ], cwd)
        pages = sorted(output.glob("figure-*.svg"))
        if len(pages) != 1:
            raise RuntimeError(f"TikZ must produce exactly one page: {source.relative_to(root)} ({len(pages)} pages)")
        ignored_pattern = r"(?im)^\s*WARNING: (\d+) PostScript specials? ignored\. The resulting SVG might look wrong\.\s*$"
        ignored = re.findall(ignored_pattern, conversion)
        remaining = conversion
        if ignored and sum(map(int, ignored)) == len(postscript):
            remaining = re.sub(ignored_pattern, "", remaining)
        if re.search(r"(?im)^\s*(?:warning|error)\b|specials? ignored", remaining):
            raise RuntimeError(f"TikZ SVG conversion was incomplete:\n{conversion[-10000:]}")
        raw = pages[0].read_bytes()
        try:
            svg = ET.fromstring(raw)
        except ET.ParseError as error:
            raise RuntimeError(f"TikZ produced invalid SVG: {source.relative_to(root)}") from error
        try:
            viewbox = [float(value) for value in svg.get("viewBox", "").split()]
            visible = len(viewbox) == 4 and all(math.isfinite(value) for value in viewbox) and viewbox[2] > 0 and viewbox[3] > 0
        except ValueError:
            visible = False
        if svg.tag != "{http://www.w3.org/2000/svg}svg" or not visible:
            raise RuntimeError(f"TikZ produced invalid SVG: {source.relative_to(root)}")
        dependencies = _inputs(output / "figure.fls", cwd, copied_bundle, bundle, root, temporary)
        original_digest = _sha256(cwd / source.name)
        if _sha256(source) != original_digest:
            raise RuntimeError(f"TikZ input changed during compilation; retry: {source}")
        dependencies[str(source.relative_to(root))] = original_digest
        return raw, dependencies


def prepare_tikz(root, include_drafts: bool = False, *, now: dt.datetime | None = None) -> list[Path]:
    """Prepare the Hugo content overlay, reusing unchanged outputs without writes.

    Future articles are excluded, matching Hugo's default behavior even in draft
    preview. Missing tools are only errors when an eligible diagram exists.
    """
    root = Path(root).resolve()
    now = now or dt.datetime.now(dt.timezone.utc)
    sources = _entry_points(root, include_drafts, now)
    destination = root / OUTPUT_DIRECTORY
    cache = root / CACHE_DIRECTORY
    for directory in (destination, cache):
        if directory.is_symlink():
            raise ValueError(f"TikZ cache must not be a symbolic link: {directory}")
        directory.mkdir(parents=True, exist_ok=True)
    targets = {source: destination / source.relative_to(root / "content").with_suffix(".svg") for source in sources}
    for source, output in targets.items():
        original_svg = source.with_suffix(".svg")
        if original_svg.exists():
            output.unlink(missing_ok=True)
            raise ValueError(
                f"TikZ output conflicts with an existing article resource: {original_svg.relative_to(root)}. "
                "Choose a different diagram source name; the existing SVG was not changed."
            )
    expected = set(targets.values())
    for old in destination.rglob("*.svg"):
        if old not in expected:
            old.unlink()
    if not sources:
        _atomic_write(cache / "manifest.json", (json.dumps({"schema": SCHEMA, "sources": {}}) + "\n").encode())
        return []
    try:
        latex, dvisvgm = _tool("latex"), _tool("dvisvgm")
        tools = json.dumps({str(tool): _run([str(tool), "--version"], root, timeout=10) for tool in (latex, dvisvgm)}, sort_keys=True)
    except (RuntimeError, OSError):
        for output in targets.values():
            output.unlink(missing_ok=True)
        raise
    previous = _read_manifest(cache / "manifest.json")
    entries = {}
    for source, output in targets.items():
        key = str(source.relative_to(root / "content"))
        entry = previous.get(key, {})
        if _fresh(entry, tools, root, output):
            entries[key] = entry
            continue
        output.unlink(missing_ok=True)
        try:
            raw, dependencies = _compile(root, source, latex, dvisvgm)
        except (RuntimeError, OSError) as error:
            raise RuntimeError(f"Cannot build TikZ diagram {source.relative_to(root)}: {error}") from error
        _atomic_write(output, raw)
        entries[key] = {"tools": tools, "inputs": dependencies, "output_sha256": hashlib.sha256(raw).hexdigest()}
    _atomic_write(cache / "manifest.json", (json.dumps({"schema": SCHEMA, "sources": entries}, indent=2, sort_keys=True) + "\n").encode())
    return list(targets.values())
