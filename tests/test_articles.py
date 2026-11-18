import datetime as dt
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from articles import new_article, publish_article, validate_articles


class ArticleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="math-blog-articles-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "archetypes").mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[1] / "archetypes/default.md", self.root / "archetypes/default.md")

    def new(self, slug="test-article", title="Test article"):
        return new_article(self.root, slug, title)

    def metadata(self):
        return validate_articles(self.root)[0]

    def test_new_draft_safe_unicode_title_and_no_implicit_dates(self):
        title = '数学: "A"\n第二行 # [x] `$(touch unsafe)`'
        index = self.new(title=title)
        data = self.metadata()
        self.assertEqual(index, self.root / "content/posts/test-article/index.md")
        self.assertEqual(data["title"], title)
        self.assertEqual(data["slug"], "test-article")
        self.assertIs(data["draft"], True)
        self.assertEqual(data["tags"], [])
        self.assertNotIn("date", data)
        self.assertNotIn("lastmod", data)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["archetypes", "content"])

    def test_new_uses_the_archetype_body(self):
        archetype = self.root / "archetypes/default.md"
        with archetype.open("a", encoding="utf-8") as stream:
            stream.write("\nCustom prompt.\n")
        self.assertIn(b"Custom prompt.", self.new().read_bytes())

    def test_existing_article_is_never_overwritten(self):
        index = self.new()
        original = index.read_bytes()
        with self.assertRaisesRegex(ValueError, "已存在"):
            self.new(title="Second title")
        self.assertEqual(index.read_bytes(), original)

    def test_unsafe_slugs_and_blank_titles_do_not_create_content(self):
        for slug in ["../escape", "/absolute", "has/slash", "UPPER", "double--dash", "中文", "", "a" * 121]:
            with self.subTest(slug=slug), self.assertRaises(ValueError):
                self.new(slug=slug)
        for title in ["", "  "]:
            with self.subTest(title=title), self.assertRaises(ValueError):
                self.new(title=title)
        self.assertFalse((self.root / "content").exists())

    def test_publish_requires_an_explicit_valid_calendar_date(self):
        index = self.new()
        original = index.read_bytes()
        for date in ["", "today", "2026-1-01", "2026-02-29", "2026-04-31", "2026-13-01", "0000-01-01", None]:
            with self.subTest(date=date), self.assertRaises(ValueError):
                publish_article(self.root, "test-article", date)
            self.assertEqual(index.read_bytes(), original)

    def test_publish_preserves_body_bytes_and_uses_the_given_shanghai_date(self):
        index = self.new()
        body = b'\r\n\r\nFormula $X$.\r\n\r\n$$\r\n\\operatorname{Hom}(X,Y).\r\n$$\r\n\r\n```python\r\nx = "literal"\r\n```\r\n'
        index.write_bytes(b'+++\r\ntitle = "Test article"\r\nslug = "test-article"\r\ndraft = true # deliberate comment\r\ntags = []\r\n+++' + body)
        result = publish_article(self.root, "test-article", "2028-02-29")
        self.assertEqual(result, index)
        self.assertTrue(index.read_bytes().endswith(body))
        self.assertEqual(index.read_bytes().split(b"+++", 2)[2], body)
        self.assertIn(b"draft = false # deliberate comment", index.read_bytes())
        data = self.metadata()
        self.assertIs(data["draft"], False)
        self.assertEqual(data["date"], dt.datetime(2028, 2, 29, tzinfo=dt.timezone(dt.timedelta(hours=8))))
        self.assertNotIn("lastmod", data)
        self.assertFalse((self.root / "public").exists())
        self.assertFalse((self.root / ".git").exists())

    def test_publish_keeps_explicit_lastmod_unknown_fields_and_comments(self):
        index = self.new()
        original = '''+++
# keep this comment
title = "Test article"
slug = "test-article"
draft = true
lastmod = 2026-11-18T12:30:00+08:00
custom = "retain exactly"
notes = """A multiline string:
draft = true
date = "2020-01-01"
"""
[extra]
draft = true
date = "not an article date"
+++
Body remains.
'''
        index.write_text(original, encoding="utf-8")
        before = self.metadata()
        publish_article(self.root, "test-article", "2026-11-17")
        after = self.metadata()
        for field in ["title", "slug", "lastmod", "custom", "notes", "extra"]:
            self.assertEqual(before[field], after[field])
        self.assertIn("# keep this comment", index.read_text())
        self.assertTrue(index.read_text().endswith("\nBody remains.\n"))

    def test_an_existing_draft_date_is_explicitly_replaced(self):
        index = self.new()
        index.write_bytes(index.read_bytes().replace(b"draft = true", b'date = "2020-01-01" # planned date\ndraft = true'))
        publish_article(self.root, "test-article", "2026-11-17")
        self.assertEqual(self.metadata()["date"].date(), dt.date(2026, 11, 17))
        self.assertIn(b"# planned date", index.read_bytes())

    def test_published_articles_cannot_be_republished_by_the_command(self):
        index = self.new()
        publish_article(self.root, "test-article", "2026-11-17")
        original = index.read_bytes()
        with self.assertRaisesRegex(ValueError, "已发布"):
            publish_article(self.root, "test-article", "2026-11-18")
        self.assertEqual(index.read_bytes(), original)

    def test_missing_draft_and_invalid_front_matter_cannot_be_published(self):
        with self.assertRaisesRegex(ValueError, "找不到草稿"):
            publish_article(self.root, "missing", "2026-11-17")
        index = self.new()
        for original in [b"No front matter", b'+++\ntitle = [\n+++\nBody', b'+++\ntitle = "Only title"\n+++\nBody']:
            index.write_bytes(original)
            with self.subTest(original=original), self.assertRaises(ValueError):
                publish_article(self.root, "test-article", "2026-11-17")
            self.assertEqual(index.read_bytes(), original)

    def test_validation_requires_published_date_and_matching_slug(self):
        index = self.new()
        original = index.read_bytes()
        for modified in [original.replace(b"draft = true", b"draft = false"), original.replace(b'slug = "test-article"', b'slug = "another-slug"')]:
            index.write_bytes(modified)
            with self.subTest(modified=modified), self.assertRaises(ValueError):
                validate_articles(self.root)

    def test_assets_are_allowed_but_extra_content_formats_are_rejected(self):
        index = self.new()
        bundle = index.parent
        (bundle / "images").mkdir()
        (bundle / "images/figure.svg").write_text("<svg/>")
        (bundle / "paper.pdf").write_bytes(b"fixture attachment")
        self.assertEqual(len(validate_articles(self.root)), 1)
        for name in ["extra.md", "index.markdown", "images/nested.mdown", "extra.html", "extra.rst", "extra.adoc", "extra.org"]:
            extra = bundle / name
            extra.write_text("Unexpected content")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "额外内容文件"):
                validate_articles(self.root)
            extra.unlink()

    def test_top_level_markdown_outside_a_bundle_is_rejected(self):
        posts = self.root / "content/posts"
        posts.mkdir(parents=True)
        (posts / "misplaced.md").write_text("Wrong place")
        with self.assertRaises(ValueError):
            validate_articles(self.root)

    def test_finder_metadata_does_not_block_the_writing_workflow(self):
        index = self.new()
        metadata = index.parent.parent / '.DS_Store'
        metadata.write_bytes(b'Finder metadata')
        self.assertEqual([record['path'] for record in validate_articles(self.root)], [index])
        self.assertEqual(metadata.read_bytes(), b'Finder metadata')

    def test_hugo_section_index_is_not_counted_as_an_article(self):
        posts = self.root / "content/posts"
        posts.mkdir(parents=True)
        section = posts / "_index.md"
        section.write_text('+++\ntitle = "Archive"\n+++\nSection introduction.\n')
        self.assertEqual(validate_articles(self.root), [])
        index = self.new()
        self.assertEqual([record["path"] for record in validate_articles(self.root)], [index])
        section.unlink()
        target = self.root / "section-target.md"
        target.write_text('+++\ntitle = "Archive"\n+++\n')
        section.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            validate_articles(self.root)

    def test_symlinks_are_rejected_without_modifying_targets(self):
        index = self.new()
        target = self.root / "target.txt"
        target.write_text("Keep this target.")
        link = index.parent / "linked.txt"
        link.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            validate_articles(self.root)
        link.unlink()
        original = index.read_bytes()
        index.unlink()
        index.symlink_to(target)
        with self.assertRaises(ValueError):
            publish_article(self.root, "test-article", "2026-11-17")
        self.assertEqual(target.read_text(), "Keep this target.")
        index.unlink()
        index.write_bytes(original)
        linked_bundle = self.root / "content/posts/linked-bundle"
        linked_bundle.symlink_to(index.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            validate_articles(self.root)

    def test_publish_failure_leaves_original_and_removes_temporary_file(self):
        index = self.new()
        original = index.read_bytes()
        with mock.patch("articles.os.replace", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(OSError):
                publish_article(self.root, "test-article", "2026-11-17")
        self.assertEqual(index.read_bytes(), original)
        self.assertEqual([p.name for p in index.parent.iterdir()], ["index.md"])

    def test_publish_does_not_overwrite_a_concurrent_edit(self):
        index = self.new()
        original_replace = os.replace
        real_fsync = os.fsync
        changed = b"Concurrent user edit."
        def edit_during_sync(fd):
            real_fsync(fd)
            index.write_bytes(changed)
        with mock.patch("articles.os.fsync", side_effect=edit_during_sync), mock.patch("articles.os.replace", wraps=original_replace) as replace:
            with self.assertRaisesRegex(ValueError, "发布期间发生变化"):
                publish_article(self.root, "test-article", "2026-11-17")
            replace.assert_not_called()
        self.assertEqual(index.read_bytes(), changed)
        self.assertEqual([p.name for p in index.parent.iterdir()], ["index.md"])

    def test_new_template_cannot_prefill_publication_or_revision_dates(self):
        archetype = self.root / "archetypes/default.md"
        original = archetype.read_text()
        for field in ["date", "lastmod"]:
            archetype.write_text(original.replace("draft = true", f"draft = true\n{field} = 2026-11-17"))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "不预设"):
                self.new()
        self.assertFalse((self.root / "content/posts/test-article").exists())


if __name__ == "__main__":
    unittest.main()
