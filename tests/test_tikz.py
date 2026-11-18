from pathlib import Path
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import tikz


NOW = dt.datetime(2026, 11, 18, 12, tzinfo=dt.timezone.utc)
SIMPLE = r"""\documentclass[tikz,border=2pt]{standalone}
\begin{document}
\begin{tikzpicture}
\draw[->] (0,0) -- (2,0) node[right] {$x$};
\draw (0,0) circle (0.5);
\end{tikzpicture}
\end{document}
"""
COMMUTATIVE = r"""\documentclass[border=2pt]{standalone}
\usepackage{tikz-cd}
\begin{document}
\begin{tikzcd}
A \arrow[r,"f"] \arrow[d,"g"'] & B \arrow[d,"h"] \\
C \arrow[r,"k"'] & D
\end{tikzcd}
\end{document}
"""


def stroked_paths(svg):
    found = []
    def visit(element, stroke=None):
        stroke = element.get("stroke", stroke)
        if element.tag == "{http://www.w3.org/2000/svg}path" and stroke and stroke != "none":
            found.append(element)
        for child in element:
            visit(child, stroke)
    visit(svg)
    return found


def has_tools():
    try:
        return all(tikz._tool(name).is_file() for name in ("latex", "dvisvgm"))
    except RuntimeError:
        return False


class TikzTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="math-blog-tikz-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "content/posts/example"
        self.bundle.mkdir(parents=True)
        self.index = self.bundle / "index.md"
        self.article()

    def article(self, draft=False, date="2020-01-01T00:00:00Z"):
        self.index.write_text(f'+++\ntitle="Example"\nslug="example"\ndraft={str(draft).lower()}\ndate={date}\n+++\n\n![Example](diagrams/example.svg)\n')

    def diagram(self, body=SIMPLE, name="example.tex"):
        target = self.bundle / "diagrams" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        return target


class TikzSelectionTest(TikzTestCase):
    def test_no_diagrams_or_excluded_articles_require_no_tools(self):
        with mock.patch.object(tikz, "_tool", side_effect=AssertionError("Unexpected TeX lookup")):
            self.assertEqual(tikz.prepare_tikz(self.root, now=NOW), [])
            self.assertTrue((self.root / tikz.OUTPUT_DIRECTORY).is_dir())
            self.diagram()
            self.article(draft=True)
            self.assertEqual(tikz.prepare_tikz(self.root, now=NOW), [])
            self.article(date="2099-01-01T00:00:00Z")
            self.assertEqual(tikz.prepare_tikz(self.root, include_drafts=True, now=NOW), [])

    def test_tex_attachments_outside_diagrams_are_not_compiled(self):
        (self.bundle / "paper.tex").write_text("Not a diagram")
        with mock.patch.object(tikz, "_tool", side_effect=AssertionError("Unexpected TeX lookup")):
            self.assertEqual(tikz.prepare_tikz(self.root, now=NOW), [])

    def test_missing_tools_remove_existing_generated_image(self):
        self.diagram()
        output = self.root / tikz.OUTPUT_DIRECTORY / "posts/example/diagrams/example.svg"
        output.parent.mkdir(parents=True)
        output.write_text("stale")
        with mock.patch.object(tikz, "_tool", side_effect=RuntimeError("cannot find latex")):
            with self.assertRaisesRegex(RuntimeError, "cannot find latex"):
                tikz.prepare_tikz(self.root, now=NOW)
        self.assertFalse(output.exists())

    def test_existing_article_svg_is_preserved_and_collision_is_rejected(self):
        source = self.diagram()
        original = source.with_suffix(".svg")
        original.write_text("Author's existing SVG")
        with mock.patch.object(tikz, "_tool", side_effect=AssertionError("Unexpected TeX lookup")):
            with self.assertRaisesRegex(ValueError, "conflicts with an existing article resource"):
                tikz.prepare_tikz(self.root, now=NOW)
        self.assertEqual(original.read_text(), "Author's existing SVG")

    def test_compiler_timeout_is_reported(self):
        with mock.patch.object(tikz.subprocess, "run", side_effect=subprocess.TimeoutExpired("latex", 1)):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                tikz._run(["latex", "example.tex"], self.root, timeout=1)


