"""Project-local, checksum-verified Hugo runtime. No system installation."""
from pathlib import Path
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

def ensure_hugo(root):
    root = Path(root)
    config = json.loads((root / "tools/runtime.json").read_text())
    target = root / ".cache/bin/hugo"
    if target.is_file():
        result = subprocess.run([str(target), "version"], capture_output=True, text=True, check=True)
        if ("v" + config["version"]) in result.stdout:
            return target
        raise RuntimeError("Cached Hugo version differs from tools/runtime.json.")
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        name = "hugo_" + config["version"] + "_darwin-universal.pkg"
    elif system == "linux" and machine in {"x86_64", "aarch64", "arm64"}:
        arch = "amd64" if machine == "x86_64" else "arm64"
        name = "hugo_" + config["version"] + "_linux-" + arch + ".tar.gz"
    else:
        raise RuntimeError("This bootstrap supports macOS and Linux amd64/arm64.")
    print("Downloading official Hugo " + config["version"] + "…", flush=True)
    payload = urllib.request.urlopen(config["url"] + name, timeout=120).read()
    if hashlib.sha256(payload).hexdigest() != config["assets"][name]:
        raise RuntimeError("Hugo download checksum mismatch.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="math-blog-hugo-") as temp:
        temp = Path(temp)
        if system == "darwin":
            package = temp / name
            package.write_bytes(payload)
            subprocess.run(["/usr/sbin/pkgutil", "--expand-full", str(package), str(temp / "expanded")], check=True)
            choices = [p for p in (temp / "expanded").rglob("hugo") if p.is_file()]
            if len(choices) != 1:
                raise RuntimeError("Expected exactly one Hugo binary in the official package.")
            binary = choices[0].read_bytes()
        else:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
                matches = [m for m in archive.getmembers() if m.name in {"hugo", "./hugo"} and m.isfile()]
                if len(matches) != 1:
                    raise RuntimeError("Expected one Hugo binary in the official archive.")
                binary = archive.extractfile(matches[0]).read()
        stage = target.with_suffix(".download")
        stage.write_bytes(binary)
        stage.chmod(0o755)
        os.replace(stage, target)
    return target
