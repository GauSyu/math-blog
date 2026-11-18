from pathlib import Path
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
HUGO = ROOT / ".cache/bin/hugo"
spec = importlib.util.spec_from_file_location("vendor_math", ROOT / "tools/vendor_math.py")
vendor_math = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vendor_math)


class MathAssetsTest(unittest.TestCase):
    def test_committed_assets_are_complete_and_verify_offline(self):
        with mock.patch.object(vendor_math.urllib.request, "urlopen", side_effect=AssertionError("Unexpected network access")):
            target = vendor_math.ensure_math(ROOT)
            manifest = vendor_math.verify_math(ROOT)
        self.assertEqual(manifest["version"], "0.18.4")
        self.assertEqual(manifest["hugoVersion"], "0.170.0")
        self.assertTrue((target / "LICENSE").is_file())
        self.assertGreater(len(manifest["files"]), 20)
        self.assertFalse(any(target.rglob("*.js")))

    def test_changed_asset_is_rejected_instead_of_redownloaded(self):
        with tempfile.TemporaryDirectory(prefix="math-blog-assets-test-") as temporary:
            root = Path(temporary)
            target = root / "static/assets/katex"
            shutil.copytree(ROOT / "static/assets/katex", target)
            (target / "katex.min.css").write_text("changed", encoding="utf-8")
            with mock.patch.object(vendor_math.urllib.request, "urlopen", side_effect=AssertionError("Unexpected network access")):
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    vendor_math.ensure_math(root)


@unittest.skipUnless(HUGO.is_file(), "Run ./blog setup to install the pinned Hugo runtime.")
class MathRenderingTest(unittest.TestCase):
    def render(self, body):
        with tempfile.TemporaryDirectory(prefix="math-blog-render-test-") as temporary:
            root = Path(temporary)
            (root / "layouts/_markup").mkdir(parents=True)
            shutil.copyfile(ROOT / "layouts/_markup/render-passthrough.html", root / "layouts/_markup/render-passthrough.html")
            (root / "layouts/single.html").write_text("{{ .Content }}", encoding="utf-8")
            (root / "layouts/home.html").write_text("Test home", encoding="utf-8")
            (root / "content/posts").mkdir(parents=True)
            (root / "content/posts/example.md").write_text('+++\ntitle = "Math test"\ndate = 2020-01-01T00:00:00Z\n+++\n\n' + body, encoding="utf-8")
            (root / "hugo.toml").write_text("""baseURL = 'https://example.test/math-blog/'
disableKinds = ['taxonomy', 'term', 'RSS', 'sitemap']
[markup.goldmark.extensions.passthrough]
enable = true
[markup.goldmark.extensions.passthrough.delimiters]
block = [['$$', '$$'], ['\\[', '\\]']]
inline = [['$', '$'], ['\\(', '\\)']]
""", encoding="utf-8")
            result = subprocess.run([str(HUGO), "--source", str(root), "--destination", str(root / "public")], capture_output=True, text=True, env=dict(os.environ, HUGO_CACHEDIR=str(root / "cache")))
            output = root / "public/posts/example/index.html"
            return result, output.read_text(encoding="utf-8") if output.is_file() else ""

    def test_aligned_inline_and_bracket_math_preserve_tex(self):
        result, html = self.render(r"""For $x_i \in V$, use \(x_i^2\).

$$
\begin{aligned}
f(x_i) &= x_i^2 \\
g(x_i) &= \frac{x_i}{1+x_i}.
\end{aligned}
$$
""")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('class="katex-display"', html)
        self.assertIn('class="katex-mathml"', html)
        self.assertIn(r"x_i \in V", html)
        self.assertIn(r"\begin{aligned}", html)
        self.assertNotIn("katex-error", html)

    def test_footnotes_render_and_fenced_formulas_stay_literal(self):
        result, html = self.render("A statement.[^detail]\n\n[^detail]: Its term is $x_i$.\n\n```text\n$$\n\\notAnActualMathMacro{x_i}\n```\n\n`$x_i$`\n")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("footnote-ref", html)
        self.assertIn("katex", html)
        self.assertIn(r"\notAnActualMathMacro", html)
        self.assertIn("$$", html)
        self.assertIn("<code>$x_i$</code>", html)

    def test_invalid_tex_fails_build_with_source_position(self):
        for source in [r"$\notAnActualMathMacro{x}$", r"$\frac{1}{$"]:
            with self.subTest(source=source):
                result, _ = self.render(source)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid mathematical markup", result.stderr + result.stdout)
                self.assertIn("example.md", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