@unittest.skipUnless(has_tools() or os.environ.get("MATH_BLOG_REQUIRE_TEX") == "1", "Install TeX Live/MacTeX and dvisvgm to exercise real diagrams.")
class TikzCompilationTest(TikzTestCase):
    def test_tikz_and_tikzcd_generate_self_contained_svg_and_cache(self):
        plain = self.diagram()
        cd = self.diagram(COMMUTATIVE, "square.tex")
        originals = {path: path.read_bytes() for path in (self.index, plain, cd)}
        outputs = tikz.prepare_tikz(self.root, now=NOW)
        self.assertEqual(len(outputs), 2)
        for output in outputs:
            element = ET.fromstring(output.read_bytes())
            self.assertEqual(element.tag, "{http://www.w3.org/2000/svg}svg")
            self.assertTrue(element.get("viewBox"))
            self.assertIn(b"<path", output.read_bytes())
            self.assertNotIn(b"<font", output.read_bytes())
            strokes = stroked_paths(element)
            self.assertGreaterEqual(len(strokes), 2, "Geometric paths must survive independently of font glyphs.")
            if output.name == "square.svg":
                self.assertGreaterEqual(len(strokes), 8, "All four arrow shafts and heads must survive conversion.")
        stamps = {path: path.stat().st_mtime_ns for path in outputs}
        with mock.patch.object(tikz, "_compile", side_effect=AssertionError("Unexpected recompilation")):
            self.assertEqual(tikz.prepare_tikz(self.root, now=NOW), outputs)
        self.assertEqual(stamps, {path: path.stat().st_mtime_ns for path in outputs})
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})
        self.assertFalse(list(self.bundle.rglob("*.aux")))
        self.assertFalse(list(self.bundle.rglob("*.dvi")))

    def test_geometry_without_any_text_is_visible_without_ghostscript(self):
        self.diagram(SIMPLE.replace(r" node[right] {$x$}", ""))
        output, = tikz.prepare_tikz(self.root, now=NOW)
        svg = ET.fromstring(output.read_bytes())
        self.assertGreater(float(svg.get("viewBox").split()[2]), 0)
        paths = stroked_paths(svg)
        self.assertGreaterEqual(len(paths), 2)

    def test_postscript_drawing_is_rejected_instead_of_silently_dropped(self):
        self.diagram(SIMPLE.replace(r"\draw (0,0) circle (0.5);", r"\special{ps: newpath 0 0 moveto 10 10 lineto stroke}"))
        with self.assertRaisesRegex(RuntimeError, "unsupported PostScript drawing specials"):
            tikz.prepare_tikz(self.root, now=NOW)

    def test_relative_input_change_rebuilds_and_failed_build_removes_old_output(self):
        self.diagram(SIMPLE.replace(r"\draw (0,0) circle (0.5);", r"\input{parts/circle.tex}"))
        part = self.bundle / "diagrams/parts/circle.tex"
        part.parent.mkdir()
        part.write_text(r"\draw (0,0) circle (0.5);")
        output, = tikz.prepare_tikz(self.root, now=NOW)
        first = output.read_bytes()
        part.write_text(r"\draw (0,0) circle (1.5);")
        tikz.prepare_tikz(self.root, now=NOW)
        self.assertNotEqual(first, output.read_bytes())
        part.unlink()
        with self.assertRaisesRegex(RuntimeError, "Cannot build TikZ diagram"):
            tikz.prepare_tikz(self.root, now=NOW)
        self.assertFalse(output.exists())

    def test_relative_include_dependency_is_compiled_and_tracked(self):
        self.diagram(r"\documentclass{article}\usepackage{tikz}\pagestyle{empty}\begin{document}\include{parts/picture}\end{document}")
        part = self.bundle / "diagrams/parts/picture.tex"
        part.parent.mkdir()
        part.write_text(r"\begin{tikzpicture}\draw(0,0)--(1,1);\end{tikzpicture}")
        output, = tikz.prepare_tikz(self.root, now=NOW)
        first = output.read_bytes()
        part.write_text(r"\begin{tikzpicture}\draw(0,0)--(2,1);\end{tikzpicture}")
        tikz.prepare_tikz(self.root, now=NOW)
        self.assertNotEqual(first, output.read_bytes())
        self.assertFalse(list(self.bundle.rglob("*.aux")))

    def test_source_removal_and_draft_filter_prune_cached_output(self):
        source = self.diagram()
        output, = tikz.prepare_tikz(self.root, now=NOW)
        self.article(draft=True)
        self.assertEqual(tikz.prepare_tikz(self.root, now=NOW), [])
        self.assertFalse(output.exists())
        output, = tikz.prepare_tikz(self.root, include_drafts=True, now=NOW)
        self.assertTrue(output.exists())
        source.unlink()
        self.assertEqual(tikz.prepare_tikz(self.root, include_drafts=True, now=NOW), [])
        self.assertFalse(output.exists())

    def test_multiple_pages_are_rejected(self):
        self.diagram(r"\documentclass{article}\begin{document}one\newpage two\end{document}")
        with self.assertRaisesRegex(RuntimeError, "exactly one page"):
            tikz.prepare_tikz(self.root, now=NOW)

    def test_generated_resource_mount_is_published_by_real_hugo(self):
        hugo = ROOT / ".cache/bin/hugo"
        if not hugo.is_file():
            self.skipTest("Run ./blog setup first.")
        self.diagram()
        tikz.prepare_tikz(self.root, now=NOW)
        (self.root / "layouts").mkdir()
        (self.root / "layouts/single.html").write_text("{{ .Content }}")
        (self.root / "layouts/home.html").write_text("Home")
        (self.root / "hugo.toml").write_text("""baseURL='https://example.test/math-blog/'
disableKinds=['taxonomy','term','RSS','sitemap','section']
[module]
[[module.mounts]]
source='content'
target='content'
[[module.mounts]]
source='.cache/tikz-content'
target='content'
""")
        result = subprocess.run([str(hugo), "--source", str(self.root), "--panicOnWarning"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        page = self.root / "public/posts/example/index.html"
        self.assertIn('src="diagrams/example.svg"', page.read_text())
        self.assertTrue((page.parent / "diagrams/example.svg").is_file())
