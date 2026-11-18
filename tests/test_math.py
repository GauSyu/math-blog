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
    def render_pages(self, pages, global_macros="", with_about=False):
        with tempfile.TemporaryDirectory(prefix="math-blog-render-test-") as temporary:
            root = Path(temporary)
            (root / "layouts/_markup").mkdir(parents=True)
            shutil.copyfile(ROOT / "layouts/_markup/render-passthrough.html", root / "layouts/_markup/render-passthrough.html")
            shutil.copytree(ROOT / "layouts/partials/math", root / "layouts/partials/math")
            (root / "layouts/shortcodes").mkdir()
            shutil.copyfile(ROOT / "layouts/shortcodes/eqref.html", root / "layouts/shortcodes/eqref.html")
            (root / "data").mkdir()
            (root / "data/math.toml").write_text(global_macros or "macros = []\n", encoding="utf-8")
            (root / "layouts/baseof.html").write_text('{{ block "main" . }}{{ end }}', encoding="utf-8")
            (root / "layouts/single.html").write_text('{{ define "main" }}{{ .Content }}{{ end }}', encoding="utf-8")
            (root / "layouts/home.html").write_text("Test home", encoding="utf-8")
            (root / "layouts/list.html").write_text("Test list", encoding="utf-8")
            if with_about:
                shutil.copyfile(ROOT / "layouts/about.html", root / "layouts/about.html")
            for path, content in pages.items():
                body, frontmatter = content if isinstance(content, tuple) else (content, "")
                source = root / "content" / path
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text('+++\ntitle = "Math test"\ndate = 2020-01-01T00:00:00Z\n' + frontmatter + '\n+++\n\n' + body, encoding="utf-8")
            (root / "hugo.toml").write_text("""baseURL = 'https://example.test/math-blog/'
disableKinds = ['taxonomy', 'term', 'RSS', 'sitemap']
[markup.goldmark.extensions.passthrough]
enable = true
[markup.goldmark.extensions.passthrough.delimiters]
block = [['$$', '$$'], ['\\[', '\\]']]
inline = [['$', '$'], ['\\(', '\\)']]
""", encoding="utf-8")
            result = subprocess.run([str(HUGO), "--source", str(root), "--destination", str(root / "public"), "--panicOnWarning"], capture_output=True, text=True, env=dict(os.environ, HUGO_CACHEDIR=str(root / "cache")))
            output = {str(path.relative_to(root / "public")): path.read_text(encoding="utf-8") for path in (root / "public").rglob("*.html")} if (root / "public").is_dir() else {}
            return result, output

    def render(self, body, **kwargs):
        result, output = self.render_pages({"posts/example.md": body}, **kwargs)
        return result, output.get("posts/example/index.html", "")

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

    def test_semantic_macros_preserve_case_arguments_and_article_scope(self):
        global_macros = r"""[[macros]]
name = '\derivedHom'
definition = '\operatorname{RHom}(#1,#2)'
[[macros]]
name = '\Scope'
definition = '\operatorname{Global}'
[[macros]]
name = '\labelledObject'
definition = 'L'
"""
        local = r"""[[math.macros]]
name = '\Scope'
definition = '\operatorname{Local}'
"""
        result, output = self.render_pages({
            "posts/example.md": (r"$\derivedHom{X}{Y}$ and $\Scope$ and $\labelledObject$" + "\n\n$$\nx \\label{eq:macro}\n$$", local),
            "posts/other.md": r"$\Scope$",
        }, global_macros=global_macros)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("RHom", output["posts/example/index.html"])
        self.assertIn("Local", output["posts/example/index.html"])
        self.assertNotIn("Global", output["posts/example/index.html"])
        self.assertIn("Global", output["posts/other/index.html"])
        self.assertNotIn("Local", output["posts/other/index.html"])

    def test_labelled_displays_number_in_order_and_support_forward_references(self):
        result, html = self.render(r"""See {{< eqref "eq:second" >}} and $\eqref{eq:first}+\ref{eq:second}$.

$$
x=1 \label{eq:first}
$$

\[
y=2
\]

$$
\begin{aligned}
z&=x+y\\
w&=z+1
\end{aligned}
\label{eq:second}
$$
""")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(html.count('id="eq-eq:first"'), 1)
        self.assertEqual(html.count('id="eq-eq:second"'), 1)
        self.assertIn('href="#eq-eq:second">(2)</a>', html)
        self.assertIn(r"\tag{1}", html)
        self.assertIn(r"\tag{2}", html)
        self.assertIn("(1)+2", html)
        self.assertNotIn("hugo-equation-label", html)

    def test_code_examples_and_tex_comments_do_not_define_labels(self):
        result, html = self.render(r"""See {{< eqref "eq:actual" >}}.

```tex
$$
x \label{eq:actual}
$$
```

`$\label{eq:actual}$`

$$
x\% = 1 % \label{eq:ignored} \eqref{eq:missing}
\label{eq:actual}
$$
""")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('href="#eq-eq:actual">(1)</a>', html)
        self.assertEqual(html.count('id="eq-eq:actual"'), 1)
        self.assertNotIn('id="eq-eq:ignored"', html)
        self.assertIn(r"x\% = 1", html)

    def test_mutual_cross_article_references_resolve_without_content_recursion(self):
        result, output = self.render_pages({
            "posts/example.md": '{{< eqref "eq:other" "/posts/other" >}}\n\n$$\nx=1 \\label{eq:here}\n$$',
            "posts/other.md": '{{< eqref "eq:here" "/posts/example" >}}\n\n$$\ny=2 \\label{eq:other}\n$$',
        })
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('href="/math-blog/posts/other/#eq-eq:other">(1)</a>', output["posts/example/index.html"])
        self.assertIn('href="/math-blog/posts/example/#eq-eq:here">(1)</a>', output["posts/other/index.html"])

    def test_tex_comment_tokenization_is_left_to_katex(self):
        result, html = self.render("$$\n\\text{a% comment\nc} + \\alpha% comment\nx \\label{eq:comments}% final comment\n$$")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("<mtext>ac</mtext>", html)
        self.assertIn("<mi>α</mi><mi>x</mi>", html)
        self.assertIn(r"\tag{1}", html)

    def test_about_can_reuse_numbered_introduction_without_duplicate_ids(self):
        result, output = self.render_pages({
            "posts/introduction.md": 'See {{< eqref "eq:intro" >}}.\n\n$$\nx=1 \\label{eq:intro}\n$$',
            "about.md": ("Fallback", 'layout = "about"'),
        }, with_about=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for path in ["posts/introduction/index.html", "about/index.html"]:
            self.assertEqual(output[path].count('id="eq-eq:intro"'), 1)
            self.assertIn('href="#eq-eq:intro">(1)</a>', output[path])

    def test_bad_labels_references_and_macro_definitions_fail_build(self):
        failures = [
            ("$$\nx=1 \\label{eq:dup}\n$$\n\n$$\ny=2 \\label{eq:dup}\n$$", "Duplicate equation label"),
            ("$$\nx \\label{eq:one} \\label{eq:two}\n$$", "one equation label per display"),
            ('{{< eqref "eq:missing" >}}', "Unknown equation label"),
            (r"$\eqref{eq:missing}$", "Unknown equation label"),
            ('{{< eqref "eq:missing" "/posts/missing" >}}', "Unknown equation reference page"),
            (r"$x\label{eq:inline}$", "require display math"),
            ("$$\nx\\label{bad label}\n$$", "Invalid equation label"),
            ("$$\nx\\label{eq:manual}\\tag{A}\n$$", "do not combine label and tag"),
        ]
        for body, message in failures:
            with self.subTest(message=message):
                result, _ = self.render(body)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr + result.stdout)
                self.assertIn("example.md", result.stderr + result.stdout)
        for macros, message in [
            ("macros = {bad = 'x'}", "must be an array"),
            ("[[macros]]\nname='bad'\ndefinition='x'", "Invalid or reserved semantic macro name"),
            ("[[macros]]\nname='\\Scope'\ndefinition='x'\n[[macros]]\nname='\\Scope'\ndefinition='y'", "Duplicate semantic macro"),
        ]:
            with self.subTest(macros=macros):
                result, _ = self.render("$x$", global_macros=macros)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
