#!/usr/bin/env python3
"""Writing and local build commands; no remote publishing operations."""
import argparse
import functools
import http.server
import os
from pathlib import Path
import subprocess
import sys
import time
from runtime import ensure_hugo

ROOT = Path(__file__).resolve().parent.parent

def preview_site(root, hugo, port, env):
    """Watch diagram inputs alongside Hugo's content/asset live reload."""
    from tikz import OUTPUT_DIRECTORY, prepare_tikz
    prepare_tikz(root, include_drafts=True)
    command = [
        str(hugo), "server", "--buildDrafts", "--bind", "127.0.0.1", "--port", str(port),
        "--disableFastRender", "--renderToMemory",
    ]

    def start():
        return subprocess.Popen(command, cwd=root, env=env)

    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def snapshot():
        return tuple((str(path), path.stat().st_mtime_ns) for path in sorted((root / OUTPUT_DIRECTORY).rglob('*.svg')))

    generated = snapshot()
    process = start()
    previous_error = None
    try:
        while process.poll() is None:
            time.sleep(0.75)
            try:
                prepare_tikz(root, include_drafts=True)
            except (ValueError, RuntimeError, OSError) as error:
                message = str(error)
                if message != previous_error:
                    print("TikZ preview error: " + message, file=sys.stderr, flush=True)
                previous_error = message
            else:
                if previous_error is not None:
                    print("TikZ preview recovered.", flush=True)
                previous_error = None
            current = snapshot()
            if current != generated:
                # Hugo may retain replaced/deleted leaf resources in memory.
                # A fresh server makes both updates and failed compilations
                # observable at the same URL without serving an old diagram.
                stop(process)
                process = start()
                generated = current
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, process.args)
    except KeyboardInterrupt:
        pass
    finally:
        stop(process)

def main():
    parser = argparse.ArgumentParser(description="Local math blog workflow; no Git push or website deployment.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    new = sub.add_parser("new")
    new.add_argument("slug"); new.add_argument("title")
    publish = sub.add_parser("publish")
    publish.add_argument("slug"); publish.add_argument("--date", required=True)
    sub.add_parser("check")
    sub.add_parser("build")
    preview = sub.add_parser("preview")
    preview.add_argument("--port", type=int, default=1313)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=1314)
    args = parser.parse_args()
    from articles import new_article, publish_article, validate_articles
    if args.command == "new":
        print(new_article(ROOT, args.slug, args.title)); return
    if args.command == "publish":
        print(publish_article(ROOT, args.slug, args.date)); return
    if args.command == "serve":
        if not (ROOT / "public/index.html").is_file():
            parser.error("Run ./blog build first.")
        base = ROOT / ".cache/serve-root"
        base.mkdir(parents=True, exist_ok=True)
        link = base / "math-blog"
        if not link.exists(): link.symlink_to(ROOT / "public", target_is_directory=True)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(base))
        print("http://127.0.0.1:" + str(args.port) + "/math-blog/", flush=True)
        http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()
        return
    hugo = ensure_hugo(ROOT)
    from vendor_math import verify_math
    verify_math(ROOT)
    if args.command == "setup":
        subprocess.run([str(hugo), "version"], check=True); return
    validate_articles(ROOT)
    env = dict(os.environ, HUGO_CACHEDIR=str(ROOT / ".cache/hugo-build"))
    if args.command == "check":
        subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, env=env, check=True)
    elif args.command == "build":
        from tikz import prepare_tikz
        prepare_tikz(ROOT)
        subprocess.run([str(hugo), "--cleanDestinationDir", "--panicOnWarning"], cwd=ROOT, env=env, check=True)
        print("Built public/; no remote changes.")
    elif args.command == "preview":
        preview_site(ROOT, hugo, args.port, env)

if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print("Error: " + str(error), file=sys.stderr)
        sys.exit(1)
