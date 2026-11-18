"""Exercise the diagram watcher through real HTTP requests to Hugo preview."""
from pathlib import Path
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import tikz

HUGO = ROOT / '.cache/bin/hugo'
try:
    TEX_AVAILABLE = all(tikz._tool(name).is_file() for name in ('latex', 'dvisvgm'))
except RuntimeError:
    TEX_AVAILABLE = False


@unittest.skipUnless(HUGO.is_file() and (TEX_AVAILABLE or os.environ.get('MATH_BLOG_REQUIRE_TEX') == '1'),
                     'Requires the pinned Hugo plus TeX Live/MacTeX and dvisvgm.')
class DiagramPreviewTest(unittest.TestCase):
    def test_changed_failed_and_repaired_diagrams_are_reflected_over_http(self):
        with tempfile.TemporaryDirectory(prefix='math-blog-preview-test-') as temporary:
            root = Path(temporary)
            bundle = root / 'content/posts/example'
            (bundle / 'diagrams').mkdir(parents=True)
            (bundle / 'index.md').write_text('+++\ntitle="Example"\nslug="example"\ndraft=true\n+++\n\n![Diagram](diagrams/example.svg)\n')
            source = bundle / 'diagrams/example.tex'
            original = r'\documentclass[tikz]{standalone}\begin{document}\tikz\draw (0,0)--(1,1);\end{document}'
            source.write_text(original)
            (root / 'layouts').mkdir()
            (root / 'layouts/single.html').write_text('{{ .Content }}')
            (root / 'layouts/home.html').write_text('Home')
            (root / 'hugo.toml').write_text("""baseURL='https://example.test/math-blog/'
disableKinds=['taxonomy','term','RSS','sitemap','section']
[[module.mounts]]
source='content'
target='content'
[[module.mounts]]
source='.cache/tikz-content'
target='content'
""")
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            runner = ('from pathlib import Path;import os,sys;sys.path.insert(0,sys.argv[1]);'
                      'from blog import preview_site;'
                      'preview_site(Path(sys.argv[2]),Path(sys.argv[3]),int(sys.argv[4]),'
                      'dict(os.environ,HUGO_CACHEDIR=sys.argv[2]+"/.cache/hugo"))')
            url = f'http://127.0.0.1:{port}/math-blog/posts/example/diagrams/example.svg'
            with (root / 'preview.log').open('w+') as log:
                process = subprocess.Popen([sys.executable, '-B', '-c', runner, str(ROOT / 'tools'),
                                            str(root), str(HUGO), str(port)], stdout=log, stderr=subprocess.STDOUT)
                def wait_for(condition):
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        try:
                            with urllib.request.urlopen(url, timeout=1) as response:
                                result = response.status, response.read()
                        except urllib.error.HTTPError as error:
                            result = error.code, b''
                        except (urllib.error.URLError, TimeoutError, ConnectionError):
                            result = 0, b''
                        if condition(result):
                            return result
                        if process.poll() is not None:
                            break
                        time.sleep(.2)
                    log.seek(0)
                    self.fail('Diagram preview did not reach the expected state:\n' + log.read()[-6000:])
                try:
                    _, first = wait_for(lambda result: result[0] == 200)
                    source.write_text(original.replace('(1,1)', '(2,2)'))
                    wait_for(lambda result: result[0] == 200 and result[1] != first)
                    source.write_text(r'\documentclass{standalone}\begin{document}\invalidcommand\end{document}')
                    wait_for(lambda result: result[0] == 404)
                    source.write_text(original)
                    wait_for(lambda result: result[0] == 200 and result[1] == first)
                finally:
                    if process.poll() is None:
                        process.send_signal(signal.SIGINT)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
