#!/usr/bin/env python3
"""Writing and local build commands; no remote publishing operations."""
import argparse
import functools
import http.server
import os
from pathlib import Path
import subprocess
import sys
from runtime import ensure_hugo

ROOT = Path(__file__).resolve().parent.parent

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
        subprocess.run([str(hugo), "--cleanDestinationDir", "--panicOnWarning"], cwd=ROOT, env=env, check=True)
        print("Built public/; no remote changes.")
    elif args.command == "preview":
        subprocess.run([str(hugo), "server", "--buildDrafts", "--bind", "127.0.0.1", "--port", str(args.port), "--disableFastRender", "--renderToMemory"], cwd=ROOT, env=env, check=True)

if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print("Error: " + str(error), file=sys.stderr)
        sys.exit(1)
