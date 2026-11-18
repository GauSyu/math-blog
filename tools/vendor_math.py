"""Vendor Hugo's matching KaTeX CSS/fonts; normal builds use committed assets."""
from datetime import datetime, timezone
from pathlib import Path
import base64
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
import urllib.request


VERSION = "0.18.4"
HUGO_VERSION = "0.170.0"
PACKAGE_URL = "https://registry.npmjs.org/katex/-/katex-0.18.4.tgz"
INTEGRITY = "sha512-IMPntbRLOU+eu88XDiFKqQ8Akhr9Tv7jDMXqPhjG9SI1JMA4DIgXk4x9k4skJz2NZJXBRbC+2pYBLj9olqcZow=="
HUGO_SOURCE = "https://github.com/gohugoio/hugo/blob/v0.170.0/internal/warpc/js/package.json"
MAX_DOWNLOAD = 16 * 1024 * 1024


def verify_math(root):
    """Check the entire committed asset set without accessing the network."""
    target = Path(root) / "static/assets/katex"
    provenance = json.loads((target / "PROVENANCE.json").read_text(encoding="utf-8"))
    if provenance.get("version") != VERSION or provenance.get("packageIntegrity") != INTEGRITY:
        raise RuntimeError("Vendored KaTeX version or package integrity differs from tools/vendor_math.py.")
    expected = set()
    for record in provenance["files"]:
        name = record["path"]
        if name not in {"katex.min.css", "LICENSE"} and not re.fullmatch(r"fonts/[A-Za-z0-9_.-]+", name):
            raise RuntimeError("Unexpected KaTeX asset path: " + name)
        if name in expected:
            raise RuntimeError("Duplicate KaTeX asset in provenance: " + name)
        expected.add(name)
        actual = hashlib.sha256((target / name).read_bytes()).hexdigest()
        if actual != record["sha256"]:
            raise RuntimeError("Vendored KaTeX checksum mismatch: " + name)
    actual_files = {file.relative_to(target).as_posix() for file in target.rglob("*") if file.is_file()}
    if actual_files != expected | {"PROVENANCE.json"}:
        raise RuntimeError("Vendored KaTeX assets differ from their provenance manifest.")
    css = (target / "katex.min.css").read_text(encoding="utf-8")
    references = set(re.findall(r"url\(['\"]?(fonts/[^)'\"]+)['\"]?\)", css))
    if not references or not references.issubset(expected):
        raise RuntimeError("KaTeX CSS references missing fonts.")
    if not {"katex.min.css", "LICENSE"}.issubset(expected):
        raise RuntimeError("KaTeX CSS or license is missing.")
    return provenance


def ensure_math(root):
    """Reuse verified assets, or fetch the exact pinned package if absent."""
    target = Path(root) / "static/assets/katex"
    if (target / "PROVENANCE.json").is_file():
        verify_math(root)
        return target
    if target.exists() and any(target.iterdir()):
        raise RuntimeError("KaTeX assets have no provenance manifest; refusing to overwrite them.")
    with urllib.request.urlopen(PACKAGE_URL, timeout=30) as response:
        payload = response.read(MAX_DOWNLOAD + 1)
    if len(payload) > MAX_DOWNLOAD:
        raise RuntimeError("KaTeX archive exceeds the download size limit.")
    actual_integrity = "sha512-" + base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii")
    if actual_integrity != INTEGRITY:
        raise RuntimeError("KaTeX archive integrity mismatch.")

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        def read_member(name):
            member = archive.getmember("package/" + name)
            if not member.isfile() or member.size > MAX_DOWNLOAD:
                raise RuntimeError("Invalid KaTeX archive member: " + name)
            with archive.extractfile(member) as handle:
                return handle.read()

        css = read_member("dist/katex.min.css")
        fonts = set(re.findall(r"url\(['\"]?(fonts/[^)'\"]+)['\"]?\)", css.decode("utf-8")))
        if not fonts or any(not re.fullmatch(r"fonts/[A-Za-z0-9_.-]+", name) for name in fonts):
            raise RuntimeError("Unexpected font references in the pinned KaTeX stylesheet.")
        files = {"katex.min.css": css, "LICENSE": read_member("LICENSE")}
        files.update({name: read_member("dist/" + name) for name in sorted(fonts)})

    provenance = {
        "package": "katex",
        "version": VERSION,
        "hugoVersion": HUGO_VERSION,
        "hugoVersionSource": HUGO_SOURCE,
        "packageMetadata": "https://registry.npmjs.org/katex/0.18.4",
        "packageURL": PACKAGE_URL,
        "packageIntegrity": INTEGRITY,
        "archiveSHA256": hashlib.sha256(payload).hexdigest(),
        "retrievedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": [{"path": name, "sha256": hashlib.sha256(data).hexdigest()} for name, data in sorted(files.items())],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".katex-", dir=target.parent) as temporary:
        staged = Path(temporary) / "assets"
        staged.mkdir()
        for name, data in files.items():
            output = staged / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        (staged / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        os.replace(staged, target)
    verify_math(root)
    return target


if __name__ == "__main__":
    print(ensure_math(Path(__file__).resolve().parent.parent))
