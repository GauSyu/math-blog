"""End-to-end publication behavior with the pinned Hugo binary."""
from pathlib import Path
import importlib.util
from html import unescape
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
HUGO = ROOT / ".cache/bin/hugo"
spec = importlib.util.spec_from_file_location("articles", ROOT / "tools/articles.py")
articles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(articles)

class SiteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="math-blog-site-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ["themes", "layouts", "assets", "static", "archetypes"]:
            shutil.copytree(ROOT / name, self.root / name)
        shutil.copyfile(ROOT / "hugo.toml", self.root / "hugo.toml")
        (self.root / "content/posts").mkdir(parents=True)
        for name in ["_index.md", "search.md"]:
            shutil.copyfile(ROOT / "content" / name, self.root / "content" / name)
        shutil.copytree(ROOT / "content/about", self.root / "content/about")
        shutil.copyfile(ROOT / "content/posts/_index.md", self.root / "content/posts/_index.md")

    def build(self, timezone="UTC", drafts=False):
        args = [str(HUGO), "--source", str(self.root), "--cleanDestinationDir", "--panicOnWarning"]
        if drafts: args.append("--buildDrafts")
        result = subprocess.run(args, capture_output=True, text=True, env=dict(os.environ, TZ=timezone, HUGO_CACHEDIR=str(self.root / "cache")))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def read(self, path):
        return (self.root / "public" / path).read_text()

    def test_publication_date_is_stable_across_host_timezones_and_mtime(self):
        path = articles.new_article(self.root, "sample-calculation", "A sample calculation")
        with path.open("ab") as out:
            out.write(b"\n\nFor $x_i$, consider\n\n$$\nx_i^2.\n$$\n")
        articles.publish_article(self.root, "sample-calculation", "2024-02-03")
        for timezone in ["UTC", "America/Los_Angeles", "Asia/Shanghai"]:
            with self.subTest(timezone=timezone):
                os.utime(path, (1999999999, 1999999999))
                self.build(timezone)
                html = unescape(self.read("posts/sample-calculation/index.html"))
                self.assertIn('datetime="2024-02-03T00:00:00+08:00"', html)
                self.assertIn(">2024-02-03</time>", html)
                self.assertNotIn("Updated", html)
                self.assertIn('class="katex-display"', html)
                search = json.loads(self.read("index.json"))
                self.assertEqual(search[0]["dateLabel"], "2024-02-03")
                rss = ET.fromstring(self.read("index.xml"))
                item = rss.find("channel/item")
                self.assertIn("03 Feb 2024", item.findtext("pubDate"))
                self.assertEqual(item.findtext("link"), "https://gausyu.top/math-blog/posts/sample-calculation/")

    def test_drafts_and_future_posts_never_leak_into_production_routes_or_indexes(self):
        articles.new_article(self.root, "private-draft", "PrivateDraftSentinel")
        articles.new_article(self.root, "future-post", "FuturePostSentinel")
        articles.publish_article(self.root, "future-post", "2999-01-01")
        self.build()
        for route in ["index.html", "posts/index.html", "tags/index.html", "index.json", "index.xml", "sitemap.xml"]:
            self.assertNotIn("PrivateDraftSentinel", self.read(route))
            self.assertNotIn("FuturePostSentinel", self.read(route))
        self.assertFalse((self.root / "public/posts/private-draft").exists())
        self.assertFalse((self.root / "public/posts/future-post").exists())
        self.build(drafts=True)
        search = json.loads(self.read("index.json"))
        draft = next(entry for entry in search if entry["title"] == "PrivateDraftSentinel")
        self.assertTrue(draft["draft"])
        self.assertEqual(draft["dateLabel"], "Draft")
        self.assertIn('class="draft-label">Draft', self.read("posts/private-draft/index.html"))

    def test_about_reuses_introduction_content_only_when_the_article_is_visible(self):
        import re

        introduction = articles.new_article(self.root, "introduction", "Introduction")
        sentinel = "SharedIntroductionBodySentinel"
        with introduction.open("ab") as out:
            out.write(f"\n\n{sentinel}: A short introduction written in one place.\n".encode())

        def prose(html):
            match = re.search(r'<div class="prose">\s*(.*?)\s*</div>', html, re.DOTALL)
            self.assertIsNotNone(match, "page renders its body in .prose")
            return unescape(match[1].strip())

        self.build()
        about = self.read("about/index.html")
        self.assertNotIn(sentinel, about)
        self.assertIn('href="https://gausyu.top/"', about)

        self.build(drafts=True)
        about = self.read("about/index.html")
        article = self.read("posts/introduction/index.html")
        self.assertIn(sentinel, prose(about))
        self.assertEqual(prose(about), prose(article))
        self.assertIn('class="draft-label">Draft', about)
        self.assertIn('class="draft-label">Draft', article)

        articles.publish_article(self.root, "introduction", "2024-02-03")
        self.build()
        about = self.read("about/index.html")
        article = unescape(self.read("posts/introduction/index.html"))
        self.assertIn(sentinel, prose(about))
        self.assertEqual(prose(about), prose(article))
        self.assertNotIn('class="draft-label">Draft', about)
        self.assertIn('datetime="2024-02-03T00:00:00+08:00"', article)
        entries = json.loads(self.read("index.json"))
        self.assertEqual(sum(entry["title"] == "Introduction" for entry in entries), 1)

    def test_empty_journal_has_all_navigation_destinations_and_feed(self):
        self.build()
        for route in ["index.html", "posts/index.html", "tags/index.html", "search/index.html", "about/index.html", "index.xml"]:
            self.assertTrue(self.read(route))
        self.assertEqual(json.loads(self.read("index.json")), [])
        self.assertIn("https://gausyu.top/MathBlog/", self.read("index.html"))

if __name__ == "__main__":
    unittest.main()
